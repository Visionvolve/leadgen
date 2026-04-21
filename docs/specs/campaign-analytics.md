# Campaign Analytics

_Spec version 1.0 · Author: sdlc:spec synthesis · Sponsor: founder · Target: Echo pillar + OutreachTab · Phase 1 of staged rollout · Created: 2026-04-21_

> **Status**: Spec'd — ready for sprint planning.
> **Phase**: 1 of 3 (see "Out of Scope" for Phase 2/3 deferrals).
> **Related drafts**: `docs/specs/drafts/campaign-analytics-pm.md`, `campaign-analytics-em.md`, `campaign-analytics-pd.md`.

---

## 1. Purpose

The founder today cannot answer "did my campaign work?" without opening three tabs — Resend dashboard, SQL, and the microsite's PostHog project. That is the exact friction this spec closes. We ship the first user-visible surface of the **Closed-Loop GTM Engine** (Try → Run → **Evaluate** → Improve) from `docs/vision/index.html`: a per-campaign analytics view that joins Resend email telemetry (shipped in BL-315, commit `aafd96c`) with microsite engagement (now sourced from PostHog) into a single funnel, time-series, hero KPI, and per-contact drill-down.

Strategy alignment: **direct hit on Theme 3 (Closed-Loop Analytics)** in `docs/PRODUCT_STRATEGY.md`. Quarter Q2-Q3 2026 is literally "Closed-Loop Intelligence — campaign performance coaching that learns from reply rates and engagement signals". That coaching layer has no substrate until this surface exists.

Design principle from the vision: **every interaction gathers a decision or delivers a result**. The analytics surface is useless if it's a wall of numbers. Every chart, every tile, every drill must point at a next action — pause a bad step, promote a winning variant, clone a campaign, re-target drop-offs.

---

## 2. Requirements

### Functional

| ID | Requirement |
|---|---|
| FR-1 | **Per-campaign funnel visualization** with 6 stages: Sent → Delivered → Opened → Clicked → Microsite Visited → CTA Action. Each stage shows absolute count and conversion % relative to the prior stage. |
| FR-2 | **Time-series chart** showing sends, opens, and clicks stacked per bucket. Default range 7d. Range selector: 24h / 7d / 30d / All. Bucket auto-derived (24h→hour, 7d/30d→day, All→week). |
| FR-3 | **Hero KPI card: Click-through rate** (clicks ÷ delivered) as the loudest number on the page — locked-in decision, 2026-04-21. Secondary tiles: Sent, Delivery %, Open rate, Reply rate (placeholder per FR-3a until BL-1044 ships), Microsite visits, CTA actions. |
| FR-3a | **Reply rate tile** renders with `—` placeholder + "Connect Gmail to track replies" prompt for tenants without Gmail connected. Tile auto-populates with `reply_rate = replies ÷ delivered` once Gmail connection + inbound mail ingestion land (separate sprint, BL-1044). |
| FR-4 | **Per-contact drill-down table** reusing the existing `CampaignRecipient` model. Row click opens existing contact `DetailModal` via `useEntityStack`. Filter chips: All · Bounced · No open · Opened · Clicked · Replied. |
| FR-5 | **"View analytics" deep link** on campaign detail page header → `/echo?campaign=<id>&range=7d`. |
| FR-6 | **Live update via SSE**: metrics refresh as events arrive. Endpoint `GET /api/campaigns/:id/analytics/stream` (text/event-stream). React hook `useCampaignAnalyticsStream(campaignId)` reconnects on disconnect with exponential backoff. Resend webhook events emit immediately; PostHog metrics polled server-side every 15s and emitted on heartbeat. |
| FR-7 | **Microsite metrics** (visits, unique visitors, time-on-page, CTA clicks, form submits) sourced from **PostHog Query API** via new backend integration `api/integrations/posthog.py`. |
| FR-8 | **Email metrics** (sent, delivered, opened, clicked, bounced, unsubscribed) sourced from our **leadgen DB** (`email_send_log` populated by Resend webhook handler at `api/routes/webhook_routes.py`). |
| FR-9 | **Echo page** (at `/echo`) replaces the current `PlaceholderPage` component. Lists campaigns with inline KPI summary (mini sparkline + reply rate + sent count). Clicking a row drills into the single-campaign view scoped via `?campaign=<id>`. |
| FR-10 | **Both surfaces stay in sync**: the OutreachTab inline funnel + time-series + hero KPI, and the Echo page's per-campaign view, share the same API endpoints, same React components (`<FunnelChart>`, `<TimeSeriesChart>`, `<KpiTile>`), and same SSE stream. |
| FR-11 | **Campaign attribution**: every microsite link in every outbound email carries `?c=<campaign_id>&r=<recipient_id>`. The microsite forwards these to PostHog as event properties so backend queries can filter by `properties.campaign_id`. |

### Non-Functional

| ID | Requirement |
|---|---|
| NFR-1 | **Performance**: dashboard load ≤1.5s from click → first contentful paint on a 10k-event campaign. Measured as React mount → first chart render with real data. |
| NFR-2 | **SSE resilience**: client reconnects on disconnect using exponential backoff (1s, 2s, 4s, capped at 30s). Server heartbeats every 15s. |
| NFR-3 | **Multi-tenant isolation**: every new endpoint validates `tenant_id` membership on the campaign before serving analytics. Mismatch returns **404** (not 403) to avoid existence disclosure. |
| NFR-4 | **Graceful degradation**: PostHog API failures degrade cleanly. Email metrics still render from our DB; microsite section shows "PostHog temporarily unavailable" banner with retry timer. Dashboard never blanks out. |
| NFR-5 | **PostHog caching**: backend caches PostHog query responses for 30s, keyed by `(campaign_id, range_bucket)`. Prevents rate-limit hits on refresh storms. |
| NFR-6 | **Credits not USD**: every cost figure (cost-per-reply, cost-per-visit) renders as credits (USD × 1000). Raw USD reserved for super-admin dashboard only (MEMORY rule). |
| NFR-7 | **Desktop ≥1280px is primary**. Tablet ≥768px graceful (stacked layout). Mobile <768px defers to v2. |
| NFR-8 | **Accessibility WCAG AA**: chart colors validated against `--color-bg`; every chart ships a sibling `<details>` table for screen readers; keyboard navigation across filter bar → hero tiles → funnel stages → time-series crosshair → drill table; `prefers-reduced-motion` respected. |
| NFR-9 | **Copy discipline**: no judgmental language about prospects. Use "No response yet" / "Awaiting engagement" / "Drop-off at open". |

---

## 3. Acceptance Criteria

Each Given/When/Then maps to an FR and is verified via the sprint's manual test script + unit tests.

### AC-1 — Funnel shows correct counts (FR-1)
- **Given** a campaign with 1000 sent, 950 delivered, 400 opened, 80 clicked, 40 visited, 12 CTA
- **When** the founder opens the analytics surface (OutreachTab or Echo)
- **Then** the funnel renders all 6 stages with absolute counts and conversion % vs prior stage (delivery 95%, open 42.1%, click 20%, visit 50%, CTA 30%)

### AC-2 — Click-through rate is the hero (FR-3)
- **Given** any campaign with ≥1 delivered email
- **When** the founder opens the analytics surface
- **Then** click-through rate (clicks ÷ delivered) is the largest, most prominent KPI, with "N clicks of M delivered" as a subtitle. If 0 clicks, shows "0%" — not "—" — because the number is real.

### AC-2a — Reply rate tile shows Gmail-connect placeholder (FR-3a)
- **Given** a tenant that has not connected Gmail
- **When** the founder opens the analytics surface
- **Then** the Reply rate tile renders with value `—`, subtext "Connect Gmail to track replies", and a small `Connect →` link pointing to `/settings/gmail`
- **And** once Gmail is connected (BL-1044 ships) and replies are ingested, the same tile auto-populates with `replies ÷ delivered` without any further UI work

### AC-3 — Time-series shows campaign arc (FR-2)
- **Given** a 14-day-old campaign with sends on days 1, 3, 7
- **When** range=30d is selected
- **Then** chart shows day-bucketed sends, opens, and clicks stacked, with zero-padded days for no activity

### AC-4 — SSE updates live (FR-6, NFR-2)
- **Given** the founder has the analytics surface open
- **When** Resend fires an `email.opened` webhook for a recipient in this campaign
- **Then** within 2s the opened count increments, the funnel redraws, and the time-series adds a data point — **without page refresh**
- **And when** the SSE connection drops, the client reconnects automatically and resumes updates

### AC-5 — Microsite metrics from PostHog (FR-7, NFR-4)
- **Given** a campaign with 20 microsite visits logged in PostHog (via `campaign_id` property)
- **When** the Microsite Metrics block renders
- **Then** visits, unique visitors, median time-on-page, and CTA clicks match the PostHog Query API response within 30s cache window
- **And when** the PostHog API returns 5xx or times out, the block shows "PostHog temporarily unavailable" but the rest of the dashboard still renders

### AC-6 — Per-contact drill-down (FR-4)
- **Given** a campaign with 200 recipients
- **When** the founder clicks "Opened" in the funnel
- **Then** the drill table filters to recipients with `opened_at IS NOT NULL`, sorted by most recent event
- **When** the founder clicks a row
- **Then** the existing contact `DetailModal` opens on the History tab

### AC-7 — Deep link into Echo (FR-5)
- **Given** the founder is on the campaign detail page
- **When** they click "View analytics"
- **Then** the browser navigates to `/echo?campaign=<id>&range=7d` and the Echo page scopes to that campaign

### AC-8 — Echo replaces placeholder (FR-9)
- **Given** a tenant with 3 campaigns
- **When** the founder clicks the Echo pillar in the nav
- **Then** the previous `PlaceholderPage` is gone; the new EchoPage lists the 3 campaigns with mini-sparkline + reply rate + sent count

### AC-9 — Attribution chain (FR-11)
- **Given** an outbound email generated by the campaign
- **When** the microsite link is inspected
- **Then** it carries `?c=<campaign_id>&r=<recipient_id>` query params
- **And when** a partner visits and triggers a `cta_clicked` event
- **Then** PostHog captures the event with `campaign_id` and `recipient_id` as event properties

### AC-10 — Tenant isolation (NFR-3)
- **Given** tenant A has campaign X; tenant B has campaign Y
- **When** a tenant B user calls `GET /api/campaigns/<X.id>/analytics/*`
- **Then** the response is 404 (not 403, not 200 with empty data)

### AC-11 — Performance on 10k events (NFR-1)
- **Given** a campaign with 10k delivered + 4k opened + 800 clicked + 150 PostHog events
- **When** the analytics surface mounts
- **Then** first chart renders within 1.5s; SSE first heartbeat within 1s of mount

---

## 4. UX / Design

Refer to `docs/specs/drafts/campaign-analytics-pd.md` for full layout wireframes. Condensed decisions below.

### 4.1 Information hierarchy

1. **THE number**: Click-through rate (clicks ÷ delivered). Chosen over reply rate for v1 because CTR is an unambiguous engagement signal — not bot-inflated like opens (MPP) and not blocked by missing inbound-mail ingestion like replies. Locked-in decision, 2026-04-21.
2. **Supporting hero tiles** (6 total on desktop): Sent · Delivery % · Open rate · Reply rate (placeholder — see §4.5) · Microsite visits · CTA actions.
3. **Funnel + Time-series** side-by-side (2/3 + 1/3 on desktop).
4. **Per-contact drill** below the fold with filter chips.

### 4.2 Surfaces

| Surface | Route | Content |
|---|---|---|
| OutreachTab inline analytics | `/campaigns/:id` → Outreach tab | Funnel + time-series + hero KPI row inline, no drill table (drill already lives in existing RecipientsDrillDown below it) |
| Echo per-campaign view | `/echo?campaign=<id>&range=7d` | Same hero + funnel + time-series + microsite block + drill table |
| Echo home | `/echo` (no `?campaign` param) | Campaign list with mini-sparkline + reply rate per row; click → per-campaign view |

Echo replaces `frontend/src/components/layout/AppNav.tsx:78-86`'s current `PlaceholderPage`. **Do NOT rename Echo → Monitor** (sponsor decision: keep Echo branding, change only the page body).

### 4.3 Component tree

```
EchoPage (reads useSearchParams)
├── EchoHeader (range selector, refresh)
├── if no ?campaign= → EchoHome
│   └── CampaignList (rows with sparkline + reply rate + sent)
└── if ?campaign=<id> → EchoCampaignView
    ├── HeroKpiRow (6 tiles; Reply rate is primary)
    ├── 2-col: FunnelChart (left 2/3) + TimeSeriesChart (right 1/3)
    ├── MicrositeMetricsBlock (PostHog-sourced)
    └── ContactDrillTable (filter chips + row click → DetailModal)
```

OutreachTab inline analytics uses the same `<HeroKpiRow>`, `<FunnelChart>`, `<TimeSeriesChart>` components above the existing `RecipientsDrillDown`.

### 4.4 Chart library

**Recharts** — first chart library in the repo (no chart lib installed today per `frontend/package.json`). Add to `frontend/package.json` dependencies. Lazy-load the chart chunk via dynamic import so the initial bundle stays thin (~95KB gzipped tree-shaken for `LineChart` + `AreaChart` + `Tooltip` + `ResponsiveContainer` + `XAxis` + `YAxis` + `CartesianGrid` + `Legend`).

**Funnel stays hand-rolled** (Tailwind + SVG), matching the existing pattern in `CampaignAnalytics.tsx:33-61`. Recharts' `FunnelChart` is weaker than our custom version; no reason to switch.

### 4.5 States

| State | Condition | Display |
|---|---|---|
| Loading first paint | TanStack Query `isLoading` | Skeleton tiles + skeleton funnel + skeleton chart frame |
| Loading refetch | `isFetching` after first paint | 2px progress sliver under filter bar; content stable |
| Empty pre-send | campaign.status ∈ {Draft, Ready, Generating, Review} | EmptyState: "Campaign hasn't shipped yet. Analytics unlock after first send." |
| Empty post-send no events | sent>0 but all engagement=0 | EmptyState: "Awaiting engagement. Events typically arrive within 2 hours of send." |
| Webhook lag banner | last_send_at > now-30min | Banner: "Some events may still be in flight. Tracking usually settles within 2 hours." |
| PostHog down | PostHog API failure | Microsite block only: "PostHog temporarily unavailable. Retrying in 30s." |
| Reply rate unavailable | Tenant has not connected Gmail | Reply rate tile shows `—` with subtext "Connect Gmail to track replies" and a small `Connect →` link that opens `/settings/gmail` (placeholder route; owned by BL-1044) |
| Error | API 4xx/5xx | Error card with Retry button (reuse existing `AnalyticsError` pattern) |

### 4.6 Responsive

- Desktop ≥1280px: 6-tile hero row, funnel + series side-by-side, full-width drill table.
- Laptop 1024–1279: hero wraps to 3×2, funnel + series stack vertically (funnel first).
- Tablet 768–1023: hero 2×3, everything vertical, drill table degrades to card list at ≤900px.
- Mobile <768px: **deferred to v2**. Page scrolls, nothing breaks, no custom mobile layout.

### 4.7 Accessibility

- Every chart ships a sibling `<details>` element with equivalent `<table>` data.
- SVG charts have `role="img"` + `aria-label` summary.
- Keyboard: Tab through filter bar → hero tiles → funnel stages (arrow keys between) → series (left/right crosshair) → drill table.
- `prefers-reduced-motion`: no chart enter animations when set.
- Comparison series (Phase 2) will use color + line-style (solid/dashed) so CVD users aren't blocked.

### 4.8 Copy discipline

No "dead leads", "ignored you", "failed prospects". Use "No response yet", "Awaiting engagement", "Drop-off at open". Enforced in code review (add to `docs/process/COPY.md` if not already there).

---

## 5. Technical Design

### 5.1 PostHog audit findings (2026-04-21)

Full repo grep for `posthog|POSTHOG|PostHog` returned four matches, all documentation:
- `docs/specs/drafts/campaign-analytics-em.md` (analyst draft)
- `docs/specs/drafts/campaign-analytics-pm.md` (analyst draft)
- `docs/specs/eventfest-campaign-outreach.md` — mentions "PostHog integration in microsite" as an **external/microsite-side dependency**, not ours
- `api/routes/campaign_routes.py:2817, 2978` — comments explicitly saying "no PostHog calls (LEADGEN-04)" — i.e. current state is zero PostHog integration on our side

Env-var check: `.env.example` and `api/config.py` have **no `POSTHOG_*` keys**. `frontend/package.json` does not declare `posthog-js`. `extension/package.json` likewise.

**Conclusion**: PostHog is currently **instrumented inside the ua-microsite repo only** (separate codebase). Nothing in `leadgen-pipeline` reads from or writes to PostHog today. This spec adds the first integration.

### 5.2 Data sources split

| Metric family | Source | Access path |
|---|---|---|
| sent / delivered / bounced / opened / clicked / replied / unsubscribed | **Our DB** `email_send_log` populated by Resend webhook handler | Extend existing `api/routes/campaign_routes.py:2635-2960` endpoint |
| microsite visits / unique visitors / time-on-page / CTA clicks / form submits | **PostHog Query API** | NEW `api/integrations/posthog.py` |
| per-contact email timeline | **Our DB** `email_send_log` + `activities` | Existing `GET /api/campaigns/:id/recipients` |

This split is documented in a new ADR (see §5.9).

### 5.3 Affected components

| Component | File | Change |
|---|---|---|
| PostHog client | `api/integrations/posthog.py` | **New** — Query API wrapper, 30s LRU cache, graceful degradation |
| Config | `api/config.py` | Modified — add `POSTHOG_HOST`, `POSTHOG_PROJECT_ID`, `POSTHOG_PERSONAL_API_KEY`, `POSTHOG_PROJECT_API_KEY` |
| Env template | `.env.example` | Modified — document new env vars |
| Webhook handler | `api/routes/webhook_routes.py` | **Bug fix (BL-1028)** — verify `resend_message_id` match writes opened_at/clicked_at |
| Webhook secret | `RESEND_WEBHOOK_SECRET` staging + prod | Chore — set secret, harden `_verify_svix_signature` to fail-closed when missing (currently skips verification silently) |
| Time-series endpoint | `api/routes/campaign_routes.py` | **New** — `GET /api/campaigns/:id/analytics/timeseries?range=&bucket=` |
| Microsite metrics endpoint | `api/routes/campaign_routes.py` | **New** — `GET /api/campaigns/:id/analytics/microsite?range=` (calls PostHog) |
| SSE stream endpoint | `api/routes/campaign_routes.py` | **New** — `GET /api/campaigns/:id/analytics/stream` |
| Existing analytics endpoint | `api/routes/campaign_routes.py:2635-2960` | Modified — include `reply_rate` + microsite KPI summary |
| Recipients endpoint | `api/routes/campaign_routes.py:2963-3078` | Modified — accept `?metric=opened\|clicked\|bounced\|visited&range=` |
| DB indexes | `migrations/061_analytics_indexes.sql` | **New** — composite partial indexes on `(tenant_id, sent_at)` / `(tenant_id, opened_at)` / `(tenant_id, clicked_at)` + microsite activity time index |
| Email link builder | `api/services/send_service.py` (or `api/utils/microsite_links.py` — EM to locate during plan phase) | Modified — append `?c=<campaign_id>&r=<recipient_id>` to every microsite link |
| Echo route | `frontend/src/App.tsx`, `frontend/src/components/layout/AppNav.tsx:78-86` | Modified — replace `PlaceholderPage` with `EchoPage` |
| Echo page | `frontend/src/pages/echo/EchoPage.tsx` | **New** — list view + per-campaign view via `useSearchParams` |
| Chart components | `frontend/src/components/charts/FunnelChart.tsx`, `TimeSeriesChart.tsx`, `KpiTile.tsx`, `MicrositeMetricsBlock.tsx`, `ContactDrillTable.tsx` | **New** — lazy-loaded chunk |
| SSE hook | `frontend/src/hooks/useCampaignAnalyticsStream.ts` | **New** — EventSource wrapper with reconnect |
| TanStack queries | `frontend/src/api/queries/useCampaigns.ts` | Modified — add `useCampaignAnalyticsTimeseries`, `useCampaignMicrositeMetrics` |
| OutreachTab integration | `frontend/src/components/campaign/OutreachTab.tsx` | Modified — add `<HeroKpiRow>` + `<FunnelChart>` + `<TimeSeriesChart>` above existing `RecipientsDrillDown` |
| Deep link | `frontend/src/pages/campaigns/CampaignDetailPage.tsx` | Modified — "View analytics" link in header |
| Microsite instrumentation | External `ua-microsite` repo (coord required) | Modified — add `posthog-js`, read `?c=` and `?r=` URL params, set as super-properties, capture `$pageview` + `cta_clicked` + `form_submitted` |
| Chart lib | `frontend/package.json` | Modified — add `recharts` |
| ADR | `docs/adr/010-campaign-analytics-data-sources.md` | **New** |
| ARCHITECTURE.md | `docs/ARCHITECTURE.md` | Modified — add Echo route + new endpoints |
| CHANGELOG.md | `CHANGELOG.md` | Modified |
| Unit tests | `tests/unit/test_campaign_analytics_timeseries.py`, `test_posthog_integration.py`, `test_analytics_sse.py` | **New** |
| E2E test | `frontend/tests/e2e/campaign-analytics.spec.ts` | **New** (sprint-completion, not per-PR) |

### 5.4 Data model changes

**Short answer: no new tables. Add indexes only.** The existing `email_send_log` + `activities` + `campaign_contacts` already capture everything needed; PostHog owns its own data store.

New migration `migrations/061_analytics_indexes.sql`:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_send_log_tenant_sent_at
  ON email_send_log (tenant_id, sent_at) WHERE sent_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_send_log_tenant_delivered_at
  ON email_send_log (tenant_id, delivered_at) WHERE delivered_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_send_log_tenant_opened_at
  ON email_send_log (tenant_id, opened_at) WHERE opened_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_send_log_tenant_clicked_at
  ON email_send_log (tenant_id, clicked_at) WHERE clicked_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_activities_microsite_tenant_time
  ON activities (tenant_id, occurred_at) WHERE source = 'microsite';
```

Note: the existing `microsite_event` ingest endpoint (commit 256d531) + table stays in place this sprint — **not ripped out**. It's no longer the source of truth for analytics reads (PostHog is), but leaving the write path alive avoids coordination with the microsite team this sprint. Deprecation is a later cleanup.

### 5.5 New environment variables

Add to `.env.example` and document in `api/config.py`:

```bash
# PostHog (paid license — US cloud, region locked, see note below)
POSTHOG_HOST=https://us.i.posthog.com          # US region — account was created in US
POSTHOG_PROJECT_ID=123456                        # numeric project id
POSTHOG_PROJECT_API_KEY=phc_xxx                  # public — ships to browser via posthog-js (safe in client bundle, still belongs in env/1P not git)
POSTHOG_PERSONAL_API_KEY=phx_xxx                 # secret — backend Query API reads; never logged, never exposed to frontend
```

**Region = US.** Account was created in US region; EU migration is a separate future effort if ever needed. See §6 Security for GDPR consideration and §10 Open Questions for the pending personal API key provisioning.

**Key provisioning & storage (do NOT hardcode in repo):**
- `POSTHOG_PROJECT_API_KEY` (public client-side key): store in 1Password `visionvolve-prod` vault as `POSTHOG_PROJECT_API_KEY`. Pulled into local dev via `bash scripts/init-env.sh`. This is a PUBLIC key — ships to the browser via posthog-js in the ua-microsite bundle — so its exposure is acceptable. It still must not live in git.
- `POSTHOG_PERSONAL_API_KEY` (secret backend key): **not yet provisioned by sponsor.** Must be generated in PostHog (Settings → Personal API Keys → Create) and stored in 1Password `visionvolve-prod` vault. Required before BL-1035 execution starts. See Open Questions.

Secrets delivered via:
- Staging: `STAGING_DOTENV` GitHub secret (per `visionvolve-vps/staging/` deploy flow)
- Production: 1Password `visionvolve-prod` vault, deployed via existing API deploy script
- Local dev: `bash scripts/init-env.sh` pulls from staging VPS → `.env.dev`

### 5.6 Campaign attribution chain

1. **Email link builder** (locate during plan phase — likely `api/services/send_service.py` or a dedicated URL helper) appends `?c=<campaign_id>&r=<recipient_id>` to every microsite link in every rendered email.
2. **Microsite** (external `ua-microsite` repo):
   - Reads `?c=` and `?r=` on page load via JS.
   - Sets PostHog super-properties: `posthog.register({campaign_id, recipient_id})`.
   - Calls `posthog.identify(recipient_id)` when available.
   - Captures `$pageview` automatically, plus custom events `cta_clicked`, `form_submitted`, `product_viewed`.
3. **Backend Query**: PostHog Query API called with HogQL `SELECT event, properties.campaign_id, count() FROM events WHERE properties.campaign_id = '<id>' AND timestamp > now() - interval 7 day GROUP BY event, campaign_id`.

### 5.7 New API endpoints

All require `@require_role("viewer")` + `resolve_tenant()` + explicit `WHERE tenant_id = :tenant_id` on the campaign row. 404 on tenant mismatch (not 403).

#### `GET /api/campaigns/:id/analytics/timeseries?range=7d&bucket=day&metrics=sent,opened,clicked`

Params: `range` ∈ {24h,7d,30d,all}, `bucket` ∈ {hour,day,week} (auto from range if omitted), `metrics` CSV whitelist.

Response:
```json
{
  "range": {"from": "2026-04-14T00:00:00Z", "to": "2026-04-21T00:00:00Z", "bucket": "day"},
  "series": [
    {"t": "2026-04-14", "sent": 120, "delivered": 118, "opened": 42, "clicked": 8}
  ]
}
```

#### `GET /api/campaigns/:id/analytics/microsite?range=7d`

Calls PostHog Query API. 30s server-side LRU cache keyed by `(campaign_id, range)`.

Response:
```json
{
  "range": {...},
  "visits": 58,
  "unique_visitors": 41,
  "median_time_on_page_sec": 87,
  "cta_clicks": 12,
  "form_submits": 3,
  "source": "posthog",
  "fallback": false
}
```

On PostHog 5xx/timeout: returns `{"fallback": true, "error": "posthog_unavailable"}` with last-known cache if available.

#### `GET /api/campaigns/:id/analytics/stream` (SSE)

Headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`.

Emits events on:
- Resend webhook received for a recipient in this campaign → immediate emit
- 15s server-side timer → poll PostHog delta, emit if changed
- 30s heartbeat regardless (keeps connection alive through proxies)

Event format:
```
event: analytics.update
data: {"funnel": {...}, "hero": {...}, "ts": "2026-04-21T12:30:00Z"}

event: heartbeat
data: {}
```

Client reconnects on drop with exponential backoff (1s → 2s → 4s → cap 30s). Caddy config requires `X-Accel-Buffering: no` header passthrough — verify in `visionvolve-vps/caddy/conf.d/` snippet.

#### Extend `GET /api/campaigns/:id/analytics` (existing)

Add fields: `engagement.reply_rate`, `microsite.{visits, cta_clicks, form_submits}` (pulled from `/analytics/microsite` handler to stay DRY).

#### Extend `GET /api/campaigns/:id/recipients` (existing)

Accept `?metric=opened|clicked|bounced|unsubscribed|visited&range=7d`. Default (no params): current behavior.

### 5.8 Frontend architecture

URL state (react-router `useSearchParams`):
- `/echo` — campaign list
- `/echo?campaign=<id>&range=7d` — per-campaign detail
- `/echo?campaign=<id>&range=7d&metric=opened` — detail with drill filter

TanStack Query keys:
- `['campaign-analytics', id]` (exists)
- `['campaign-analytics-timeseries', id, range, bucket, metrics]` (new)
- `['campaign-microsite', id, range]` (new, 30s staleTime)
- SSE stream managed outside TanStack (EventSource lifecycle in `useCampaignAnalyticsStream`)

Lazy loading: `EchoPage` and the chart components live in a separate Vite chunk (dynamic `import()`). Initial bundle unaffected.

### 5.9 Architecture decisions (ADR-010)

New ADR: `docs/adr/010-campaign-analytics-data-sources.md`. Decisions:

1. **Split source of truth**: email telemetry in leadgen DB, microsite analytics in PostHog. Rationale: PostHog already owns session analytics, heatmaps, funnels, retention — expensive to re-implement. Resend webhook data stays in our DB because we need contact-level drill joins that PostHog can't express naturally.
2. **SSE over polling**: lower latency than 10s poll, simpler than WebSocket. One-way stream is sufficient.
3. **Aggregation strategy**: on-the-fly PG aggregation with partial indexes (§5.4). No materialized views until >10 tenants or >1M events per tenant.
4. **Attribution via URL params**: `?c=<campaign>&r=<recipient>` on every microsite link. No campaign_id column added to `activities` (avoids denormalization drift when contacts move between campaigns).
5. **Microsite multi-campaign overcount**: documented known limitation. One microsite visit counts for every campaign the contact is in. Acceptable at current scale (1 tenant, rare overlap). Revisit when overlap grows.
6. **PostHog instance**: **US cloud** (`https://us.i.posthog.com`). Account was created in US region; EU migration is a separate future effort if ever needed. Configurable via `POSTHOG_HOST`. See Security §6 for GDPR consideration.
7. **Existing `microsite_event` table**: leave in place, writes continue, reads deprecated. Formal removal is a Phase 2 cleanup item.

Existing ADRs that remain in force: ADR-006 (Campaign Data Model), ADR-007 (Message Version Tracking), ADR-009 (External API Patterns — webhooks).

### 5.10 Tech debt interactions

| Debt | Interaction |
|---|---|
| **BL-1028** (opened_at/clicked_at NULL) | **HARD BLOCKER** — must ship in-sprint before or in parallel with analytics. Zero point rendering a dashboard on empty data. |
| **BL-1029** (superseded rows) | Analytics queries default to `WHERE status != 'failed_superseded'`. Coordinate in-sprint. |
| **BL-1026** (preview pollution) | Analytics queries default to `WHERE kind != 'preview'`. Preview flag must land even if full BL-1026 helper doesn't. |
| TD-002 (no API rate limiting) | New endpoints are aggregation-heavy; add rate limit post-v1 if refresh storms appear |
| TD-003 (SQLite test compat) | `date_trunc` is PG-specific; verify conftest shim covers it, else use PG-only integration tests for this suite |
| TD-004/TD-009 (input validation) | Strict range/bucket/metrics enum; 400 on invalid |

---

## 6. Security

- `POSTHOG_PERSONAL_API_KEY` is **secret**, backend-only. Never exposed to frontend. Never logged.
- `POSTHOG_PROJECT_API_KEY` is **public** — used by microsite for event ingestion. Safe to ship in microsite JS bundle.
- All new endpoints verify tenant membership on the campaign before serving data. 404 (not 403) on cross-tenant ID.
- PostHog queries always include `AND properties.campaign_id = :campaign_id` with the campaign's tenant verified first.
- `RESEND_WEBHOOK_SECRET` is now **fail-closed** (BL-1034 — `_verify_svix_signature` returns False when the secret is missing or empty, handler responds with 401, missing-secret case logs at `ERROR` level). There is no dev-bypass path in production code. For local dev without a valid secret, set `RESEND_WEBHOOK_SECRET=any-local-string` in `.env.dev` and sign test payloads accordingly (see `tests/unit/test_webhook_routes.py` for the HMAC signing helper).

### 6.1 Webhook secret rotation runbook (BL-1034)

1. In the Resend dashboard, open Webhooks → the target endpoint → **Rotate signing secret**. Copy the new value (format `whsec_...`).
2. Update the 1Password item `visionvolve-prod` / `Resend Webhook (leadgen-pipeline)` field `RESEND_WEBHOOK_SECRET` with the new value.
3. Update staging: rotate the GitHub secret `STAGING_RESEND_WEBHOOK_SECRET` on `michallicko/visionvolve-vps` (`gh secret set STAGING_RESEND_WEBHOOK_SECRET --repo michallicko/visionvolve-vps`), then trigger the staging infra redeploy (`gh workflow run deploy-staging-infra.yml --repo michallicko/visionvolve-vps`).
4. Update production: rotate the equivalent production secret (`PROD_RESEND_WEBHOOK_SECRET` on the same repo — add if missing alongside existing `PROD_RESEND_API_KEY`) and redeploy the leadgen-api container.
5. Verify by sending a Resend test event from the dashboard; confirm the corresponding `EmailSendLog` row is updated and no `CRITICAL: RESEND_WEBHOOK_SECRET is not configured` entries appear in logs.
- SSE endpoint authenticates via JWT in Authorization header (same as other routes). Connection is tenant-scoped.
- PostHog event ingestion from microsite uses the public project API key — no backend secret exposure.
- **GDPR consideration**: Microsite analytics sent to PostHog US region. Acceptable for current tenant (VisionVolve). If EU-resident tenant data flows through the microsite in future, evaluate region migration or dual-project setup.

---

## 7. Testing

### Unit (pytest, `tests/unit/`, context-aware per CLAUDE.md)

- `test_campaign_analytics_timeseries.py`: bucket padding, range filter correctness, metrics filter, tenant isolation (tenant B events never appear in tenant A response)
- `test_posthog_integration.py`: cache hit/miss, PostHog 5xx → graceful fallback, query construction with tenant-scoped campaign_id filter, no personal API key leaked to response
- `test_analytics_sse.py`: heartbeat cadence, event emission on webhook arrival, client disconnect cleanup, tenant isolation on stream
- `test_webhook_resend_fix.py` (BL-1028): synthetic delivered/opened/clicked webhook → rows updated correctly; idempotent on replay
- `test_webhook_secret_fail_closed.py`: missing `RESEND_WEBHOOK_SECRET` → 401 not 200

Run: `make test-changed`

### E2E (Playwright, sprint-completion only)

`frontend/tests/e2e/campaign-analytics.spec.ts`:
1. Seed staging with campaign that has sent + opened + clicked + 1 PostHog visit (simulate via direct ingest).
2. Navigate to `/echo` → campaign list renders with KPIs.
3. Click campaign → URL updates, funnel + time-series + hero render.
4. Toggle range 7d → 30d → chart updates.
5. Click "Opened" funnel stage → drill table filters.
6. Click recipient row → DetailModal opens.
7. Navigate to campaign detail → click "View analytics" → lands on Echo scoped view.
8. OutreachTab on campaign detail renders hero + funnel + time-series inline.

### Playwright MCP interactive verification

Sprint-close gate: spawn an agent with Playwright MCP access that walks through the full staging flow as a real user, capturing screenshots at each step. Required before marking any feature item Done per project quality gate.

---

## 8. Dependencies

### Hard blockers (in-sprint or pre-sprint)

- **BL-1028**: Populate `email_send_log.opened_at / clicked_at` — bundled in this sprint
- **Set `RESEND_WEBHOOK_SECRET` in staging + prod** and harden verification to fail-closed — bundled

### Soft dependencies (in-sprint for data hygiene)

- **BL-1029**: Mark superseded send-log rows — bundled (analytics query filters depend on this)
- **BL-1026**: Preview pollution filter — minimal `kind='preview'` column flag bundled; full helper is out of scope

### Supersedes

- **BL-174** (archived Sprint 7): Original "Campaign Analytics Dashboard" — superseded by this spec; leave archived, add note
- **BL-305** (Sprint 23): Sequence funnel in OutreachTab — absorbed into FR-1 + FR-10; close as duplicate of this sprint
- **BL-317** (Refined): Microsite → leadgen activity webhook + PostHog — partially superseded. The activity webhook (commit 256d531) is in place; PostHog reads are added by this spec. Update BL-317 status: the remaining scope (scroll depth, video plays) is a later PostHog capture enhancement in the microsite repo, not in leadgen

### External coordination

- **ua-microsite repo**: needs `posthog-js` instrumentation + URL param reading. Spec owner to coordinate; this work is out of this repo's tree.

---

## 9. Out of Scope (v1)

Explicit non-goals so the sprint doesn't drift:

- **Cross-campaign comparison view** (Phase 2) — multi-select, overlay charts, delta callouts
- **Dedicated `/monitor` page or pillar rename** — sponsor decision: keep Echo, no rename
- **Heatmap visualization** (Phase 3) — depends on PostHog element-level tracking, defer
- **Anomaly detection** (Phase 3 / BL-172 thread) — "opens dropped 40% vs last campaign" alerts
- **AI coaching / recommendations** — BL-048 thread, downstream consumer of this data
- **Mobile-optimized layout** — page scrolls, nothing breaks, no investment in <768px charts
- **Reply detection from inbound mail** — inbound pipeline not yet wired; Reply rate tile renders with `—` placeholder + "Connect Gmail to track replies" prompt (see §4.5 UI States) until Gmail integration lands
- **Gmail OAuth + inbound mail ingestion + reply attribution** — tracked in **BL-1044** for a follow-up sprint. The UI tile + placeholder affordance ship this sprint so the slot auto-populates when Gmail ingestion arrives
- **Deprecation of existing `microsite_event` table + ingest endpoint** — leave in place this sprint; formal removal later
- **Materialized daily rollup tables** — on-the-fly PG aggregation is sufficient at current scale
- **LangSmith / LLM-ops telemetry** — separate surface (super-admin), BL-272 thread
- **Export to CSV / PNG / share-link** — deferred to Phase 2

---

## 10. Open Questions

Unresolved items needing sponsor or EM input during plan phase:

1. **PostHog webhook for real-time push vs we poll every 15s?** Simpler to poll; check PostHog's webhook support during EM plan phase. If available, switch to push for lower latency.
2. **Email link builder location**: the outbound email generator that renders microsite links needs to be located (likely `api/services/send_service.py` or a URL helper). Does it already append any tracking params (e.g. from BL-315 partner attribution)? If yes, format needs to be compatible with the new `?c=&r=` convention.
3. **Existing `microsite_partner_token` attribution vs new `?r=`**: the `CampaignContact.microsite_partner_token` is already used for attribution in `api/routes/tracking_routes.py`. Do we keep both (backward compat) or consolidate on `?r=`?
4. **SSE vs WebSocket on Caddy**: verify Caddy staging + prod configs forward `text/event-stream` with buffering disabled. Add a health-check item.
5. **PostHog Personal API Key provisioning (BLOCKER for BL-1035 execution)**: `POSTHOG_PERSONAL_API_KEY` (`phx_…`) needs to be generated in PostHog (Settings → Personal API Keys → Create) and stored in 1Password `visionvolve-prod` vault as `POSTHOG_PERSONAL_API_KEY`. Required before BL-1035 (PostHog integration + microsite endpoint) starts. Sponsor action.

**Resolved (locked 2026-04-21):**
- Hero KPI = Click-through rate (clicks ÷ delivered). Reply rate → secondary tile with Gmail-connect placeholder. See §4.1, FR-3, AC-2/AC-2a.
- PostHog region = US (`https://us.i.posthog.com`). See §5.5, §6.
- Reply tracking deferred to BL-1044 (Gmail integration). Reply rate tile renders `—` + Connect CTA until then. See §9 Out of Scope.

---

## 11. Rollout plan

1. **Pre-sprint**: sponsor answers Open Questions 1, 2, 5 (15min conversation).
2. **Sprint kick-off**: PM verifies scope gate, EM runs plan phase (identifies email link builder file, confirms Caddy SSE path).
3. **Parallel tracks in sprint**:
   - Track A (backend): BL-1028 fix → webhook secret hardening → migration 061 → PostHog integration → timeseries + microsite + SSE endpoints
   - Track B (frontend): Recharts install → chart components → SSE hook → EchoPage → OutreachTab integration
   - Track C (chore): ADR-010 + ARCHITECTURE.md + CHANGELOG.md + new env vars in staging/prod
   - Track D (microsite, external coord): `posthog-js` instrumentation + URL param read in ua-microsite repo
4. **Sprint QA**: full E2E + Playwright MCP walkthrough + acceptance criteria verification on staging root.
5. **Gate**: founder opens last EventFest campaign, confirms numbers match Resend dashboard within 1% AND match PostHog project dashboard within 5%.
6. **Merge staging → main**: deploy to production. User tests on production root.

---

## 12. References

- Analyst drafts:
  - `docs/specs/drafts/campaign-analytics-pm.md`
  - `docs/specs/drafts/campaign-analytics-em.md`
  - `docs/specs/drafts/campaign-analytics-pd.md`
- Product strategy: `docs/PRODUCT_STRATEGY.md` (Theme 3)
- Vision: `docs/vision/index.html`
- Existing analytics endpoint: `api/routes/campaign_routes.py:2635-3078`
- Resend webhook: `api/routes/webhook_routes.py:46-187` (commit `aafd96c`)
- Microsite ingest (deprecated for reads): `api/routes/tracking_routes.py:86-200` (commit `256d531`)
- Cost display rule: MEMORY.md — "Cost Display Rules"
- Copy discipline: `docs/vision/index.html` — "Never show harsh/judgmental language about prospects or companies"
