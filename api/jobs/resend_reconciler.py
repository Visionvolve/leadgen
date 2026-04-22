"""Resend engagement timestamp reconciler (BL-1045).

Scheduled reconciler that closes the gap left by missed Resend webhook
deliveries. For every ``email_send_log`` row that still has a NULL
engagement timestamp (``delivered_at`` / ``opened_at`` / ``clicked_at`` /
``bounced_at`` / ``complained_at`` / ``unsubscribed_at``) and was created
inside the configured lookback window, we call Resend's
``GET /emails/{id}`` endpoint and backfill the column that matches the
API response's ``last_event`` field.

Why this exists
---------------
Resend webhook deliveries can fail (network blip, our endpoint down,
signature misconfigured). Engagement analytics are only as good as the
webhook stream, and a missing ``opened_at`` on a high-value prospect is
a real business miss. This job provides a second-chance path that
reconciles against Resend's authoritative state.

Earliest-observed invariant (BL-1028)
-------------------------------------
The reconciler is **strictly additive**: it only writes columns that are
currently NULL. Any column already set by the webhook — even if the
reconciler now sees a different value — is preserved. That keeps the
"first observed timestamp wins" semantics the webhook handler enforces.

Multi-tenant isolation
----------------------
Resend API keys are per-tenant (stored in ``tenant.settings.resend_api_key``).
``GET /emails/{id}`` only returns messages sent with the caller's API
key, so the source itself is tenant-isolated. We additionally scope every
query by ``tenant_id`` so a misconfigured key cannot spill data across
tenants. The :func:`reconcile_all_tenants` driver iterates each active
tenant that has a key configured and processes its rows in isolation.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import or_

from ..models import EmailSendLog, Tenant, db

logger = logging.getLogger(__name__)

RESEND_API_BASE = "https://api.resend.com"
DEFAULT_WINDOW_DAYS = 30
DEFAULT_BATCH_LIMIT = 100
_HTTP_TIMEOUT_SECONDS = 10

# Map from Resend's ``last_event`` string → EmailSendLog column name.
# Only columns that actually exist on the model are eligible. Values
# outside this mapping (e.g. ``failed``) are skipped — we have no
# corresponding timestamp column.
_LAST_EVENT_TO_COLUMN: dict[str, str] = {
    "delivered": "delivered_at",
    "opened": "opened_at",
    "clicked": "clicked_at",
    "bounced": "bounced_at",
    "complained": "complained_at",
    "unsubscribed": "unsubscribed_at",
}

# Engagement columns we care about when deciding "does this row need
# reconciling?". A row is a candidate when ANY of these is NULL.
_ENGAGEMENT_COLUMNS = (
    EmailSendLog.delivered_at,
    EmailSendLog.opened_at,
    EmailSendLog.clicked_at,
    EmailSendLog.bounced_at,
    EmailSendLog.complained_at,
    EmailSendLog.unsubscribed_at,
)


def _parse_event_ts(raw: str | None) -> datetime | None:
    """Parse Resend's ``last_event_at`` ISO-8601 string into a datetime.

    Returns ``None`` when ``raw`` is missing or unparseable — callers fall
    back to ``EmailSendLog.created_at``.
    """
    if not raw:
        return None
    try:
        normalised = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(normalised)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, AttributeError):
        logger.warning("Resend reconcile: unparseable last_event_at %r", raw)
        return None


def reconcile_send_logs(
    tenant_id: str,
    api_key: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
) -> dict:
    """Backfill engagement timestamps for a single tenant.

    Parameters
    ----------
    tenant_id:
        UUID (string) of the tenant whose ``email_send_log`` rows to process.
    api_key:
        The tenant's Resend API key. Must match the key used to send the
        messages — Resend only returns records for the owning key.
    window_days:
        Lookback horizon. Rows older than this are excluded to bound the
        number of outbound API calls and avoid hammering Resend with
        long-dead messages.
    batch_limit:
        Maximum number of rows to process per invocation. Keeps the job
        bounded when a backlog of rows needs reconciliation — subsequent
        runs pick up the remainder.

    Returns
    -------
    dict
        ``{"rows_checked": int, "rows_updated": int, "errors": int}``.
        ``errors`` counts transient failures (5xx, connection errors) —
        404s are treated as "row is stale on Resend's side" and are NOT
        counted as errors.
    """
    since = datetime.now(timezone.utc) - timedelta(days=window_days)

    rows = (
        EmailSendLog.query.filter(
            EmailSendLog.tenant_id == tenant_id,
            EmailSendLog.resend_message_id.isnot(None),
            EmailSendLog.created_at >= since,
            or_(*(col.is_(None) for col in _ENGAGEMENT_COLUMNS)),
        )
        .limit(batch_limit)
        .all()
    )

    stats = {"rows_checked": 0, "rows_updated": 0, "errors": 0}

    for row in rows:
        stats["rows_checked"] += 1
        try:
            resp = requests.get(
                f"{RESEND_API_BASE}/emails/{row.resend_message_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.warning(
                "Resend reconcile: network error for %s: %s",
                row.resend_message_id,
                exc,
            )
            stats["errors"] += 1
            continue

        if resp.status_code == 404:
            # Message purged / unknown — nothing to reconcile, move on.
            continue

        if resp.status_code >= 400:
            logger.warning(
                "Resend reconcile: API error %s for %s",
                resp.status_code,
                row.resend_message_id,
            )
            stats["errors"] += 1
            continue

        try:
            data = resp.json() or {}
        except ValueError:
            logger.warning(
                "Resend reconcile: non-JSON response for %s",
                row.resend_message_id,
            )
            stats["errors"] += 1
            continue

        last_event = data.get("last_event")
        column = _LAST_EVENT_TO_COLUMN.get(last_event)
        if not column:
            # Either the field is missing or the value is outside our
            # mapping (e.g. ``failed``). No column to write — skip.
            continue

        # Earliest-observed: never overwrite an already-set timestamp.
        current_value = getattr(row, column, None)
        if current_value is not None:
            continue

        event_ts = _parse_event_ts(data.get("last_event_at")) or row.created_at
        if event_ts is None:
            # Pathological: neither Resend nor the row have a timestamp.
            # Use the current wall clock as last resort.
            event_ts = datetime.now(timezone.utc)

        setattr(row, column, event_ts)
        stats["rows_updated"] += 1

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Resend reconcile: commit failed for tenant %s", tenant_id)
        stats["errors"] += 1
        return stats

    logger.info(
        "Resend reconcile complete for tenant %s: %s (window=%sd, limit=%s)",
        tenant_id,
        stats,
        window_days,
        batch_limit,
    )
    return stats


def _load_resend_key(tenant: Tenant) -> str | None:
    """Pull ``resend_api_key`` out of ``tenant.settings`` (str-or-dict)."""
    settings = tenant.settings
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except (ValueError, TypeError):
            return None
    settings = settings or {}
    key = settings.get("resend_api_key") if isinstance(settings, dict) else None
    return key if isinstance(key, str) and key else None


def reconcile_all_tenants(
    window_days: int = DEFAULT_WINDOW_DAYS,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
) -> dict:
    """Run the reconciler across every active tenant with a Resend key.

    Returns a summary dict with aggregated counts. Individual tenant
    failures are logged but do not abort the whole run.
    """
    tenants = Tenant.query.filter(Tenant.is_active.is_(True)).all()

    summary = {
        "tenants_processed": 0,
        "tenants_skipped": 0,
        "rows_checked": 0,
        "rows_updated": 0,
        "errors": 0,
    }

    for tenant in tenants:
        api_key = _load_resend_key(tenant)
        if not api_key:
            summary["tenants_skipped"] += 1
            continue

        try:
            stats = reconcile_send_logs(
                tenant_id=tenant.id,
                api_key=api_key,
                window_days=window_days,
                batch_limit=batch_limit,
            )
        except Exception:
            logger.exception(
                "Resend reconcile: tenant %s crashed, continuing", tenant.id
            )
            summary["errors"] += 1
            continue

        summary["tenants_processed"] += 1
        summary["rows_checked"] += stats["rows_checked"]
        summary["rows_updated"] += stats["rows_updated"]
        summary["errors"] += stats["errors"]

    logger.info("Resend reconcile (all tenants): %s", summary)
    return summary
