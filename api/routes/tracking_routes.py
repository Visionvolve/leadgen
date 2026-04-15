"""Tracking endpoints for external event ingestion (e.g. microsite partner events).

No JWT auth — protected by API key in ``X-API-Key`` header.
Always returns 200 to avoid breaking the calling service on transient errors.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from ..models import Activity, Contact, db

logger = logging.getLogger(__name__)

tracking_bp = Blueprint("tracking", __name__)

VALID_EVENTS = frozenset(
    {
        "invite_redeemed",
        "product_viewed",
        "page_viewed",
        "session_ended",
    }
)


def _verify_api_key() -> bool:
    """Check that the request carries a valid ``X-API-Key`` header."""
    expected = current_app.config.get("UA_INVITE_API_KEY") or ""
    if not expected:
        return False
    return request.headers.get("X-API-Key", "") == expected


def _resolve_contact(token: str, data: dict | None) -> Contact | None:
    """Resolve a contact from the event payload.

    Strategy:
    1. If *data* contains an ``email`` field, look up the contact by email.
    2. As a fallback, try to find a contact whose email matches the token
       (some microsites use email-as-token).

    Returns the first matching :class:`Contact` or ``None``.
    """
    email = (data or {}).get("email", "").strip().lower() if data else ""

    if email:
        contact = Contact.query.filter(
            db.func.lower(Contact.email_address) == email,
        ).first()
        if contact:
            return contact

    # Fallback: treat token itself as email
    if token and "@" in token:
        contact = Contact.query.filter(
            db.func.lower(Contact.email_address) == token.strip().lower(),
        ).first()
        if contact:
            return contact

    return None


@tracking_bp.route("/api/tracking/microsite-event", methods=["POST"])
def ingest_microsite_event():
    """Ingest a single event from the ua-microsite.

    Expected JSON body::

        {
            "token": "abc123",
            "event": "invite_redeemed",
            "data": { "email": "...", ... },
            "timestamp": "2026-04-13T12:00:00Z"   // optional
        }
    """
    # Always 200 — never break the caller
    try:
        if not _verify_api_key():
            logger.warning("Tracking: invalid or missing API key")
            return jsonify({"ok": False, "error": "unauthorized"}), 200

        body = request.get_json(silent=True) or {}

        token = (body.get("token") or "").strip()
        event_name = (body.get("event") or "").strip()
        data = body.get("data") or {}
        ts_raw = body.get("timestamp")

        if not event_name:
            return jsonify({"ok": False, "error": "missing event"}), 200

        if event_name not in VALID_EVENTS:
            return jsonify({"ok": False, "error": f"unknown event: {event_name}"}), 200

        # Parse optional timestamp
        occurred_at = None
        if ts_raw:
            try:
                occurred_at = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                occurred_at = None
        if occurred_at is None:
            occurred_at = datetime.now(timezone.utc)

        contact = _resolve_contact(token, data)

        activity = Activity(
            tenant_id=contact.tenant_id if contact else None,
            contact_id=contact.id if contact else None,
            activity_name=event_name,
            activity_type="event",
            activity_detail=str(data) if data else None,
            source="microsite",
            event_type=event_name,
            occurred_at=occurred_at,
            timestamp=occurred_at,
            payload=data,
        )

        # tenant_id is NOT NULL — if we couldn't resolve a contact, we still
        # want to persist the event for debugging.  Use a sentinel or skip.
        if activity.tenant_id is None:
            logger.info(
                "Tracking: could not resolve contact for token=%s event=%s — skipping persist",
                token,
                event_name,
            )
            return jsonify({"ok": True, "matched": False}), 200

        db.session.add(activity)
        db.session.commit()

        logger.info(
            "Tracking: persisted %s for contact=%s",
            event_name,
            contact.id if contact else "?",
        )
        return jsonify({"ok": True, "matched": True}), 200

    except Exception:
        db.session.rollback()
        logger.exception("Tracking: unexpected error ingesting microsite event")
        return jsonify({"ok": False, "error": "internal"}), 200
