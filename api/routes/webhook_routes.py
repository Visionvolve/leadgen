"""Webhook routes for external service callbacks (Resend email tracking).

Handles Resend webhook events for email delivery, opens, clicks,
bounces, and complaints. Updates EmailSendLog records accordingly.

No user authentication required — webhooks come from Resend, not users.
Svix signature verification is MANDATORY (fail-closed): if
``RESEND_WEBHOOK_SECRET`` is missing or the signature does not match,
the request is rejected with HTTP 401.

There is no dev-bypass path. For local testing, set
``RESEND_WEBHOOK_SECRET`` in ``.env.dev`` to any value and sign test
payloads with that same secret (see ``tests/unit/test_webhook_routes.py``
for the signing helper).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from ..models import Activity, Contact, EmailSendLog, db

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


def _verify_svix_signature(payload_bytes: bytes, headers) -> bool:
    """Verify Resend webhook signature using svix HMAC.

    Fail-closed:
    - Missing or empty ``RESEND_WEBHOOK_SECRET`` → returns False, logs error.
    - Missing svix headers → returns False, logs error.
    - Bad signature → returns False, logs error.

    ``headers`` must be a ``werkzeug.datastructures.Headers`` instance (or
    any mapping with a case-insensitive ``.get()``). Do NOT pass
    ``dict(request.headers)`` — that normalizes keys to title case and
    breaks lowercase lookups like ``.get("svix-id")``.
    """
    secret = os.environ.get("RESEND_WEBHOOK_SECRET", "")

    if not secret:
        # Fail-closed: unconfigured secret means we cannot trust any
        # inbound payload. Previously this returned True (fail-open),
        # which allowed arbitrary forged events to update metrics.
        logger.error(
            "RESEND_WEBHOOK_SECRET not configured — rejecting webhook (fail-closed)"
        )
        return False

    # Werkzeug's Headers object is case-insensitive, so lowercase keys work.
    svix_id = headers.get("svix-id", "")
    svix_timestamp = headers.get("svix-timestamp", "")
    svix_signature = headers.get("svix-signature", "")

    if not svix_id or not svix_timestamp or not svix_signature:
        logger.error("Resend webhook: missing svix-* headers — rejecting (fail-closed)")
        return False

    # Resend/svix signs: "{svix_id}.{svix_timestamp}.{body}"
    to_sign = f"{svix_id}.{svix_timestamp}.".encode() + payload_bytes

    # Secret may have "whsec_" prefix — strip it and base64-decode
    if secret.startswith("whsec_"):
        secret_bytes = base64.b64decode(secret[6:])
    else:
        secret_bytes = secret.encode()

    expected = hmac.new(secret_bytes, to_sign, hashlib.sha256).digest()
    expected_b64 = base64.b64encode(expected).decode()

    # svix-signature can contain multiple signatures: "v1,<sig1> v1,<sig2>"
    for sig_part in svix_signature.split(" "):
        if sig_part.startswith("v1,"):
            sig_value = sig_part[3:]
            if hmac.compare_digest(expected_b64, sig_value):
                return True

    logger.error("Resend webhook: svix signature verification failed — rejecting")
    return False


def _suppress_contact_for_email(
    tenant_id: str,
    to_email: str | None,
    reason: str,
    event_time: datetime,
    *,
    campaign_id: str | None = None,
) -> None:
    """Flip ``contacts.is_suppressed`` for the recipient of a webhook event.

    BL-1105 (Unsubscribe Loop) — webhook-driven suppression for the three
    irreversible signals:

    * ``email.unsubscribed``  -> reason="resend_webhook"
    * ``email.bounced`` (hard) -> reason="hard_bounce"
    * ``email.complained``    -> reason="spam_complaint"

    Idempotent: if the contact is already suppressed we do NOT overwrite
    ``suppressed_at`` or ``suppression_reason`` and we do NOT write a
    duplicate Activity row — earliest-observed semantics, matching the
    EmailSendLog timestamp rules.

    Looks up the contact by ``(tenant_id, lower(email_address))``. If no
    such contact exists (e.g. extension-only contact later deleted) this
    is a no-op — the EmailSendLog audit row still gets the suppression
    timestamp, so we don't lose the signal.
    """
    if not to_email:
        return

    contact = (
        db.session.query(Contact)
        .filter(
            Contact.tenant_id == tenant_id,
            db.func.lower(Contact.email_address) == to_email.lower(),
        )
        .first()
    )
    if contact is None:
        logger.info(
            "Resend webhook: no contact for to_email=%s tenant=%s (skipping suppression)",
            to_email,
            tenant_id,
        )
        return

    if contact.is_suppressed:
        return  # idempotent — earliest-observed wins

    contact.is_suppressed = True
    contact.suppressed_at = event_time
    contact.suppression_reason = reason

    db.session.add(
        Activity(
            tenant_id=tenant_id,
            contact_id=contact.id,
            activity_name="Contact unsubscribed",
            activity_type="event",
            event_type="contact.unsubscribed",
            payload={
                "source": "resend_webhook",
                "reason": reason,
                "to_email": to_email,
                "campaign_id": str(campaign_id) if campaign_id else None,
            },
            occurred_at=event_time,
        )
    )


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

    Signature verification is **fail-closed**: requests without a valid
    svix signature (missing header, bad signature, or unconfigured secret)
    return 401 so Resend flags the endpoint rather than silently dropping
    events.

    All timestamp columns follow **earliest-observed** semantics: once
    set they are never overwritten by a later webhook delivery. Repeat
    deliveries from Resend's retry queue are therefore idempotent — they
    only bump ``open_count`` / ``click_count``.

    Beyond the 401 signature path, the endpoint always returns 200 to
    prevent Resend from retrying for business-logic reasons (unknown
    email_id, unknown event, etc.).
    """
    payload_bytes = request.get_data()

    # Mandatory signature verification (fail-closed). ``request.headers``
    # is Werkzeug's case-insensitive Headers object — pass it directly,
    # do NOT wrap with ``dict()``.
    if not _verify_svix_signature(payload_bytes, request.headers):
        return jsonify({"error": "Invalid signature"}), 401

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

            # BL-1105: hard bounces are permanent — suppress so we never
            # retry. Soft bounces are recoverable (e.g. inbox full) so we
            # leave the contact mailable.
            if (log.bounce_type or "").lower() == "hard":
                _suppress_contact_for_email(
                    log.tenant_id,
                    log.to_email,
                    reason="hard_bounce",
                    event_time=event_time,
                )

        elif event_type == "email.complained":
            if not log.complained_at:
                log.complained_at = event_time
            log.status = "complained"

            # BL-1105: spam complaint -> immediate suppression.
            _suppress_contact_for_email(
                log.tenant_id,
                log.to_email,
                reason="spam_complaint",
                event_time=event_time,
            )

        elif event_type == "email.unsubscribed":
            if not log.unsubscribed_at:
                log.unsubscribed_at = event_time
            log.status = "unsubscribed"

            # BL-1103 / BL-1105: flip the contact's suppression flag so
            # no future campaign sends them another email. Idempotent.
            _suppress_contact_for_email(
                log.tenant_id,
                log.to_email,
                reason="resend_webhook",
                event_time=event_time,
            )

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
