"""PostHog Query API integration (BL-1035).

Thin wrapper around PostHog's HogQL Query API. Used by the campaign analytics
route (BL-1038) to read microsite metrics — visits, unique visitors, CTA
clicks, form submits, avg time on page — per campaign.

Design notes
------------
- **Plain ``requests``** — no posthog-python SDK dependency. We only need the
  Query endpoint and the SDK is geared toward event capture.
- **Graceful degradation**: HTTP 4xx/5xx and timeouts raise
  :class:`PostHogUnavailableError`. Callers are expected to catch this and
  render a "temporarily unavailable" banner so the rest of the analytics
  dashboard keeps working (see spec NFR-4).
- **30-second in-memory cache** keyed by ``(campaign_id, since, until)``.
  This is the simplest thing that prevents rate-limit thrash during SSE
  refresh storms — an actual distributed cache is overkill at current scale.
- **Secret hygiene**: the ``POSTHOG_PERSONAL_API_KEY`` is backend-only. It
  must never appear in error messages, logs, ``repr(client)``, or response
  bodies. Tests enforce this.

Spec reference
--------------
- ``docs/specs/campaign-analytics.md`` §5.2 (data sources split), §5.5 (env
  vars), §5.7 (microsite endpoint), NFR-4/NFR-5.
- Backlog item: BL-1035.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# Module-level cache. Keyed by (campaign_id, since_iso, until_iso).
# Stored value: (expires_monotonic, CampaignMicrositeMetrics).
_CACHE_TTL_SECONDS = 30.0
_cache: dict[tuple[str, str, str], tuple[float, "CampaignMicrositeMetrics"]] = {}
_cache_lock = threading.Lock()

# Default HTTP timeout (seconds). Kept tight because callers are latency-sensitive
# (SSE stream) and we'd rather degrade gracefully than block.
_DEFAULT_TIMEOUT = 10.0


def _clear_cache_for_tests() -> None:
    """Reset the module-level cache. Test-only helper."""
    with _cache_lock:
        _cache.clear()


class PostHogUnavailableError(RuntimeError):
    """Raised when PostHog's Query API returns an error or times out.

    Callers should catch this at the route boundary and degrade cleanly
    (e.g. return ``{"fallback": true, "error": "posthog_unavailable"}``).
    The message intentionally carries no secret material.
    """


@dataclass(frozen=True)
class CampaignMicrositeMetrics:
    """Aggregated microsite metrics for a single campaign over a time window.

    All counts are non-negative integers. ``avg_time_on_page_sec`` is ``None``
    when no pageview events in the window carried a ``time_on_page_ms``
    property (e.g. the microsite hasn't been instrumented yet — BL-1036).
    """

    campaign_id: str
    since: datetime
    until: datetime
    visits: int
    unique_visitors: int
    cta_clicks: int
    form_submits: int
    avg_time_on_page_sec: Optional[float]


# HogQL query used by ``get_campaign_microsite_metrics``. Kept at module scope
# so it's easy to diff against the PostHog project in a review.
_MICROSITE_METRICS_HOGQL = """
SELECT
  countIf(event = '$pageview') AS visits,
  count(DISTINCT person_id) FILTER (WHERE event = '$pageview') AS unique_visitors,
  countIf(event = 'cta_clicked') AS cta_clicks,
  countIf(event = 'form_submitted') AS form_submits,
  avg(toFloat(properties.time_on_page_ms)) FILTER (
    WHERE event = '$pageview' AND properties.time_on_page_ms IS NOT NULL
  ) / 1000 AS avg_time_on_page_sec
FROM events
WHERE properties.campaign_id = {campaign_id}
  AND timestamp >= {since}
  AND timestamp < {until}
""".strip()


class PostHogClient:
    """Minimal PostHog Query API client.

    Configuration is pulled from environment variables at init time so tests
    and route handlers get a consistent view of credentials. Pass explicit
    kwargs to override (used by tests).
    """

    def __init__(
        self,
        personal_api_key: Optional[str] = None,
        host: Optional[str] = None,
        project_id: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.personal_api_key = personal_api_key or os.environ.get(
            "POSTHOG_PERSONAL_API_KEY", ""
        )
        self.host = (
            host or os.environ.get("POSTHOG_HOST") or "https://us.i.posthog.com"
        ).rstrip("/")
        self.project_id = project_id or os.environ.get("POSTHOG_PROJECT_ID", "")
        self.timeout = timeout

        if not self.personal_api_key:
            raise RuntimeError(
                "POSTHOG_PERSONAL_API_KEY is not configured — cannot talk to "
                "PostHog Query API. Set it in .env.dev (local) or 1Password / "
                "STAGING_DOTENV (staging+prod)."
            )
        if not self.project_id:
            raise RuntimeError(
                "POSTHOG_PROJECT_ID is not configured — cannot talk to PostHog "
                "Query API. Set it in .env.dev / 1P / STAGING_DOTENV."
            )

    # ------------------------------------------------------------------
    # Python dunder hygiene — never leak the secret key.
    # ------------------------------------------------------------------
    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"PostHogClient(host={self.host!r}, project_id={self.project_id!r})"

    __str__ = __repr__

    # ------------------------------------------------------------------
    # Raw query
    # ------------------------------------------------------------------
    def query(
        self,
        hogql: str,
        variables: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Run a HogQL query and return parsed rows as a list of dicts.

        Each row is a dict keyed by the column names PostHog returns.

        Raises:
            PostHogUnavailableError: on HTTP 4xx/5xx or timeout. Callers are
                expected to handle this and degrade gracefully. The error
                message never includes the personal API key.
        """
        url = f"{self.host}/api/projects/{self.project_id}/query/"
        payload = {
            "query": {
                "kind": "HogQLQuery",
                "query": hogql,
                "values": variables or {},
            }
        }
        headers = {
            "Authorization": f"Bearer {self.personal_api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                url, headers=headers, json=payload, timeout=self.timeout
            )
        except requests.Timeout:
            # Do NOT include the exception in the message — ``requests`` may
            # echo parts of the request (including the Authorization header)
            # in its repr on some versions. Log generically so ops can see
            # the timeout without the secret.
            logger.warning("PostHog query timed out after %.1fs", self.timeout)
            raise PostHogUnavailableError(
                f"PostHog Query API timed out after {self.timeout:.0f}s"
            ) from None
        except requests.RequestException as exc:
            logger.warning("PostHog query network error: %s", type(exc).__name__)
            raise PostHogUnavailableError(
                f"PostHog Query API network error ({type(exc).__name__})"
            ) from None

        if resp.status_code >= 400:
            # Log the status and a truncated body for diagnostics — the body
            # is PostHog's error JSON, it never contains our personal API key.
            body_preview = (resp.text or "")[:500]
            logger.warning(
                "PostHog query returned HTTP %s: %s", resp.status_code, body_preview
            )
            raise PostHogUnavailableError(
                f"PostHog Query API returned HTTP {resp.status_code}"
            )

        data = resp.json()
        columns: list[str] = data.get("columns") or []
        results: list[list[Any]] = data.get("results") or []
        if not columns:
            # Unexpected shape — treat as unavailable rather than crashing
            # callers with a KeyError.
            logger.warning("PostHog query returned no columns in response")
            raise PostHogUnavailableError(
                "PostHog Query API returned malformed response"
            )
        return [dict(zip(columns, row)) for row in results]

    # ------------------------------------------------------------------
    # Canned queries
    # ------------------------------------------------------------------
    def get_campaign_microsite_metrics(
        self,
        campaign_id: str,
        since: datetime,
        until: datetime,
    ) -> CampaignMicrositeMetrics:
        """Return microsite engagement metrics for ``campaign_id`` in a time window.

        Result is cached for 30 seconds keyed by ``(campaign_id, since, until)``
        to absorb SSE refresh storms without hitting PostHog rate limits
        (spec NFR-5).

        Raises:
            PostHogUnavailableError: if PostHog returns an error. The cache is
                NOT populated on failure — the next call will retry. Callers
                should catch and degrade.
        """
        cache_key = (campaign_id, since.isoformat(), until.isoformat())
        now = time.monotonic()

        with _cache_lock:
            cached = _cache.get(cache_key)
            if cached is not None and cached[0] > now:
                return cached[1]

        rows = self.query(
            _MICROSITE_METRICS_HOGQL,
            variables={
                "campaign_id": campaign_id,
                "since": since.isoformat(),
                "until": until.isoformat(),
            },
        )

        if rows:
            row = rows[0]
            visits = int(row.get("visits") or 0)
            unique_visitors = int(row.get("unique_visitors") or 0)
            cta_clicks = int(row.get("cta_clicks") or 0)
            form_submits = int(row.get("form_submits") or 0)
            raw_avg = row.get("avg_time_on_page_sec")
            avg_time = float(raw_avg) if raw_avg is not None else None
        else:
            # No events in window — report zeros rather than erroring so the
            # UI just shows 0 for a campaign whose microsite hasn't been
            # visited yet (or before BL-1036 ships the instrumentation).
            visits = 0
            unique_visitors = 0
            cta_clicks = 0
            form_submits = 0
            avg_time = None

        metrics = CampaignMicrositeMetrics(
            campaign_id=campaign_id,
            since=since,
            until=until,
            visits=visits,
            unique_visitors=unique_visitors,
            cta_clicks=cta_clicks,
            form_submits=form_submits,
            avg_time_on_page_sec=avg_time,
        )

        with _cache_lock:
            _cache[cache_key] = (now + _CACHE_TTL_SECONDS, metrics)

        return metrics
