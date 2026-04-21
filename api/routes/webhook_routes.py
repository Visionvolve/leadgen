"""Webhook routes for external service callbacks (Resend email tracking).

Handles Resend webhook events for email delivery, opens, clicks,
bounces, and complaints. Updates EmailSendLog records accordingly.

No authentication required — webhooks come from Resend, not users.
Optional svix signature verification when RESEND_WEBHOOK_SECRET is configured.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from ..models import EmailSendLog, db

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/api/webhooks")

# Event type → handler mapping
SUPPORTED_EVENTS = {
    "email.delivered",
    "email.opened",
    "email.clicked",
    "email.bounced",
    "email.complained",
    # Phase 2 (LEADGEN-01 6th state): user clicked the List-Unsubscribe
    # one-click button or hit the mailto unsubscribe link. Resend reports
    # the unsubscribed_at timestamp through this event.
    "email.unsubscribed",
}


def _verify_svix_signature(payload_bytes: bytes, headers: dict) -> bool:
    """Verify Resend webhook signature using svix HMAC.

    Returns True if signature is valid or if no secret is configured (skip).
    Returns False if secret is configured but signature is invalid.
    """
    secret = os.environ.get("RESEND_WEBHOOK_SECRET", "")
    if not secret:
        return True  # No secret configured — skip verification

    svix_id = headers.get("svix-id", "")
    svix_timestamp = headers.get("svix-timestamp", "")
    svix_signature = headers.get("svix-signature", "")

    if not svix_id or not svix_timestamp or not svix_signature:
        logger.warning("Missing svix headers for webhook verification")
        return False

    # Resend/svix signs: "{svix_id}.{svix_timestamp}.{body}"
    to_sign = f"{svix_id}.{svix_timestamp}.".encode() + payload_bytes

    # Secret may have "whsec_" prefix — strip it and base64-decode
    if secret.startswith("whsec_"):
        import base64

        secret_bytes = base64.b64decode(secret[6:])
    else:
        secret_bytes = secret.encode()

    expected = hmac.new(secret_bytes, to_sign, hashlib.sha256).digest()

    import base64

    expected_b64 = base64.b64encode(expected).decode()

    # svix-signature can contain multiple signatures: "v1,<sig1> v1,<sig2>"
    for sig_part in svix_signature.split(" "):
        if sig_part.startswith("v1,"):
            sig_value = sig_part[3:]
            if hmac.compare_digest(expected_b64, sig_value):
                return True

    logger.warning("Svix signature verification failed")
    return False


def _parse_event_timestamp(body: dict) -> datetime:
    """Extract the event timestamp from the webhook payload.

    Resend places the authoritative event time at the top level as
    ``created_at`` (ISO-8601). Using that — rather than ``datetime.now()``
    at webhook-processing time — keeps the row's timestamp aligned with
    when the open/click actually happened, even if Resend retried
    delivery hours later. Falls back to the current UTC wall clock when
    ``created_at`` is missing or unparseable (tests, non-compliant
    proxies, etc.).
    """
    raw = body.get("created_at")
    if isinstance(raw, str) and raw:
        try:
            # ``datetime.fromisoformat`` in Py 3.11+ accepts the trailing
            # ``Z``. For older runtimes translate it to ``+00:00``.
            normalised = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
            parsed = datetime.fromisoformat(normalised)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            logger.warning("Resend webhook: unparseable created_at %r", raw)
    return datetime.now(timezone.utc)


@webhooks_bp.route("/resend", methods=["POST"])
def resend_webhook():
    """Handle Resend webhook events for email tracking.

    Resend sends POST requests with JSON body:
    {
        "type": "email.opened",
        "created_at": "2026-02-22T23:41:12.126Z",
        "data": {
            "email_id": "resend-message-id",
            "to": ["recipient@example.com"],
            ...
        }
    }

    All timestamp columns follow **earliest-observed** semantics: once
    set they are never overwritten by a later webhook delivery. Repeat
    deliveries from Resend's retry queue are therefore idempotent — they
    only bump ``open_count`` / ``click_count``.

    Always returns 200 to prevent Resend from retrying (except for
    signature failures which return 400 so Resend flags the endpoint).
    """
    payload_bytes = request.get_data()

    # Optional signature verification
    if not _verify_svix_signature(payload_bytes, dict(request.headers)):
        return jsonify({"error": "Invalid signature"}), 400

    body = request.get_json(silent=True)
    if not body:
        logger.warning("Resend webhook received empty or invalid JSON body")
        return jsonify({"status": "ignored", "reason": "no body"}), 200

    event_type = body.get("type", "")
    data = body.get("data", {})
    email_id = data.get("email_id", "")

    if event_type not in SUPPORTED_EVENTS:
        logger.warning("Resend webhook: unknown event type %r", event_type)
        return jsonify({"status": "ignored", "reason": "unknown event"}), 200

    if not email_id:
        logger.warning("Resend webhook %s: missing email_id in data", event_type)
        return jsonify({"status": "ignored", "reason": "no email_id"}), 200

    # Look up the send log by resend_message_id. Order by sent_at so that
    # when a pathological collision exists across tenants (data-migration
    # error) we deterministically pick the ORIGINAL sender rather than a
    # non-deterministic row — keeps multi-tenant isolation safe by
    # default.
    log = (
        db.session.query(EmailSendLog)
        .filter(EmailSendLog.resend_message_id == email_id)
        .order_by(EmailSendLog.sent_at.asc().nullslast())
        .first()
    )

    if not log:
        # Log at WARNING (not INFO) so production log dashboards surface
        # this — a flood of "unknown email_id" is the usual fingerprint
        # of a mis-match between what we store in ``resend_message_id``
        # and what Resend sends in webhook payloads.
        logger.warning(
            "Resend webhook %s: no EmailSendLog for email_id=%s",
            event_type,
            email_id,
        )
        return jsonify({"status": "ignored", "reason": "unknown email_id"}), 200

    event_time = _parse_event_timestamp(body)

    try:
        if event_type == "email.delivered":
            if not log.delivered_at:
                log.delivered_at = event_time
            # ``status`` tracks the latest transition — delivered is not
            # a terminal state, so allow it to advance from "sent" only.
            if log.status in (None, "queued", "sent"):
                log.status = "delivered"

        elif event_type == "email.opened":
            if not log.opened_at:
                log.opened_at = event_time
            log.open_count = (log.open_count or 0) + 1

        elif event_type == "email.clicked":
            if not log.clicked_at:
                log.clicked_at = event_time
            log.click_count = (log.click_count or 0) + 1

        elif event_type == "email.bounced":
            if not log.bounced_at:
                log.bounced_at = event_time
                bounce_data = data.get("bounce", {}) or {}
                # Preserve first-observed bounce_type too — a subsequent
                # "soft" retry must not downgrade an earlier "hard".
                log.bounce_type = bounce_data.get("type", "unknown")
            log.status = "bounced"

        elif event_type == "email.complained":
            if not log.complained_at:
                log.complained_at = event_time
            log.status = "complained"

        elif event_type == "email.unsubscribed":
            if not log.unsubscribed_at:
                log.unsubscribed_at = event_time
            log.status = "unsubscribed"

        db.session.commit()
        logger.info(
            "Resend webhook %s processed for email_id=%s (log=%s, tenant=%s)",
            event_type,
            email_id,
            log.id,
            log.tenant_id,
        )

    except Exception:
        db.session.rollback()
        logger.exception(
            "Resend webhook %s: error updating EmailSendLog %s",
            event_type,
            log.id,
        )

    return jsonify({"status": "ok"}), 200
