# Sprint 24 — Campaign Analytics v1 — Manual Test Script

**Staging URL:** https://leadgen-staging.visionvolve.com
**Scope:** Echo page, OutreachTab analytics block, campaign deep link, Gmail OAuth scaffolding, PostHog microsite merge.

Run this script after every staging deploy that touches analytics code. Mark each check PASS / FAIL. Fix FAILs and redeploy before handing off to the user.

## 0. Prerequisites

- [ ] Staging deploy green (GHA workflow `deploy-staging.yml`). Verify via `gh run list --workflow=deploy-staging.yml --limit 1`.
- [ ] `curl https://leadgen-staging.visionvolve.com/api/health` returns `{"db":"connected","status":"healthy"}`.
- [ ] Login with a real tenant account (not `test@staging.local` — that user is currently stale per ops notes 2026-04-24).

## 1. Echo page — list view

- [ ] Navigate to `/:namespace/echo` (no query params).
- [ ] Campaign list renders with mini-sparkline + reply rate (placeholder "—") + sent count per row.
- [ ] Click any row → URL updates to `?campaign=<id>`.
- [ ] Empty state: a fresh namespace without campaigns renders an "No campaigns yet" message, not a crash.

## 2. Echo page — per-campaign detail

- [ ] `/:namespace/echo?campaign=<id>` renders per-campaign view.
- [ ] Hero KPI shows **CTR** (click-through rate) with clicks / delivered in the sub-text.
- [ ] Six supporting tiles: Sent, Delivered, Open rate, Click rate, Microsite visits, Reply rate (placeholder).
- [ ] Range selector (24h / 7d / 30d / all) updates URL and refetches.
- [ ] Funnel chart renders with 5 stages (Sent → Delivered → Opened → Clicked → Microsite).
- [ ] Time-series chart lazy-loads (network tab shows a separate chunk) and renders Recharts axes + lines.
- [ ] Microsite section shows 6 tiles: Total visits, Unique visitors, CTA clicks (or Product views fallback), Form submits, Avg time, Visit rate. **(BL-1047)**
- [ ] Contact drill table below funnel shows recipients with timeline chips (sent/opened/clicked).
- [ ] Live indicator pill shows "Live" (green) when SSE connects, "Polling" when fallback.

## 3. OutreachTab inline analytics

- [ ] Navigate to `/:namespace/campaigns/<id>` → Outreach tab.
- [ ] Hero CTR tile + 7 supporting tiles render above the RecipientsDrillDown.
- [ ] "Microsite" tile shows visits, "CTA clicks" (or "CTA actions" if PostHog offline) shows value.
- [ ] Reply rate tile shows "—" + "Connect Gmail" link pointing at `/:namespace/settings/gmail`.
- [ ] Funnel + Time series row renders side-by-side on desktop, stacked on tablet.
- [ ] RecipientsDrillDown (existing) still works with no regression.

## 4. Deep-link from campaign detail

- [ ] Campaign detail page header shows "View analytics" link (only when campaign.status != draft).
- [ ] Clicking it navigates to `/:namespace/echo?campaign=<id>&range=7d`.
- [ ] Echo receives the campaign id + range and renders the per-campaign view immediately.

## 5. PostHog microsite merge (BL-1047)

- [ ] **When PostHog is configured**: `microsite.source` === `"posthog"` in the `/api/campaigns/<id>/analytics` response; `cta_clicks` / `form_submits` / `avg_time_on_page_sec` are numbers (may be 0, but never null).
- [ ] **When PostHog env is missing**: top-level `posthog_available` === `false`; microsite fields fall back to activities-table counts; `microsite.cta_clicks` === null; UI shows "Microsite analytics temporarily unavailable" banner.
- [ ] Legacy `microsite.product_views` field still populated on both paths (Phase-2 removal deferred).
- [ ] No 5xx on either path — degradation is silent and non-blocking.

## 6. Reply rate placeholder + Gmail CTA

- [ ] Reply rate tile on Echo + OutreachTab shows "—" by default.
- [ ] Subtext shows "Connect Gmail to track replies" + a "Connect →" link.
- [ ] Link navigates to `/:namespace/settings/gmail` → Gmail connection settings page renders.
- [ ] "Connect Gmail" button initiates OAuth flow (lands on Google consent screen). **Note: full round-trip requires tenant-level OAuth app provisioning; see BL-1044-b.**

## 7. SSE live push

- [ ] Open devtools → Network → filter for `/analytics/stream`.
- [ ] An EventSource connection is active on Echo detail view + OutreachTab.
- [ ] Heartbeat event arrives ~every 30s (shows as `:heartbeat` in the stream).
- [ ] Simulate a webhook (via backend test tool or Resend dashboard) → `event: update` arrives within 2s and the hero KPI + funnel refresh.
- [ ] Disconnect network briefly → EventSource reconnects with exponential backoff (visible 1s, 2s, 4s gaps in devtools).

## 8. Security + tenant isolation

- [ ] `GET /api/campaigns/<id>/analytics` for a campaign in a different tenant returns 404 (not 403, not 200).
- [ ] `POST /api/webhooks/resend` without a valid svix signature returns 401 (BL-1034 fail-closed).
- [ ] Preview sends (`kind='preview'`) are excluded from all analytics rollups (BL-1026).
- [ ] Superseded retries (`superseded_at IS NOT NULL`) are excluded from default analytics (BL-1029).

## 9. Accessibility

- [ ] Tab through Echo detail view — focus order is: range selector → funnel → time series → microsite tiles → drill table.
- [ ] `<details>` sibling tables next to each chart are keyboard-openable + screen-reader-readable.
- [ ] `prefers-reduced-motion` honored: animated SSE pulse does not animate when reduced-motion is set.

## 10. Regression check

- [ ] Campaign list, campaign detail, Messages tab, Sequence tab, Settings tab all still work.
- [ ] Enrichment page + Contacts page unaffected.
- [ ] Import wizard unaffected.
- [ ] LLM costs dashboard unaffected.

## Sign-off

**Tester:** _________________ **Date:** _________________
**Staging SHA:** _________________

All PASS → notify user. Any FAIL → file backlog item + fix before handoff.
