"""Public unsubscribe endpoints (BL-1103, BL-1105).

Provides ``GET /api/unsubscribe`` (confirmation page) and
``POST /api/unsubscribe`` (one-click form submission, RFC 8058 compliant)
that any recipient can hit from their email client without being signed
in to the dashboard.

Security model:
- No auth required (the recipient is anonymous to the system).
- Replaced by a **per-contact HMAC token** baked into every outbound
  email's unsubscribe link. The token is
  ``base32(HMAC-SHA256("{contact_id}:{tenant_id}", key=UNSUBSCRIBE_SECRET))``
  and is verified with ``hmac.compare_digest`` to avoid timing attacks.
- Tenant isolation: the token cannot be reused across tenants because
  the tenant_id is part of the signed payload.

Side effects on success (``POST``):
1. Contact is flagged ``is_suppressed=TRUE`` (idempotent).
2. An ``Activity`` row is written with
   ``event_type='contact.unsubscribed'`` for the audit trail.
3. A single confirmation email is dispatched via
   ``send_service.send_unsubscribe_confirmation`` — but only on the
   *first* suppression. Replays of the same POST do NOT re-send.

The handler always returns 200 with a small HTML/JSON body (per
``Accept`` header). 403 is reserved for bad tokens. 404 is reserved for
contacts the token references that have been deleted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, render_template_string, request

from ..models import Activity, Contact, Tenant, db

logger = logging.getLogger(__name__)

unsubscribe_bp = Blueprint("unsubscribe", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# HMAC token helpers
# ---------------------------------------------------------------------------


def _get_unsubscribe_secret() -> bytes:
    """Return the bytes used to sign unsubscribe tokens.

    Prefers ``UNSUBSCRIBE_SECRET`` (dedicated, rotatable) and falls back
    to ``JWT_SECRET_KEY`` so dev/staging boots without extra config.
    """
    secret = (
        current_app.config.get("UNSUBSCRIBE_SECRET")
        or current_app.config.get("JWT_SECRET_KEY")
        or "change-me-in-production"
    )
    if isinstance(secret, str):
        return secret.encode("utf-8")
    return secret


def _b32(raw: bytes) -> str:
    """URL-safe short base32 (no padding) — keeps unsubscribe URLs short."""
    return base64.b32encode(raw).rstrip(b"=").decode("ascii").lower()


def generate_unsubscribe_token(contact: Contact) -> str:
    """Sign the (contact_id, tenant_id) pair into a short URL-safe token.

    Truncated to 16 bytes of HMAC output (128 bits) — plenty of entropy
    for a non-stored one-way action token, while keeping the resulting
    base32 string under 32 chars so the unsubscribe URL fits within
    typical Outlook/Apple Mail render budgets.
    """
    payload = f"{contact.id}:{contact.tenant_id}".encode("utf-8")
    mac = hmac.new(_get_unsubscribe_secret(), payload, hashlib.sha256).digest()
    return _b32(mac[:16])


def _verify_unsubscribe_token(contact_id: str, tenant_id: str, token: str) -> bool:
    """Constant-time verify a token against (contact_id, tenant_id).

    Returns False on any malformed input — never raises.
    """
    if not contact_id or not tenant_id or not token:
        return False
    payload = f"{contact_id}:{tenant_id}".encode("utf-8")
    mac = hmac.new(_get_unsubscribe_secret(), payload, hashlib.sha256).digest()
    expected = _b32(mac[:16])
    try:
        return hmac.compare_digest(expected, token.lower())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


_CONFIRM_PAGE_TMPL = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Unsubscribe</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           background:#fafafa; color:#222; max-width:520px; margin:48px auto; padding:24px; }
    h1 { font-size:20px; margin:0 0 16px; }
    p { line-height:1.55; }
    .card { background:#fff; padding:32px 28px; border-radius:12px;
            box-shadow:0 1px 4px rgba(0,0,0,0.06); }
    form { margin-top:24px; }
    button { background:#222; color:#fff; border:0; padding:10px 20px;
             font-size:14px; border-radius:6px; cursor:pointer; }
    button:hover { background:#000; }
    .muted { color:#777; font-size:13px; margin-top:24px; }
  </style>
</head>
<body>
  <div class="card">
    {% if suppressed %}
      <h1>You've been unsubscribed</h1>
      <p>{{ tenant_name }} will no longer send you marketing emails.</p>
      <p>If this was a mistake, reply to any previous email and we'll restore your subscription.</p>
    {% else %}
      <h1>Unsubscribe from {{ tenant_name }}</h1>
      <p>Click the button below to stop receiving marketing emails from {{ tenant_name }}.</p>
      <form method="POST" action="{{ form_action }}">
        <input type="hidden" name="contact_id" value="{{ contact_id }}">
        <input type="hidden" name="token" value="{{ token }}">
        <button type="submit">Confirm unsubscribe</button>
      </form>
    {% endif %}
    <p class="muted">Your email address is only used to identify your subscription.</p>
  </div>
</body>
</html>"""


_ERROR_PAGE_TMPL = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Unsubscribe link invalid</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           background:#fafafa; color:#222; max-width:520px; margin:48px auto; padding:24px; }
    .card { background:#fff; padding:32px 28px; border-radius:12px;
            box-shadow:0 1px 4px rgba(0,0,0,0.06); }
    h1 { font-size:18px; margin:0 0 12px; color:#b00020; }
  </style>
</head>
<body>
  <div class="card">
    <h1>This unsubscribe link is invalid</h1>
    <p>The link you used may be expired or tampered with. If you want to stop receiving emails,
       reply to any previous email with the word "unsubscribe" and we'll handle it manually.</p>
  </div>
</body>
</html>"""


def _wants_json() -> bool:
    """Return True if the client prefers a JSON response."""
    accept = (request.headers.get("Accept") or "").lower()
    if "application/json" in accept:
        return True
    if request.is_json:
        return True
    return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@unsubscribe_bp.route("/unsubscribe", methods=["GET"])
def unsubscribe_page():
    """Render the confirmation page (GET).

    Validates the token but does NOT suppress the contact yet — that
    happens on POST so a preview-fetch by a corporate link scanner (e.g.
    Microsoft Defender SafeLinks) doesn't accidentally suppress users.
    """
    contact_id = (request.args.get("contact_id") or "").strip()
    token = (request.args.get("token") or "").strip()

    contact = db.session.get(Contact, contact_id) if contact_id else None
    if not contact:
        return render_template_string(_ERROR_PAGE_TMPL), 404

    if not _verify_unsubscribe_token(contact.id, contact.tenant_id, token):
        return render_template_string(_ERROR_PAGE_TMPL), 403

    tenant = db.session.get(Tenant, contact.tenant_id)
    tenant_name = (tenant.name if tenant else "our team") or "our team"

    return render_template_string(
        _CONFIRM_PAGE_TMPL,
        suppressed=bool(contact.is_suppressed),
        tenant_name=tenant_name,
        contact_id=contact.id,
        token=token,
        form_action=request.path,
    )


@unsubscribe_bp.route("/unsubscribe", methods=["POST"])
def unsubscribe_submit():
    """Apply the suppression (POST).

    Idempotent: repeat POSTs do not duplicate the Activity row or the
    confirmation email. The suppression is committed FIRST, then the
    confirmation email is dispatched — so even if Resend errors, the
    contact is still suppressed and won't be mailed again.
    """
    # Accept both form-encoded and JSON
    if request.is_json:
        body = request.get_json(silent=True) or {}
        contact_id = (body.get("contact_id") or "").strip()
        token = (body.get("token") or "").strip()
    else:
        contact_id = (request.form.get("contact_id") or "").strip()
        token = (request.form.get("token") or "").strip()

    contact = db.session.get(Contact, contact_id) if contact_id else None
    if not contact:
        if _wants_json():
            return jsonify({"error": "not_found"}), 404
        return render_template_string(_ERROR_PAGE_TMPL), 404

    if not _verify_unsubscribe_token(contact.id, contact.tenant_id, token):
        logger.warning("Unsubscribe POST: invalid token for contact_id=%s", contact.id)
        if _wants_json():
            return jsonify({"error": "invalid_token"}), 403
        return render_template_string(_ERROR_PAGE_TMPL), 403

    tenant = db.session.get(Tenant, contact.tenant_id)
    tenant_name = (tenant.name if tenant else "our team") or "our team"

    first_time = not contact.is_suppressed

    if first_time:
        now = datetime.now(timezone.utc)
        contact.is_suppressed = True
        contact.suppressed_at = now
        contact.suppression_reason = "user_one_click"

        db.session.add(
            Activity(
                tenant_id=contact.tenant_id,
                contact_id=contact.id,
                activity_name="Contact unsubscribed",
                activity_type="event",
                event_type="contact.unsubscribed",
                payload={
                    "source": "unsubscribe_endpoint",
                    "to_email": contact.email_address,
                },
                occurred_at=now,
            )
        )
        db.session.commit()

        # Send the one-shot confirmation email AFTER commit so failure
        # there can't roll back the suppression itself.
        try:
            from ..services.send_service import send_unsubscribe_confirmation

            send_unsubscribe_confirmation(contact, tenant)
        except Exception:
            logger.exception(
                "Failed to send unsubscribe confirmation for contact_id=%s",
                contact.id,
            )

    if _wants_json():
        return jsonify(
            {
                "status": "unsubscribed",
                "contact_id": contact.id,
                "first_time": first_time,
            }
        ), 200

    return render_template_string(
        _CONFIRM_PAGE_TMPL,
        suppressed=True,
        tenant_name=tenant_name,
        contact_id=contact.id,
        token=token,
        form_action=request.path,
    )
