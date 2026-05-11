# Leadgen Pipeline — Project Context

## What This Is

Multi-tenant outreach & enrichment platform for **Visionvolve** and its clients (currently **Losers Cirque Company / United Arts**, abbreviated **LCC**). It is the "GTM operating system" — a closed-loop engine that imports contacts → enriches them (n8n + Perplexity/Anthropic) → generates and sends personalized outreach (Resend, Lemlist) → tracks engagement (Resend webhooks, microsite analytics, PostHog) → feeds results back into the playbook so the AI strategist gets smarter each cycle.

**In prod:** Lightsail VPS `visionvolvevps` at 52.58.119.191; dashboard at `https://leadgen.visionvolve.com/{namespace}/`; API at `https://leadgen.visionvolve.com/api/*`. Multi-tenant: each namespace (`visionvolve`, `losers`, etc.) is an isolated tenant on a shared PG schema with `tenant_id` column. Auth: JWT + namespace URL routing.

**Staging:** `https://leadgen-staging.visionvolve.com/` on Lightsail `leadgen_staging` (3.124.110.199). Auto-deploys from the `staging` branch via GHA.

**Cross-project partner:** `/Users/michal/git/ua-microsite` — Next.js product catalog at `booking.losers.cz`. LCC's partner-facing site. Sends per-partner microsite analytics back to leadgen-pipeline via `/api/tracking/microsite-event`. Several Sprint 25 phases execute in that repo.

## Core Value

**Zero busywork for the founder.** The user is the CEO; the AI is the strategist. Every interaction in the dashboard should either gather a decision or deliver a result. Closed-loop learning means each campaign improves the next. If everything else fails, this must work: a founder spending 10 minutes a week gets meaningful, personalized outreach to the right prospects with feedback on what worked.

## Context

- **Stack:** Python 3.13 / Flask / SQLAlchemy / PostgreSQL (RDS Lightsail managed PG) on the backend; React (Vite + TypeScript) + a vanilla-HTML dashboard on the frontend; n8n self-hosted for enrichment orchestration; Docker on the VPS; Caddy reverse proxy.
- **Outbound:** Resend (primary, transactional + campaign) + Lemlist (sequencing). Resend webhooks (`email.delivered`, `email.opened`, `email.clicked`, `email.bounced`, `email.unsubscribed`) flow into `email_send_log` (BL-1028 fixed in Sprint 24).
- **Inbound analytics:** PostHog for microsite events (BL-1047, merged into `/analytics` page); Resend webhook handler (BL-315) for email engagement.
- **Enrichment:** n8n orchestrator workflow (`N00qr21DCnGoh32D`) → L1 company + L2 company + Person sub-workflows. Perplexity + Anthropic credentials.
- **Auth:** JWT (bcrypt passwords, access + refresh tokens). RBAC: `super_admin | namespace_admin | user`.
- **Multi-tenant URL routing:** `leadgen.visionvolve.com/{slug}/page` — Caddy strips the namespace prefix, JS reads `LeadgenAuth.getNamespace()` from the path.
- **Active sprints just shipped:** Sprint 24 (Campaign Analytics v1) — see CHANGELOG.md and `docs/specs/campaign-analytics.md`. Sprint 23 work also recently merged (Gmail OAuth foundation BL-1044, Resend reconciler BL-1045).
- **Branching:** main (production) ← staging (latest beta) ← feature/* (worktree-based parallel agent work). PRs required for both staging and main merges. Branch protection enforced.

## Current Milestone — v25 LCC Client Requests

**Goal:** Land the 17 asks captured from LCC (Losers Cirque Company) on 2026-05-11. These split across:
- **2 microsite quick wins** — logo refresh, Kc→Kč copy fix (ua-microsite repo)
- **1 reported bug** — Contacts table lazy-load duplicates + scroll jump (leadgen frontend)
- **5 contact-data foundations** — inline edit, salutation, company categorization
- **3 campaign-DB prep items** — CZ agencies cold, autumn/winter cultural orgs, DACH agencies
- **2 unsubscribe-loop items** — track + suppress unsubscribes, send confirmation email
- **1 cross-repo tracking links item** — per-contact unique URL generator
- **1 partner admin** — admin route on booking.losers.cz
- **1 bilingual mailing item** — CZ default, EN auto by contact.language
- **1 campaign reach reporting item** — per-campaign + cross-campaign reach

Source: 17-row CSV from LCC plus one bug report raised in the same review session. Tracked as backlog items **BL-1100..BL-1116** in `Sprint 25 — LCC client requests`. Phase decomposition in `ROADMAP.md`.

**Hard deadlines:** Items #1, #2, #3, #10, #16 are priority-1 with "ASAP" deadline. Item #1 (universal catalog link) is already Done. The other four (logo, bounces export, Kc→Kč, partner admin) are the urgent batch — Phases 1, 2, 8 in the roadmap.

**Cross-repo execution:** Phases 1, 7, 8 touch the `ua-microsite` repo (`/Users/michal/git/ua-microsite`). The executing agent must `cd` into that repo, branch from its `staging`, and PR back to its `staging` — NOT to leadgen-pipeline. The backlog item still tracks the cross-repo PR URL for unified visibility (see `gsd-phase-mapping` directive in backlog service).

### v25 north-star checks

Every Sprint 25 phase must move us closer to:
- A founder who can review a campaign's bounce list in one click (BL-1102, BL-1114)
- A contact database the team can trust because it's editable (BL-1107) + categorized (BL-1108)
- A mailing system that respects unsubscribes by default (BL-1103 + BL-1105)
- Per-contact tracking that proves "they looked" without a 3-step manual setup (BL-1104, BL-1115)

If a phase doesn't visibly serve one of those, replan before executing.

## Requirements

### Validated (existing v1..v24)

See `CHANGELOG.md` for the full ledger. Recent v24 wins:
- ✓ Engagement timestamps land in `email_send_log` from Resend webhooks (BL-1028)
- ✓ Resend reconciler backfills retroactively (BL-1045)
- ✓ PostHog microsite metrics merged into `/analytics` page (BL-1047)
- ✓ Gmail OAuth foundation — encrypted token storage + settings page (BL-1044)
- ✓ Campaign Analytics v1 SSE frontend wiring
- ✓ Stakeholder preview + render-as-real-partner helper (BL-1026)
- ✓ Superseded-row tracking for retry safety (BL-1029)

### Active (Milestone v25)

Mapped 1:1 to phases — see `ROADMAP.md`.

| Phase | Backlog | Outcome |
|-------|---------|---------|
| 1 | BL-1101, BL-1109 | Microsite logo + Kc→Kč copy fixes live on `booking.losers.cz` |
| 2 | BL-1102 | EventFest bounces CSV exported + recurring "Export bounces" button on Campaigns page |
| 3 | BL-1103, BL-1105 | Unsubscribes recorded, contact suppressed from future sends, confirmation email delivered |
| 4 | BL-1116 | Contacts/Companies table: no duplicate rows on scroll, no scroll-position jump |
| 5 | BL-1106, BL-1107 | Operators can inline-edit core Contact + Company fields; salutation is a first-class editable field |
| 6 | BL-1108 | Each company carries a category (`agency_b2b | corporate_b2c | public_org_b2g | cultural_referent | festival_organizer`) |
| 7 | BL-1104 | Operator can copy a per-contact unique catalog URL (with/without prices) and see opens on the contact row |
| 8 | BL-1115 | LCC team has `/cs/admin/partners` route on `booking.losers.cz` |
| 9 | BL-1110 | Mailings render in CZ by default, EN when `contact.language='en'` |
| 10 | BL-1111, BL-1112, BL-1113 | Three audience-ready draft campaigns: CZ agencies cold, autumn/winter event orgs, DACH agencies |
| 11 | BL-1114 | Campaign reach reporting with per-campaign + 30/60/90-day unique-reach |

### Out of Scope (this milestone)

- **AI auto-categorization of companies** — humans categorize in v25; ML inference is a future iteration. *Why:* avoid blocking on prompt design + accuracy validation.
- **Per-tenant Resend BYOK** (BL-030) — separate platform-foundation effort, not LCC-specific.
- **Sending the three new campaigns** in Phase 10 — Sprint 25 only prepares the database + draft campaigns. Actual send is a later sprint with founder-written copy.
- **Reply-tracking** — future Resend webhook (`email.replied`) work, not in v25.
- **Production deploy** — every v25 PR merges to `staging`; production deploys are a separate cutover after user sign-off.

## Constraints

- **Branching:** `main` is production; `staging` is the integration branch. Feature work happens on `feature/*` worktrees, PRs to `staging`, then `staging` → `main` after acceptance. `git checkout main` / `git switch main` are denied by hook.
- **Testing during feature work:** Use `make test-changed` and `make lint-changed` — never full `make test` (5+ minutes wasted). E2E (`make test-e2e`) runs at sprint completion only, not per PR.
- **Local-first:** Every code change must be tested locally with `make dev` (hot reload Flask+Vite) before any staging deploy. Local verification gate is non-negotiable.
- **Cross-repo phases:** Phases 1, 7, 8 require working in `/Users/michal/git/ua-microsite`. Agent must `cd` into that repo and PR against its own `staging` branch.
- **Backlog status updates:** Every executor must call `backlog_claim_item` → `backlog_update_item(status='Building')` → `backlog_update_item(status='PR Open')` → `backlog_update_item(status='Done')` → `backlog_release_item` at the appropriate phase boundaries. Skipping these is a process violation.
- **No agents read source in the lead context:** Lead coordinator NEVER reads code, runs git, or executes deploys. All such work goes through spawned agents (Team Delegation Mode is always on — see global CLAUDE.md).

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Bootstrap GSD `.planning/` for v25 (not earlier) | Sprints 1–24 ran via the backlog service directly. v25's cross-repo + structured-phases scope is the first time GSD's milestone/phase artifact set adds enough value to be worth the bootstrap overhead. | — Pending v25 completion |
| Phase decomposition uses 11 phases (rather than fewer larger phases) | Each phase maps to 1–3 backlog items so executor agents have tight scope + clear PR boundaries. Larger phases create coordination tax across parallel agents. | — Pending v25 |
| BL-1107 (inline edit) sequenced before BL-1108 (categorization) | Categorization needs editable Company rows to be useful; if we ship categorization first without edit-in-place we ship a half-feature operators can't use. | — Pending Phase 5/6 |
| BL-1115 (partner admin) built inside `ua-microsite` (not leadgen) | Client expects it on `booking.losers.cz`; Payload CMS already has admin auth scaffolding; minimizes new auth surface. | — Pending Phase 8; revisit if Payload extension proves too costly |
| BL-1102 (bounces export) is a Phase 2 standalone (not bundled with reach reporting BL-1114) | The client asked for it as priority-1 ASAP; it's a single SQL query + CSV. BL-1114 is priority-3 and pulls in 30/60/90-day windows. Bundling delays the urgent ask behind the broader reporting design. | — Pending Phase 2 |
| Cross-repo phases (1, 7, 8) PR against `ua-microsite`'s staging, not this repo | The cross-repo dependency is one-way: ua-microsite uses leadgen's API, not vice-versa. Code lives where it runs. | — Decided 2026-05-11 |

---
*Last updated: 2026-05-11 after GSD bootstrap for Milestone v25.*
