# ADR-010: Campaign Analytics Data Pipeline

**Date**: 2026-04-22 | **Status**: Accepted | **Context**: Sprint 24

## Context

Sprint 24 delivered Campaign Analytics v1 — the "Evaluate" step of the Try → Run → Evaluate → Improve vision (`docs/vision/index.html`). Founders need a single funnel + time-series view of how an outreach campaign is performing: sent → delivered → opened → clicked → converted (microsite event) → replied.

Two sources of truth exist: our own `email_send_log` table (fed by Resend webhooks — BL-315, BL-1028, BL-1029, BL-1034) captures email-lifecycle events, and a microsite hosted in a separate repo handles landing-page engagement. Earlier sprints attempted to mirror microsite events into the leadgen DB (BL-316 / commit `256d531`); that duplicated state and made analytics drift from the microsite's own PostHog instrumentation.

We also needed live updates (founders watch the funnel during send windows) without adding a WebSocket layer or hammering the DB with 5s polls.

## Decision

- **Email events stay in-DB** — `/api/campaigns/:id/analytics/timeseries` queries `email_send_log` (the Resend webhook store, BL-315).
- **Microsite events come from PostHog** — `/api/campaigns/:id/analytics/microsite` calls PostHog HogQL Query API (US region, `https://us.i.posthog.com`). We do not write microsite events to our DB.
- **Campaign attribution via URL params** — microsite links carry `?utm_campaign=<campaign_short_id>&utm_source=leadgen`; PostHog events auto-capture the URL; HogQL filters by `properties.$current_url` substring match (BL-1036a).
- **Live updates via SSE, not WebSocket or polling** — `/api/campaigns/:id/analytics/stream` emits a `snapshot` event on connect, then `update` events every 10s and `heartbeat` every 30s (BL-1039). One-way server-to-client, works over plain HTTPS through Caddy, no extra infra.
- **Recharts for time-series, hand-rolled Tailwind SVG for funnel** — Recharts pulls its weight for multi-series time-series; the funnel is ~12 stages of flat boxes and is cheaper to build directly.
- **Tenant isolation: 404, never 403** — unknown campaign or cross-tenant campaign returns 404. We do not leak existence of another tenant's campaigns via authz error codes.
- **Graceful degradation on PostHog failure** — PostHog 5xx, timeout, or invalid JSON returns 200 with `microsite_metrics: {visits: 0, cta_clicks: 0, conversion_rate: 0, posthog_available: false}` so the UI can render a partial funnel with a "Microsite data unavailable" notice rather than crashing the whole tab.

## Consequences

**Positive**
- Single source of truth per domain: email events in our DB, engagement events in PostHog. No mirror table to keep in sync.
- SSE streams cost one HTTP connection + one poll cycle per open tab — cheap compared to WebSocket or aggressive client polling.
- Funnel tab never fails atomically: if PostHog dies, email metrics still render.

**Negative**
- Microsite analytics are only as fresh as PostHog's ingestion lag (seconds, usually, but not guaranteed).
- HogQL queries count against PostHog's free-tier quota; at scale we may need to cache responses (deferred).
- `_compute_campaign_analytics` helper is now shared between the legacy `/analytics` endpoint and the new split endpoints — the legacy endpoint was refactored (not removed) to keep existing dashboards working during migration.

## References

- Spec: `docs/specs/campaign-analytics.md`
- PRs: #148 (deploy config), #149 (BL-1028), #150 (BL-1034), #151 (BL-1046), #152 (BL-1026), #153 (BL-1035), #154 (BL-1029), #155 (BL-1036a), #156 (BL-1039), #157 (BL-1038), #158 (BL-1037)
- Related ADRs: ADR-006 (campaign data model), ADR-007 (message version tracking), ADR-009 (external API patterns)
