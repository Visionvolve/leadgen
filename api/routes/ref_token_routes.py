"""Ref-token routes — per-contact unique catalog tracking links (BL-1104).

Two surface areas:

1. Authenticated dashboard endpoints (JWT + tenant scope) — issue tokens
   for a contact and list tokens already issued.

2. Public endpoints (no auth) — consumed by the ua-microsite at
   `?ref=<token>` time. The microsite hits ``GET /api/ref-tokens/<token>
   /preferences`` to find out what variant to render, then fires
   ``POST /api/ref-tokens/<token>/visit`` to record the visit.

Tokens are 32-char base32 of 16 random bytes (Crockford-style uppercase,
no padding). Idempotent issuance: if a non-expired token already exists
for (tenant, contact, variant), the existing token is returned instead of
creating a new one. This satisfies acceptance criterion "re-copying
returns the same URL".

Visit ingestion writes an Activity row of ``event_type='catalog_ref_visited'``
so the ref-token visits flow through the same downstream analytics surfaces
as other engagement events (email opens, microsite redemptions).
"""

from __future__ import annotations

import base64
import logging
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, jsonify, request

from ..auth import require_role, resolve_tenant
from ..models import Activity, Contact, RefToken, db
from ..utils.safe_lookup import (
    is_valid_ref_token,
    is_valid_uuid,
    safe_first,
    safe_get,
)

logger = logging.getLogger(__name__)

ref_token_bp = Blueprint("ref_tokens", __name__)

VALID_VARIANTS = frozenset({"with_prices", "without_prices"})


# --- helpers --------------------------------------------------------------


def _generate_token() -> str:
    """Generate a 32-char URL-safe token (base32, no padding).

    16 random bytes → 26 base32 characters; we pad with random hex to land
    on a stable 32-char width that matches the migration's CHAR(32).
    """
    raw = secrets.token_bytes(20)  # 20 bytes → 32 chars base32 no padding
    encoded = base64.b32encode(raw).decode("ascii").rstrip("=")
    # Always exactly 32 ASCII characters with 20 random bytes.
    return encoded[:32]


def _catalog_url(token: str) -> str:
    """Compose the public catalog URL that embeds the ref token."""
    base = (current_app.config.get("UA_MICROSITE_URL") or "").rstrip("/")
    if not base:
        # Operator deployments without UA_MICROSITE_URL set still get a
        # functional relative URL; surface that to the caller untouched.
        return f"/cs?ref={token}"
    return f"{base}/cs?ref={token}"


def _find_existing_active_token(tenant_id, contact_id, variant) -> RefToken | None:
    """Return an unexpired RefToken matching the (tenant, contact, variant) triple."""
    now = datetime.now(timezone.utc)
    candidates = (
        RefToken.query.filter_by(
            tenant_id=str(tenant_id),
            contact_id=str(contact_id),
            variant=variant,
        )
        .order_by(RefToken.created_at.desc())
        .all()
    )
    for tok in candidates:
        if not tok.is_expired(now):
            return tok
    return None


# --- authenticated endpoints ---------------------------------------------


@ref_token_bp.route("/api/contacts/<contact_id>/ref-token", methods=["POST"])
@require_role("editor")
def create_ref_token(contact_id):
    """Issue (or reuse) a ref token for a contact.

    Body: ``{variant, expires_in_days?, notes?}``.

    Idempotent: if a non-expired token already exists for (contact,
    variant), the existing token is returned with ``reused: true``. This
    matches the acceptance criterion that re-copying returns the same URL.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Reject malformed contact_id before the DB query so PostgreSQL never
    # raises InvalidTextRepresentation. See api/utils/safe_lookup.py.
    if not is_valid_uuid(contact_id):
        return jsonify({"error": "invalid_contact_id"}), 400

    body = request.get_json(silent=True) or {}
    variant = (body.get("variant") or "with_prices").strip()
    if variant not in VALID_VARIANTS:
        return jsonify(
            {"error": f"variant must be one of {sorted(VALID_VARIANTS)}"}
        ), 400

    # Validate that the contact belongs to the resolved tenant.
    contact = safe_first(
        Contact.query.filter_by(id=contact_id, tenant_id=str(tenant_id))
    )
    if not contact:
        return jsonify({"error": "Contact not found"}), 404

    # Idempotent reuse.
    existing = _find_existing_active_token(tenant_id, contact_id, variant)
    if existing:
        return jsonify(
            {
                "token": existing.token,
                "url": _catalog_url(existing.token),
                "variant": existing.variant,
                "expires_at": (
                    existing.expires_at.isoformat() if existing.expires_at else None
                ),
                "reused": True,
            }
        )

    # Compute optional expiry.
    expires_at = None
    expires_in_days = body.get("expires_in_days")
    if expires_in_days is not None:
        try:
            days = int(expires_in_days)
            if days <= 0:
                return jsonify({"error": "expires_in_days must be > 0"}), 400
            expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        except (TypeError, ValueError):
            return jsonify({"error": "expires_in_days must be an integer"}), 400

    notes = body.get("notes")
    if notes is not None:
        notes = str(notes).strip() or None

    # Generate a fresh token; retry on the astronomically rare collision.
    user = getattr(g, "current_user", None)
    created_by = str(user.id) if user is not None else None

    for _ in range(5):
        token_str = _generate_token()
        if not db.session.get(RefToken, token_str):
            break
    else:  # pragma: no cover — defensive
        return jsonify({"error": "Could not allocate unique token"}), 500

    tok = RefToken(
        token=token_str,
        tenant_id=str(tenant_id),
        contact_id=str(contact_id),
        variant=variant,
        created_by=created_by,
        expires_at=expires_at,
        notes=notes,
        visit_count=0,
    )
    db.session.add(tok)
    db.session.commit()

    return jsonify(
        {
            "token": tok.token,
            "url": _catalog_url(tok.token),
            "variant": tok.variant,
            "expires_at": tok.expires_at.isoformat() if tok.expires_at else None,
            "reused": False,
        }
    ), 201


@ref_token_bp.route("/api/contacts/<contact_id>/ref-tokens", methods=["GET"])
@require_role("viewer")
def list_ref_tokens(contact_id):
    """List all ref tokens issued for a contact (most recent first)."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    if not is_valid_uuid(contact_id):
        return jsonify({"error": "invalid_contact_id"}), 400

    contact = safe_first(
        Contact.query.filter_by(id=contact_id, tenant_id=str(tenant_id))
    )
    if not contact:
        return jsonify({"error": "Contact not found"}), 404

    rows = (
        RefToken.query.filter_by(tenant_id=str(tenant_id), contact_id=str(contact_id))
        .order_by(RefToken.created_at.desc())
        .all()
    )
    out = []
    for tok in rows:
        d = tok.to_dict()
        d["url"] = _catalog_url(tok.token)
        d["is_expired"] = tok.is_expired()
        out.append(d)
    return jsonify({"tokens": out})


# --- public endpoints (no auth) ------------------------------------------


@ref_token_bp.route("/api/ref-tokens/<token>/preferences", methods=["GET"])
def get_token_preferences(token):
    """Look up token → variant + contact first name.

    Consumed by the ua-microsite ``/api/ref-grant`` route. Returns 404 if
    the token is unknown or expired so the microsite falls through to the
    no-cookie path silently. Never reveals tenant slugs or sensitive
    contact data — just the strictly necessary fields to render the page.

    Returns 400 ``invalid_token`` if the token shape is obviously wrong;
    the public surface MUST NOT 500 on malformed input (PR #175 fixed the
    same anti-pattern in the unsubscribe endpoint).
    """
    # Reject obviously malformed tokens up-front so we never touch the DB
    # with garbage that could trip InvalidTextRepresentation on PG.
    if not is_valid_ref_token(token):
        return jsonify({"error": "invalid_token"}), 400

    tok = safe_get(RefToken, token)
    if not tok or tok.is_expired():
        return jsonify({"error": "Not found"}), 404

    contact = safe_get(Contact, tok.contact_id)
    first_name = contact.first_name if contact else None

    return jsonify(
        {
            "variant": tok.variant,
            "contact_first_name": first_name,
            "contact_id": tok.contact_id,
            "tenant_id": tok.tenant_id,
            "expires_at": tok.expires_at.isoformat() if tok.expires_at else None,
        }
    )


@ref_token_bp.route("/api/ref-tokens/<token>/visit", methods=["POST"])
def record_token_visit(token):
    """Record a visit for a ref token (public, no auth).

    Bumps ``visit_count`` and timestamps, then writes an Activity row of
    ``event_type='catalog_ref_visited'`` so the visit flows through the
    same downstream analytics as other engagement events.

    Returns 204 on success, 404 on unknown/expired token, 400 on a
    malformed token shape. The endpoint is intentionally non-throwing
    for any other failure mode — the microsite visit must never break
    because the visit emit failed.
    """
    # Reject malformed tokens before DB touch (avoids 500 on PG cast errors).
    if not is_valid_ref_token(token):
        return jsonify({"error": "invalid_token"}), 400

    tok = safe_get(RefToken, token)
    if not tok or tok.is_expired():
        return jsonify({"error": "Not found"}), 404

    now = datetime.now(timezone.utc)
    tok.visit_count = (tok.visit_count or 0) + 1
    if tok.first_visited_at is None:
        tok.first_visited_at = now
    tok.last_visited_at = now

    # Commit the visit counter update FIRST so it lands even if the
    # downstream Activity insert fails. The visit_count + timestamps on the
    # RefToken row are the source of truth for visit tracking; the Activity
    # row is a denormalized event-stream mirror for analytics.
    db.session.commit()

    # Best-effort Activity row in a separate transaction. Visits are
    # append-only — they MUST NOT carry external_id because the
    # idx_activities_tenant_external_id partial unique index (used to
    # dedupe inbound webhook events like Resend/Gmail) would collide on
    # the second visit with the same token and 500 the public endpoint.
    # The token reference is preserved in the payload JSON for analytics.
    try:
        activity = Activity(
            tenant_id=tok.tenant_id,
            contact_id=tok.contact_id,
            event_type="catalog_ref_visited",
            activity_type="event",
            activity_name="Catalog tracking link visited",
            activity_detail=f"variant={tok.variant}, visit_count={tok.visit_count}",
            source="ua_microsite_ref",
            # external_id intentionally NOT set — visits are append-only
            # and the unique index would collide on repeat visits.
            timestamp=now,
            occurred_at=now,
            payload={
                "token": tok.token,
                "variant": tok.variant,
                "visit_count": tok.visit_count,
            },
        )
        db.session.add(activity)
        db.session.commit()
    except Exception:  # pragma: no cover
        logger.exception("Failed to write Activity for ref-token visit")
        db.session.rollback()

    return ("", 204)
