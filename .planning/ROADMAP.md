# Roadmap — Milestone v25: LCC Client Requests

**Milestone goal:** Ship the 17 asks captured from LCC (Losers Cirque Company / United Arts) on 2026-05-11 — 1 already done, 11 phases covering 16 remaining items + 1 user-reported bug. Cross-repo: 3 phases execute in `ua-microsite`, 8 in `leadgen-pipeline`, 1 spans both. Phase 12 was added 2026-05-14 (editable company name + duplicate detection, BL-1117 — leadgen-pipeline only).

**Granularity:** standard (12 phases).
**Coverage:** 18/18 v25 backlog items mapped (BL-1100 is already Done — audit-trail only; BL-1117 added 2026-05-14 for Phase 12).
**Backlog sprint:** `Sprint 25 — LCC client requests` (backlog.visionvolve.com).
**Cross-repo:** Phases 1, 7, 8 execute in `/Users/michal/git/ua-microsite`. All other phases (including Phase 12) in `/Users/michal/git/leadgen-pipeline`.

## Parallelization

Suggested execution order (numeric prefix = wave; phases in the same wave can run in parallel):

```
Wave 1 (parallel):  Phase 1  |  Phase 2  |  Phase 4
Wave 2 (parallel):  Phase 3  |  Phase 5  |  Phase 8
Wave 3 (sequential dependents on Wave 2):  Phase 6  →  Phase 7
Wave 4 (sequential dependents on Wave 3):  Phase 9
Wave 5 (sequential dependents on Wave 3 + 4):  Phase 10  →  Phase 11
Phase 12 is independent — can run in any wave alongside Phases 5, 6, 9, 10, 11 (no dependency on the inline-edit foundation since useInlineEdit already exists for contact-email; verified 2026-05-14).
```

Rationale:
- Phases 1, 2, 4 are independent quick wins; each touches different code paths (microsite, leadgen CSV export, frontend table component).
- Phase 5 (inline edit) is a Must-Have foundation for Phases 6, 7, 9, 10. Phase 6 must follow 5; Phase 7 must follow 5; Phase 10 must follow 5+6+9.
- Phase 8 (partner admin in ua-microsite) is independent of the leadgen-side work and can run alongside Phases 5+6.
- Phase 11 needs Phase 6 (categorization) to do per-category breakdowns; ideally Phase 10's draft campaigns too, but the reach widget can ship without them.
- Phase 12 (editable company name) is added post-bootstrap; the useInlineEdit hook already exists for contact email so Phase 12 has no real dependency on Phase 5.

## Phases

- [ ] **Phase 1: Microsite Quick Fixes** — Logo refresh + Kc→Kč copy fix on `booking.losers.cz`
- [ ] **Phase 2: Eventfest Bounces Export** — CSV of EventFest bounces + recurring "Export bounces" button
- [ ] **Phase 3: Unsubscribe Loop** — Suppress unsubscribed contacts + send confirmation email
- [ ] **Phase 4: Tables Lazy-Load Bug Fix** — Eliminate duplicate rows + scroll-jump on Contacts/Companies tables
- [ ] **Phase 5: Editable Contact Fields** — Inline edit + salutation as first-class field
- [ ] **Phase 6: Company Categorization** — Five-category enum + filter UI
- [ ] **Phase 7: Unique Catalog Tracking Links** — Per-contact catalog URL generator + analytics
- [ ] **Phase 8: Partner Admin Access** — `/cs/admin/partners` route on `booking.losers.cz`
- [ ] **Phase 9: Multilingual Mailing Foundation** — CZ default, EN auto when `contact.language='en'`
- [ ] **Phase 10: Campaign Database Foundations** — Three audience-ready draft campaigns (CZ agencies / autumn-winter orgs / DACH agencies)
- [ ] **Phase 11: Campaign Reach Reporting** — Per-campaign + 30/60/90-day unique-reach widget
- [ ] **Phase 12: Editable Company Name + Duplicate Detection** — Inline edit company name with server-side normalize + duplicate-resolution modal (merge / use existing / keep both / cancel)

## Phase Details

### Phase 1: Microsite Quick Fixes
**Goal:** Ship two priority-1 client-visible fixes to the partner microsite — new LCC logo (provided in user's Downloads) and "Kc" → "Kč" currency abbreviation.
**Executes in:** `/Users/michal/git/ua-microsite`
**Depends on:** Nothing
**Parallel with:** Phase 2, Phase 4
**Backlog items:** BL-1101, BL-1109
**Success Criteria** (what must be TRUE):
  1. The microsite header on `booking.losers.cz` (and `/cs/demo`) renders the new LCC logo from the user's provided PNGs (`/Users/michal/Downloads/LOGO LCC 2025-01.png`, `… bile S.png`, `… bile 2025.png`).
  2. White-variant logo is used on dark-background contexts (email hero banner if applicable).
  3. Every user-facing CZK price renders "Kč" (with háček) — not "Kc". A `grep` of the codebase finds zero standalone "Kc" tokens in user-facing render paths.
  4. Playwright catalog page test contains `expect(...).toContainText('Kč')` assertion and passes.
  5. Visual diff (or screenshot review) approved by the user before merge.
**Plans:** TBD

Plans:
- [ ] 01-01: TBD — define during `/gsd-plan-phase 1`

---

### Phase 2: Eventfest Bounces Export
**Goal:** Deliver the one-shot bounces CSV LCC asked for AND add a permanent "Export bounces" button on the Campaigns page so this is repeatable for every future campaign.
**Executes in:** `/Users/michal/git/leadgen-pipeline`
**Depends on:** Nothing
**Parallel with:** Phase 1, Phase 4
**Backlog items:** BL-1102
**Backlog prerequisites already shipped:** BL-1028 (engagement timestamps in `email_send_log`)
**Success Criteria** (what must be TRUE):
  1. A CSV of EventFest bounces is generated by querying `email_send_log` joined with `campaign_recipients` and saved/delivered to LCC.
  2. CSV columns include: contact_id, email, first_name, last_name, company, bounce_type, bounced_at, error_message.
  3. The Campaigns page in the dashboard has an "Export bounces" button that downloads the same CSV shape for any selected campaign.
  4. Rows that originally failed with `daily_quota_exceeded` but eventually delivered (BL-1029 `superseded` flag) are excluded from the bounce list.
  5. Unit test covers the SQL join + filter logic.
**Plans:** TBD

Plans:
- [ ] 02-01: TBD — define during `/gsd-plan-phase 2`

---

### Phase 3: Unsubscribe Loop
**Goal:** Make unsubscribes a first-class state on contacts — track them, suppress future sends to unsubscribed contacts, and send a confirmation email to the unsubscriber.
**Executes in:** `/Users/michal/git/leadgen-pipeline`
**Depends on:** Nothing
**Parallel with:** Phase 5, Phase 8
**Backlog items:** BL-1105, BL-1103
**Backlog prerequisites already shipped:** BL-1028 (engagement timestamps in `email_send_log`)
**Success Criteria** (what must be TRUE):
  1. `contacts.mailing_status` column exists (`active | unsubscribed | bounced_hard | suppressed`), defaulting to `active`; `unsubscribed_at` + `unsubscribed_source` audit columns also present.
  2. Resend `email.unsubscribed` webhook flips `mailing_status='unsubscribed'` idempotently (earliest `unsubscribed_at` wins).
  3. `send_campaign_emails` worker skips contacts with `mailing_status != 'active'` and logs a `skipped_unsubscribed` row per skip in the campaign run summary.
  4. Unsubscribed contacts show an "Unsubscribed" badge + date in the dashboard.
  5. When a contact first unsubscribes, exactly one confirmation email is sent to them; on webhook replay, no duplicate email is sent (idempotent on `(recipient_email, unsubscribed_at_day)`).
  6. Confirmation email send failures do NOT block the unsubscribe state from being recorded.
**Plans:** TBD

Plans:
- [ ] 03-01: TBD — define during `/gsd-plan-phase 3`

---

### Phase 4: Tables Lazy-Load Bug Fix
**Goal:** Eliminate the duplicate-row and scroll-jump bugs on the Contacts (and Companies) tables reported during the 2026-05-11 client review.
**Executes in:** `/Users/michal/git/leadgen-pipeline` (frontend)
**Depends on:** Nothing
**Parallel with:** Phase 1, Phase 2
**Backlog items:** BL-1116
**Success Criteria** (what must be TRUE):
  1. After scrolling through three or more page boundaries on the Contacts table, no contact ID appears in the rendered DOM more than once.
  2. New pages append without visually shifting the scroll position of currently-visible rows.
  3. A Playwright spec (`tests/e2e/contacts-table-no-duplicates.spec.ts` or equivalent) asserts no duplicates after 5 scroll-to-bottom triggers against a >200-contact populated table.
  4. Navigation away from the table and back preserves scroll position (regression-safe).
  5. Same fix applied (or verified unnecessary) for the Companies table.
**Plans:** TBD

Plans:
- [ ] 04-01: TBD — define during `/gsd-plan-phase 4`

---

### Phase 5: Editable Contact Fields
**Goal:** Make core Contact + Company fields editable inline, audited, and RBAC-gated — foundational for the operator-driven DB cleanup the client asked for. Salutation lands as a first-class field as part of this work.
**Executes in:** `/Users/michal/git/leadgen-pipeline`
**Depends on:** Nothing
**Parallel with:** Phase 3, Phase 8
**Backlog items:** BL-1107, BL-1106
**Note:** Phase 5 is the foundation that later phases (Six, Seven, Nine, Ten) build upon.
**Success Criteria** (what must be TRUE):
  1. From either the Contact detail page or the Contacts table row, an admin/namespace_admin operator can inline-edit: `first_name`, `last_name`, `salutation`, `email` (with uniqueness check), `role`, `phone`, `language`, `notes`. From the Company side: `name`, `domain`, `category`, `notes`.
  2. Every edit lands as a PATCH on the API, validates server-side, and shows a "Saved" toast on success or an inline error on failure (e.g. duplicate email).
  3. An audit log (`audit_log` or `contact_edits` table) captures `(actor_user_id, contact_id, field, old_value, new_value, edited_at)` for every edit.
  4. Non-admin roles do NOT see edit affordances (RBAC enforced server-side).
  5. `contacts.salutation` column exists, backfilled via the Czech vocative function. The field is editable per the rules above; a `salutation_overridden_at` flag distinguishes auto-generated vs operator-curated values so a vocative-function fix never overwrites a manual edit.
  6. Email templates render `{{salutation}}` from `contacts.salutation` (not the live-vocative call).
**Plans:** TBD

Plans:
- [ ] 05-01: TBD — define during `/gsd-plan-phase 5`

---

### Phase 6: Company Categorization
**Goal:** Add the five-category enum the client asked for (B2B agency / B2C corporate / B2G public-org / cultural-referent / festival-organizer) plus a filter UI on the Companies table.
**Executes in:** `/Users/michal/git/leadgen-pipeline`
**Depends on:** Phase 5 (inline edit must exist before category is editable in-table)
**Parallel with:** None (gated on Phase 5)
**Backlog items:** BL-1108
**Success Criteria** (what must be TRUE):
  1. Migration creates `companies.category` enum with values `agency_b2b | corporate_b2c | public_org_b2g | cultural_referent | festival_organizer | uncategorized` (default `uncategorized`) plus optional `subcategory` free-text column.
  2. Operators can change a company's category from Company detail OR inline in the Companies table (via Phase 5 mechanics), with the change audited.
  3. Companies table supports filtering by category — filter state is URL-shareable.
  4. Joined Contacts table rows show the company's category as a colored chip.
  5. Audience-query builder (used by Phase 10) can filter by `category` value.
**Plans:** TBD

Plans:
- [ ] 06-01: TBD — define during `/gsd-plan-phase 6`

---

### Phase 7: Unique Catalog Tracking Links
**Goal:** One-click button per contact that generates a unique catalog URL (with-prices via existing partner-token, without-prices via new `?ref=` tracking_id) and fans every open back into leadgen's event store so we can answer "did this contact actually look?"
**Executes in:** BOTH `/Users/michal/git/leadgen-pipeline` AND `/Users/michal/git/ua-microsite` (coordinated PRs)
**Depends on:** Phase 5 (Contact detail page must exist as an interactive page first)
**Parallel with:** None (gated on Phase 5)
**Backlog items:** BL-1104
**Success Criteria** (what must be TRUE):
  1. Contact detail page (and Contacts table row) exposes "Copy catalog link (with prices)" and "Copy catalog link (no prices)" buttons. Each is idempotent — re-clicking returns the same URL.
  2. The with-prices URL reuses existing `Invites` partner-token mechanism; the without-prices URL is a public-catalog URL with `?ref={tracking_id}`.
  3. On either URL being opened, the ua-microsite emits an event to leadgen's `/api/tracking/microsite-event` ingest with `(contact_id, link_variant, opened_at)`.
  4. The leadgen ingest endpoint stores the events and exposes `last_opened_at` + open count per variant on the Contact row.
  5. Two PRs (one per repo) land in coordination — neither is merged until both pass review.
**Plans:** TBD

Plans:
- [ ] 07-01: TBD — define during `/gsd-plan-phase 7`

---

### Phase 8: Partner Admin Access
**Goal:** Add an authenticated `/cs/admin/partners` page on `booking.losers.cz` so LCC team members can see all partner invites with engagement at a glance.
**Executes in:** `/Users/michal/git/ua-microsite`
**Depends on:** Nothing (Payload admin scaffolding already exists)
**Parallel with:** Phase 3, Phase 5
**Backlog items:** BL-1115
**Success Criteria** (what must be TRUE):
  1. `/cs/admin/partners` route exists on the microsite, gated by Payload admin auth — non-admin users get 401 / Payload login redirect.
  2. The page lists all partner invites with partner name, contact email, invite token, created_at, last_opened_at, page_view_count.
  3. Clicking a partner row opens a detail page with the full timeline of microsite events for that partner.
  4. Leadgen-side engagement data (sends/opens/clicks/bounces/unsubscribes per contact) is fetched from leadgen's existing API and merged into the partner row.
  5. The page is reachable at `booking.losers.cz/cs/admin/partners` in production.
**Plans:** TBD

Plans:
- [ ] 08-01: TBD — define during `/gsd-plan-phase 8`

---

### Phase 9: Multilingual Mailing Foundation
**Goal:** Refactor template rendering to support CZ + EN variants per template; the worker picks the variant by `contact.language`.
**Executes in:** `/Users/michal/git/leadgen-pipeline`
**Depends on:** Phase 5 (language field needs to be editable + visible)
**Parallel with:** None (gated on Phase 5; gates Phase 10's DACH audience)
**Backlog items:** BL-1110
**Success Criteria** (what must be TRUE):
  1. `contacts.language` enum exists (`cs | en`) defaulting to `cs`, editable per Phase 5.
  2. Template renderer loads CZ and EN variants from a structured location (e.g. `{template}.cs.html` + `{template}.en.html`) — design choice documented in plan.
  3. `send_campaign_emails` worker reads `contact.language` and renders the matching variant.
  4. Campaign preview UI shows both variants side-by-side when both exist.
  5. EventFest template re-renders byte-identical in CZ (no regression on the production-tested path) — assert via snapshot test.
**Plans:** TBD

Plans:
- [ ] 09-01: TBD — define during `/gsd-plan-phase 9`

---

### Phase 10: Campaign Database Foundations
**Goal:** Prepare three audience-ready draft campaigns: CZ agencies (cold), autumn/winter cultural-event organizers, DACH event agencies. This phase preps the DB and creates draft `campaigns` rows — actual send is later.
**Executes in:** `/Users/michal/git/leadgen-pipeline`
**Depends on:** Phase 6 (need category), Phase 5 (need editable fields to fix gaps surfaced by readiness widget), Phase 9 (DACH audience needs EN bilingual support)
**Parallel with:** None
**Backlog items:** BL-1111, BL-1112, BL-1113
**Success Criteria** (what must be TRUE):
  1. Three saved audience queries exist:
     - CZ agencies cold: `category='agency_b2b' AND country='CZ' AND no prior outreach`
     - Autumn/winter cultural orgs: `category IN ('festival_organizer','public_org_b2g','cultural_referent','corporate_b2c')` with a `seasonal_focus` tag
     - DACH agencies: `category='agency_b2b' AND country IN ('DE','AT','CH')`
  2. A "Campaign readiness" widget on each draft campaign shows: total audience, contacts with email, contacts missing email/salutation/language, etc.
  3. "Enrich missing" button triggers the existing L1/L2/Person enrichment pipeline on the audience subset.
  4. For the DACH audience, a "bulk-set language=EN" admin tool exists (or per-contact via Phase 5).
  5. Three `campaigns` rows exist in `status='draft'` with `audience_query` + `recipient_count` populated, ready for copywriting + send in a future sprint.
  6. The `companies.country` dimension is verified to exist (or added in this phase) so the audience queries can run.
**Plans:** TBD

Plans:
- [ ] 10-01: TBD — define during `/gsd-plan-phase 10`

---

### Phase 11: Campaign Reach Reporting
**Goal:** Add the reach lens the client asked for — per-campaign sends/delivered/opened/clicked/bounced/unsubscribed/unique-reached counts plus a cross-campaign unique-reach widget for 30/60/90-day windows.
**Executes in:** `/Users/michal/git/leadgen-pipeline`
**Depends on:** Phase 6 (per-category breakdown needs `category` field). Phase 10 ideal but not strictly required (reach can render on existing campaigns).
**Parallel with:** None (last phase)
**Backlog items:** BL-1114
**Success Criteria** (what must be TRUE):
  1. On the existing Campaign Analytics page, a new "Reach" section shows per-campaign counts: sent / delivered / opened / clicked / bounced / unsubscribed / unique-reached.
  2. The analytics dashboard has a "Unique reach" widget showing distinct contacts touched in the last 30 / 60 / 90 days, broken down by company category (Phase 6).
  3. "Export PDF" button generates a one-page reach report for any campaign.
  4. For campaigns sent before the BL-1028 tracking fix, "delivered" falls back to `sent − bounced` with a clear caveat footnote in the UI.
  5. Unit test covers the unique-reach windowed query.
**Plans:** TBD

Plans:
- [ ] 11-01: TBD — define during `/gsd-plan-phase 11`

---

### Phase 12: Editable Company Name + Duplicate Detection
**Goal:** Let operators rename a company from two entry points — inline in the Companies table and from the Company detail page — with server-side duplicate detection after normalization (trim + lowercase + NFKD diacritic strip + Czech/DE/EN legal-suffix strip). On collision in the same tenant, prompt the user with a resolution modal offering per-match "Use this one" / "Merge into this one" and footer "Keep both as separate" / "Cancel". Merge re-points all FKs into the surviving record and hard-deletes the loser inside one Postgres transaction.
**Executes in:** `/Users/michal/git/leadgen-pipeline`
**Depends on:** None technically (the useInlineEdit hook already exists for contact email per the CONTEXT discovery — Phase 12 is independent of Phase 5).
**Parallel with:** Phases 5, 6, 9, 10, 11 (any wave)
**Backlog items:** BL-1117 (created during Plan 12-01)
**Success Criteria** (what must be TRUE):
  1. `companies.normalized_name TEXT` column exists with a non-unique index on `(tenant_id, normalized_name)`; backfill populates every non-NULL `name` row.
  2. `api/services/name_normalize.py` exports `normalize_company_name()`, a pure function unit-tested against CZ legal suffixes (s.r.o., a.s., spol. s r.o., v.o.s., k.s.), DE (GmbH, AG, mbH, KG), EN (Ltd, LLC, Inc, Corp, Co, Company), diacritics, punctuation, and mid-string-suffix non-stripping.
  3. PATCH `/api/companies/<id>` returns 409 with `{code:"duplicate_company_name", matches:[...]}` when the new name collides with an existing same-tenant company. `?confirm_duplicate=keep_both` overrides and writes an annotated audit row.
  4. POST `/api/companies/<id>/merge?into=<surviving_id>` re-points 14 FK tables in one transaction with `SELECT ... FOR UPDATE` locking; writes one audit row with a JSON snapshot of the deleted row; hard-deletes the duplicate.
  5. Companies table renders an inline-editable name column by default (`name_edit` flipped on); the read-only `name` column is hidden by default.
  6. CompanyDetail.tsx renders the company name header as an `EditableText` component (Esc cancels, Enter saves).
  7. `DuplicateCompanyModal` opens on 409 from either entry point and offers all 4 actions; default focus is "Use this one" of the first match; ESC cancels.
  8. Tenant isolation enforced: a collision in tenant B never triggers a 409 for tenant A.
  9. Manual sprint test script `docs/testing/sprint-25-manual-tests.md` Phase 12 section (T12.1..T12.10) all PASS on staging root before BL-1117 → Done.
**Plans:** 9 plans (12-01..12-09), 7 waves.

Plans:
- [ ] 12-01: Setup + Backlog + Spec doc — claim BL-1117, create worktree off staging, write `docs/specs/editable-company-name.md`
- [ ] 12-02: Backend foundation — migrations 073 + 074, `name_normalize.py`, `find_name_collisions`, backfill script
- [ ] 12-03: PATCH duplicate gate — extend update_company() with 409 + keep-both flow
- [ ] 12-04: Merge endpoint — POST /api/companies/<id>/merge with transactional FK re-pointing across 14 tables
- [ ] 12-05: Inline-edit on Companies table — flip name_edit column on; useInlineEdit recognizes new 409; useCompanyDuplicateGate hook
- [ ] 12-06: Detail-page edit — EditableText component on CompanyDetail header
- [ ] 12-07: DuplicateCompanyModal — full UI with merge / use existing / keep both / cancel
- [ ] 12-08: Tests + manual sprint script — full-flow integration + Playwright + T12.1..T12.10
- [ ] 12-09: PR + staging validation — PR to staging, migration dispatch, human sign-off, BL-1117 → Done

---

## Progress

**Execution Order:**
Phases execute in numeric order with parallelism per the Wave plan above. Lead agent decides when to start each wave based on agent availability and parallel-worktree slots.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Microsite Quick Fixes | 0/1 | Not started | - |
| 2. Eventfest Bounces Export | 0/1 | Not started | - |
| 3. Unsubscribe Loop | 0/1 | Not started | - |
| 4. Tables Lazy-Load Bug Fix | 0/1 | Not started | - |
| 5. Editable Contact Fields | 0/1 | Not started | - |
| 6. Company Categorization | 0/1 | Not started | - |
| 7. Unique Catalog Tracking Links | 0/1 | Not started | - |
| 8. Partner Admin Access | 0/1 | Not started | - |
| 9. Multilingual Mailing Foundation | 0/1 | Not started | - |
| 10. Campaign Database Foundations | 0/1 | Not started | - |
| 11. Campaign Reach Reporting | 0/1 | Not started | - |
| 12. Editable Company Name + Duplicate Detection | 0/9 | Planned (2026-05-14) | - |

## Backlog ↔ Phase Coverage

18 backlog items → 12 phases. BL-1100 is an audit-trail entry (already Done) and is not mapped to a phase. BL-1117 was added 2026-05-14 for Phase 12.

| Phase | Backlog items |
|-------|---------------|
| 1 | BL-1101, BL-1109 |
| 2 | BL-1102 |
| 3 | BL-1103, BL-1105 |
| 4 | BL-1116 |
| 5 | BL-1106, BL-1107 |
| 6 | BL-1108 |
| 7 | BL-1104 |
| 8 | BL-1115 |
| 9 | BL-1110 |
| 10 | BL-1111, BL-1112, BL-1113 |
| 11 | BL-1114 |
| 12 | BL-1117 (created during Plan 12-01) |

No orphans. No duplicates. Mapping is also stored in the backlog service under directive `gsd-phase-mapping` for runtime discovery.

---
*Created: 2026-05-11 during GSD bootstrap for Milestone v25 (LCC Client Requests). Phase 12 added 2026-05-14 — finalized via `/gsd-plan-phase 12` with 9 plans across 7 waves.*
