"""Campaign Reach Reporting endpoints (BL-1114, milestone v25 phase 11).

This module exposes the **reach** lens the LCC client asked for:

- ``GET /api/campaigns/<id>/reach``
    Per-campaign rollup: totals (targeted / sent / delivered / opened /
    clicked / bounced / complained / unsubscribed), engagement rates,
    per-template-language breakdown, and a per-UTC-day timeline of
    sent / opened / clicked counts.

- ``GET /api/campaigns/reach/summary``
    Tenant-wide rollup: returns ``{campaign_id, name, totals, rates}``
    for every campaign in the tenant. Powers the "Campaigns overview"
    page.

Design notes
------------

The data already lives in ``email_send_log`` — Phase 9 added the
``template_language`` / ``template_language_fallback`` columns, Phase 2
added ``unsubscribed_at``, and the original Sprint-24 work
(BL-1028, BL-1029, BL-1026) added the engagement timestamps,
``superseded_at``, and ``kind``. We therefore aggregate directly from
this table:

- Filter ``kind != 'preview'`` so previews never inflate reach numbers.
- Filter ``superseded_at IS NULL`` so a retry that bounced and was
  later re-sent only counts once per event type.
- Scope by tenant (``email_send_log.tenant_id``) — tenant isolation
  must hold even if a campaign UUID leaks across tenants.

Timeline aggregation runs in Python rather than SQL ``date_trunc`` so
the same code path works under SQLite (used by the unit-test suite) and
PostgreSQL (production). At current scale this is fast enough; if the
log grows beyond ~100k rows per campaign we can swap in a dialect-aware
``date_trunc`` query.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify

from ..auth import require_role, resolve_tenant
from ..models import db
from ..utils.safe_lookup import is_valid_uuid

logger = logging.getLogger(__name__)

reach_bp = Blueprint("campaign_reach", __name__)


# ── Helpers ─────────────────────────────────────────────────────────


def _safe_rate(num: int | float | None, den: int | float | None) -> float:
    """Return ``num / den`` rounded to 4 dp, or 0.0 when ``den`` is 0/None.

    Centralised so callers never trip a ZeroDivisionError when a
    campaign hasn't been sent yet.
    """
    if not den or den <= 0:
        return 0.0
    return round(float(num or 0) / float(den), 4)


def _coerce_aware(ts):
    """Return a tz-aware UTC datetime (or None) regardless of input shape.

    Send-log timestamps come back as ``datetime`` under PostgreSQL and
    as ISO-format strings under SQLite (tests). Both branches normalise
    to tz-aware UTC so date-truncation behaves identically.
    """
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, str):
        # Accept the trailing 'Z' that some clients emit.
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _utc_date_key(ts) -> str | None:
    """Return ``YYYY-MM-DD`` (UTC) for a timestamp, or None."""
    dt = _coerce_aware(ts)
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).date().isoformat()


def _aggregate_send_log_rows(rows) -> dict[str, int]:
    """Sum event counts from raw send-log rows.

    Each row is a 7-tuple of timestamps (or NULLs):
    ``(sent_at, delivered_at, opened_at, clicked_at, bounced_at,
       complained_at, unsubscribed_at)``.
    """
    totals = {
        "sent": 0,
        "delivered": 0,
        "opened": 0,
        "clicked": 0,
        "bounced": 0,
        "complained": 0,
        "unsubscribed": 0,
    }
    keys = (
        "sent",
        "delivered",
        "opened",
        "clicked",
        "bounced",
        "complained",
        "unsubscribed",
    )
    for r in rows:
        for idx, key in enumerate(keys):
            if r[idx] is not None:
                totals[key] += 1
    return totals


def _totals_with_rates(targeted: int, totals: dict[str, int]) -> dict:
    """Combine targeted + event totals into a single ``{totals, rates}`` block.

    Rates use the conventional bases the LCC client expects:

    - send_rate         = sent / targeted
    - delivery_rate     = delivered / sent
    - open_rate         = opened / delivered
    - click_rate        = clicked / delivered
    - bounce_rate       = bounced / sent
    - complaint_rate    = complained / delivered
    - unsubscribe_rate  = unsubscribed / delivered

    Each base is the strongest non-zero denominator we can defend
    (e.g. open rate uses delivered because we can only open a message
    that actually arrived).
    """
    sent = totals["sent"]
    delivered = totals["delivered"]
    return {
        "totals": {"targeted": targeted, **totals},
        "rates": {
            "send_rate": _safe_rate(sent, targeted),
            "delivery_rate": _safe_rate(delivered, sent),
            "open_rate": _safe_rate(totals["opened"], delivered),
            "click_rate": _safe_rate(totals["clicked"], delivered),
            "bounce_rate": _safe_rate(totals["bounced"], sent),
            "complaint_rate": _safe_rate(totals["complained"], delivered),
            "unsubscribe_rate": _safe_rate(totals["unsubscribed"], delivered),
        },
    }


# ── Per-campaign reach ──────────────────────────────────────────────


@reach_bp.route("/api/campaigns/<campaign_id>/reach", methods=["GET"])
@require_role("viewer")
def campaign_reach(campaign_id):
    """Return reach totals + rates + per-language + timeline for a campaign.

    Tenant-scoped. Returns 404 if the campaign does not exist in the
    caller's tenant (so a cross-tenant probe cannot distinguish a
    missing campaign from a forbidden one).
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Reject malformed campaign_id before the DB query — PostgreSQL's UUID
    # column would otherwise raise InvalidTextRepresentation → 500.
    if not is_valid_uuid(campaign_id):
        return jsonify({"error": "invalid_campaign_id"}), 400

    # Verify campaign membership in tenant + capture ``total_contacts``
    # (used as the ``targeted`` denominator). We use total_contacts so
    # the number stays stable even after a campaign is sent.
    camp = db.session.execute(
        db.text(
            """
            SELECT id, total_contacts
            FROM campaigns
            WHERE id = :id AND tenant_id = :t
            LIMIT 1
            """
        ),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not camp:
        return jsonify({"error": "Campaign not found"}), 404

    # If total_contacts was never populated, fall back to the live
    # campaign_contacts row count so freshly created campaigns still
    # show a non-zero ``targeted``.
    targeted = camp[1] or 0
    if not targeted:
        fallback = db.session.execute(
            db.text(
                """
                SELECT COUNT(*) FROM campaign_contacts
                WHERE campaign_id = :cid AND tenant_id = :t
                """
            ),
            {"cid": campaign_id, "t": tenant_id},
        ).scalar()
        targeted = int(fallback or 0)

    # ── Pull send-log rows for this campaign ────────────────────────
    # We join through messages → campaign_contacts (same path as the
    # rest of campaign_routes.py). The 7 timestamp columns drive all
    # downstream aggregations; pulling them in one pass keeps this an
    # O(rows_for_campaign) operation, not O(rows_total).
    rows = db.session.execute(
        db.text(
            """
            SELECT
                esl.sent_at,
                esl.delivered_at,
                esl.opened_at,
                esl.clicked_at,
                esl.bounced_at,
                esl.complained_at,
                esl.unsubscribed_at,
                esl.template_language,
                esl.template_language_fallback
            FROM email_send_log esl
            JOIN messages m ON m.id = esl.message_id
            JOIN campaign_contacts cc ON cc.id = m.campaign_contact_id
            WHERE cc.campaign_id = :cid
              AND cc.tenant_id = :t
              AND esl.tenant_id = :t
              AND esl.kind != 'preview'
              AND esl.superseded_at IS NULL
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    # ── Totals + rates ──────────────────────────────────────────────
    totals = _aggregate_send_log_rows([r[:7] for r in rows])
    payload = _totals_with_rates(targeted, totals)

    # ── Per-language breakdown ──────────────────────────────────────
    # We group by the (template_language, template_language_fallback)
    # pair so operators can see how many CS-fallback sends went out vs
    # explicit-CS sends. Rows with NULL template_language are skipped
    # (non-templated sends — they have no language to attribute to).
    lang_buckets: dict[tuple[str, bool], dict[str, int]] = {}
    for r in rows:
        lang = r[7]
        if lang is None:
            continue
        fallback = bool(r[8]) if r[8] is not None else False
        key = (lang, fallback)
        bucket = lang_buckets.setdefault(
            key,
            {
                "sent": 0,
                "delivered": 0,
                "opened": 0,
                "clicked": 0,
                "bounced": 0,
                "complained": 0,
                "unsubscribed": 0,
            },
        )
        for idx, name in enumerate(
            (
                "sent",
                "delivered",
                "opened",
                "clicked",
                "bounced",
                "complained",
                "unsubscribed",
            )
        ):
            if r[idx] is not None:
                bucket[name] += 1
    by_language = [
        {"language": lang, "fallback": fallback, **counts}
        for (lang, fallback), counts in sorted(
            lang_buckets.items(), key=lambda kv: (kv[0][0], kv[0][1])
        )
    ]
    payload["by_language"] = by_language

    # ── Timeline (per UTC day) ──────────────────────────────────────
    # Use ``sent_at`` as the bucket key — the timeline answers "when
    # did this campaign go out and engage" rather than "when did each
    # event land". Opens/clicks land later than the send, but for the
    # operator-facing chart they are most useful charted against the
    # original send day.
    day_buckets: dict[str, dict[str, int]] = {}
    for r in rows:
        day = _utc_date_key(r[0])
        if day is None:
            continue
        bucket = day_buckets.setdefault(day, {"sent": 0, "opened": 0, "clicked": 0})
        bucket["sent"] += 1
        if r[2] is not None:  # opened_at
            bucket["opened"] += 1
        if r[3] is not None:  # clicked_at
            bucket["clicked"] += 1
    timeline = [
        {"date": d, **counts}
        for d, counts in sorted(day_buckets.items(), key=lambda kv: kv[0])
    ]
    payload["timeline"] = timeline

    payload["campaign_id"] = str(campaign_id)
    return jsonify(payload)


# ── Tenant-wide reach summary ───────────────────────────────────────


@reach_bp.route("/api/campaigns/reach/summary", methods=["GET"])
@require_role("viewer")
def campaign_reach_summary():
    """Return a reach rollup for every campaign in the tenant.

    Drives the "Campaigns overview" page (sortable table of reach
    rates). One row per campaign with ``{campaign_id, name, totals,
    rates}``; campaigns with no sends still appear so operators can
    see the empty pipeline.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Pull every (campaign, send-log-row) pair in one query and bucket
    # in Python — far simpler than a per-campaign aggregation
    # subquery and still cheap at current scale (a tenant has O(10)
    # campaigns, each with O(1000) sends).
    rows = db.session.execute(
        db.text(
            """
            SELECT
                c.id           AS campaign_id,
                c.name         AS campaign_name,
                c.status       AS campaign_status,
                c.total_contacts AS targeted,
                esl.sent_at,
                esl.delivered_at,
                esl.opened_at,
                esl.clicked_at,
                esl.bounced_at,
                esl.complained_at,
                esl.unsubscribed_at
            FROM campaigns c
            LEFT JOIN campaign_contacts cc
                ON cc.campaign_id = c.id AND cc.tenant_id = c.tenant_id
            LEFT JOIN messages m
                ON m.campaign_contact_id = cc.id
            LEFT JOIN email_send_log esl
                ON esl.message_id = m.id
                AND esl.tenant_id = c.tenant_id
                AND esl.kind != 'preview'
                AND esl.superseded_at IS NULL
            WHERE c.tenant_id = :t
            """
        ),
        {"t": tenant_id},
    ).fetchall()

    # Group rows by campaign id; remember name + targeted from any row
    # (they're constant per campaign).
    campaigns: dict[str, dict] = {}
    for r in rows:
        cid = str(r[0])
        record = campaigns.setdefault(
            cid,
            {
                "name": r[1],
                "status": r[2],
                "targeted": r[3] or 0,
                "rows": [],
            },
        )
        # Only append rows that actually have a sent_at (LEFT JOIN may
        # emit a single NULL row for campaigns with zero sends).
        if r[4] is not None:
            record["rows"].append(r[4:])

    result = []
    for cid, info in campaigns.items():
        totals = _aggregate_send_log_rows(info["rows"])
        block = _totals_with_rates(info["targeted"], totals)
        result.append(
            {
                "campaign_id": cid,
                "name": info["name"],
                "status": info["status"],
                **block,
            }
        )

    # Sort: campaigns with sends first (by sent desc), then alpha.
    result.sort(key=lambda c: (-c["totals"]["sent"], (c["name"] or "").lower()))
    return jsonify({"campaigns": result})
