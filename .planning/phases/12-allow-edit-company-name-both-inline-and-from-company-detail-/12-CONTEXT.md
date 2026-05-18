# Phase 12: Editable Company Name + Duplicate Detection — Context

**Gathered:** 2026-05-14
**Status:** Ready for planning
**Source:** Auto-decided (user requested "full auto to prod") with codebase-grounded defaults

<domain>
## Phase Boundary

Let users edit a company's `name` field from two entry points — **inline in the Companies table** and from the **Company detail page** — with server-side duplicate detection after normalization. If a save would create a same-tenant duplicate (after trim + lowercase + diacritic-strip + legal-suffix-strip), the user is prompted to **merge**, **use the existing one**, **keep both**, or **cancel**.

In scope: name editing, normalization, server-side duplicate detection, conflict resolution prompt, merge engine, audit trail, staging validation, production deploy.

Out of scope (deferred): bulk-merge UI; fuzzy/trigram matching; auto-detect duplicates on company **create** (POST /api/companies); applying same flow to contact names; surfacing existing in-tenant duplicates retroactively as a forced cleanup task; merge-direction choice (we always merge edited record INTO the existing match — user can rename the survivor afterward).

</domain>

<decisions>
## Implementation Decisions

### Edit affordance (frontend)
- **Inline edit** uses the existing `useInlineEdit` hook from `frontend/src/hooks/useInlineEdit.ts` (the same hook that powers contact email inline edit with its 409-conflict gate).
- **`name_edit` column** in `frontend/src/config/companyColumns.tsx` is already defined (line ~51, `defaultVisible: false`). Flip `defaultVisible: true` and wire `editable: true` to use the hook.
- The plain **`name`** column stays read-only (click → navigate to detail). The new visible column is **`name_edit`** showing the same value but with text-input affordance and a pencil/save state per `useInlineEdit`.
- **Detail page (`CompanyDetail.tsx`)** adds an `EditableText` (analog to existing `EditableSelect`/`EditableTextarea`) wrapping the company name header. Same `useUpdateCompany()` mutation; same 409 handling.

### Normalization rules (server, canonical)
- New helper: `api/services/name_normalize.py` exporting `normalize_company_name(s: str) -> str`.
- Steps in order:
  1. Strip leading/trailing whitespace; collapse internal whitespace runs to one space.
  2. Lowercase.
  3. NFKD-normalize and remove combining marks (`unicodedata.normalize('NFKD', s)` → filter `category(ch) == 'Mn'`).
  4. Remove punctuation: `, . & ( ) ' " / \` and replace `-` and `_` with a single space.
  5. Strip common legal suffixes (case-insensitive, with optional dots/spaces): `s.r.o`, `sro`, `a.s`, `as`, `spol s r o`, `v.o.s`, `vos`, `k.s`, `ks`, `gmbh`, `ag`, `mbh`, `kg`, `ltd`, `limited`, `llc`, `inc`, `corp`, `co`, `company`. Strip these as **standalone trailing tokens** only — never mid-name.
  6. Collapse whitespace runs again; trim.
- Empty result rejects the save (400 — name cannot be empty after normalization).
- Exact-match-after-normalization only. **No fuzzy/trigram matching in v1** (deferred).

### Storage and indexing
- Add column `normalized_name TEXT` on `companies`.
- Add index `idx_companies_tenant_normalized_name ON companies (tenant_id, normalized_name)` — **non-unique** (we allow user to keep both intentionally; uniqueness is enforced by the prompt, not the DB).
- App writes `normalized_name` on insert and on every name update (single source of truth lives in `normalize_company_name`).
- One-time **backfill migration**: SQL migration creates column + index; a Python migration script (or backfill block in the migration) computes normalized_name for every existing row in batches.

### Duplicate check (server)
- New helper in `api/services/dedup.py`: `find_name_collisions(tenant_id, normalized_name, exclude_id=None) -> list[CompanySummary]`. Returns 0..N matches scoped to the tenant, excluding `exclude_id` (the company being edited).
- PATCH `/api/companies/<id>` (existing): when the incoming payload changes `name`:
  1. Compute `new_normalized = normalize_company_name(payload.name)`. Reject if empty.
  2. Call `find_name_collisions(tenant_id, new_normalized, exclude_id=id)`.
  3. If matches exist AND request lacks `?confirm_duplicate=keep_both`: respond **409** with body `{ "code": "duplicate_company_name", "matches": [...] }`. Each match summary includes `id, name, domain, status, owner, contact_count, last_activity_at`.
  4. If `?confirm_duplicate=keep_both` is present: skip the check, proceed with PATCH, log audit row with note `duplicate_kept_intentionally`.

### Conflict resolution UX
- On 409, frontend opens a `DuplicateCompanyModal` listing all `matches` (one row per match: name, domain, owner avatar, status pill, contact count, last activity).
- Per-match buttons: **"Use this one"** (close the edit, navigate to `/companies/{match.id}`, discard the rename), **"Merge into this one"** (call merge endpoint — see below).
- Modal footer: **"Keep both as separate"** (re-PATCH with `?confirm_duplicate=keep_both`), **"Cancel"** (revert the input to pre-edit value, no API call).
- Default focus: "Use this one" on the first / highest-confidence match (most contacts).

### Merge engine (server)
- New endpoint: `POST /api/companies/<id>/merge?into=<surviving_id>` (RBAC: editor + same tenant).
- Wrapped in a single Postgres transaction:
  1. Verify both companies belong to `tenant_id`. Reject otherwise.
  2. Surviving record's non-null fields **win**; the edited record's fields fill **only NULL slots** on the surviving record (reuse the `dedup.update_empty_fields` pattern).
  3. Re-point all FKs to the deleted company's id: `contacts.company_id`, `email_send_log.company_id` (if present), `enrichment_l1.company_id`, `enrichment_l2.company_id`, `company_tags.company_id`, `contact_field_changes.entity_id WHERE entity_type='company'`, and any other `company_id` FK present in current schema.
  4. Write a single audit row in `contact_field_changes` with `entity_type='company'`, `entity_id=surviving.id`, `field_name='merged_from'`, `old_value=<deleted.id>`, `new_value=<surviving.id>`, plus a JSON snapshot of the deleted row stored in a `metadata` JSONB column (add to the audit table via migration if not present).
  5. **Hard-delete** the duplicate row.
  6. Return surviving company payload.
- Owner: surviving record's `owner_id` is preserved as-is; the modal warns when owners differ so the user knows before clicking Merge.
- If FK re-pointing fails for any reason → rollback the entire transaction.

### Validation & deploy
- Staging deploy via `staging` branch merge (auto-deploys via GHA).
- Sprint QA agent runs the sprint test script after merge.
- User signs off on staging root.
- PR from `staging` → `main`; merge triggers production GHA workflow.
- Per project rules: Claude does NOT run `deploy/deploy-*.sh` directly.

### Backlog mapping
- No existing BL-#### maps to Phase 12 in `gsd-phase-mapping` directive (phase was added post-bootstrap). A new backlog item should be created before execution starts. Suggested: **`BL-1117 — Editable company name + duplicate detection`** in `Sprint 25 — LCC client requests`.

### Claude's discretion (implementation defaults)
- React component: build a generic `DuplicateConflictModal` parameterized by entity type so future entities (contacts, owners) can reuse.
- Server: keep `normalize_company_name` pure and unit-tested in isolation.
- Migration: split into two — one for `normalized_name` column + index + backfill; a separate one for the audit `metadata` JSONB column (if not already present).
- Tests: unit tests for `normalize_company_name` (CZ legal-suffix variants, diacritics, edge cases); integration test for PATCH-409 flow; integration test for merge endpoint including FK re-pointing for at least contacts + tags.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & scope
- `.planning/ROADMAP.md` — Phase 12 entry (line ~301), milestone v25 framing
- `.planning/PROJECT.md` — multi-tenant architecture, north-star checks, deploy model
- `.planning/STATE.md` — current milestone position

### Backend code to reuse / extend
- `api/models.py` (Company at lines 144–217) — schema reference; do NOT add unique constraint on (tenant_id, name)
- `api/routes/company_routes.py` (PATCH at lines 1228–1414; GET at 232–564) — endpoint to extend with duplicate check
- `api/services/dedup.py` (lines 21–108, 270–478) — extend with `find_name_collisions`; mirror `normalize_domain` style for `normalize_company_name`
- `api/services/phone_normalize.py` — pattern to mirror for `name_normalize.py`
- `api/auth.py` (`resolve_tenant`, lines 127–145; `@require_auth`, `@require_role`) — tenant-scoping pattern
- `api/services/contact_helpers.py` (`write_field_change`, lines 49–97) — audit-log pattern

### Frontend code to reuse / extend
- `frontend/src/hooks/useInlineEdit.ts` (409 duplicate-email gate at lines 59–83) — copy the gate pattern for company name
- `frontend/src/config/companyColumns.tsx` (dormant `name_edit` column at lines 51–59) — flip on
- `frontend/src/pages/companies/CompanyDetail.tsx` (existing `EditableSelect`/`EditableTextarea` at lines 163–200; `useUpdateCompany` at line 32) — add `EditableText` for the name header

### Migration prior art
- `migrations/066_contact_field_changes_audit.sql` — audit-table schema to extend (may need `metadata JSONB` column added)
- `migrations/001_initial_schema.sql` through `migrations/071_saved_smart_lists.sql` — naming/style convention

### Project rules (mandatory)
- `CLAUDE.md` (root of this repo) — branch model, deploy bans, agent-claim flow, definition of done
- `CLAUDE.md` "Pre-PR Quality Gates" section
- `docs/specs/` — drop the Phase 12 spec here (e.g., `docs/specs/editable-company-name.md`)

</canonical_refs>

<code_context>
## Reusable Assets and Patterns

- **Inline-edit hook** (`useInlineEdit`) already handles the per-cell save state machine + 409-conflict modal precedent (email duplicates on contacts). The hook needs no new methods — only a new 409 `code` recognizer for `"duplicate_company_name"`.
- **Dormant column** `name_edit` is in place — minimal frontend edit. The "discovery delta" is a single config change (`defaultVisible: true`) plus the modal.
- **`dedup.find_existing_company`** scoped by `tenant_id` already exists — Phase 12 adds a peer function `find_name_collisions` that takes a pre-normalized name and an `exclude_id`.
- **Audit logging** already wires per-field changes on company PATCH via `write_field_change`. Merge needs a single extra row with `field_name='merged_from'` plus a metadata snapshot.
- **No `unaccent` extension** in Postgres → diacritic stripping happens in Python (`unicodedata.normalize('NFKD', …)`). The index is over the application-computed `normalized_name`, not a postgres function — keeps it portable.

## Integration Points

- Companies table (`CompaniesPage` / `companyColumns.tsx`) — flip column + render modal on 409.
- Company detail (`CompanyDetail.tsx`) — `EditableText` on the header.
- Companies router (`api/routes/company_routes.py`) — extend PATCH; add merge endpoint.
- Migrations dir — add `072_companies_normalized_name.sql` (and possibly `073_company_audit_metadata.sql`).
- Sprint test script (`docs/testing/sprint-25-manual-tests.md`) — add Phase 12 acceptance steps.

</code_context>

<specifics>
## Specific References

- Phase 12 is for **leadgen-pipeline only** (executes in `/Users/michal/git/leadgen-pipeline`). Not cross-repo.
- Roadmap lists Phase 12 with `Depends on: Phase 11` — that is incidental ordering, not a true technical dependency. The real dependency is the inline-edit hook, which **already exists** in `useInlineEdit.ts` (built for contact email duplicates), so Phase 12 can be planned and executed independently of Phases 5, 6, 11.
- The dormant `name_edit` column with `editable: true, editField: 'name'` proves prior intent to ship this exact feature — Phase 12 is the activation.
- Czech market is primary (LCC tenant); legal suffix stripping (`s.r.o.`, `a.s.`, etc.) is **load-bearing** for real-world duplicate detection.

</specifics>

<deferred>
## Deferred Ideas

- **Fuzzy / trigram matching** — if exact-after-normalize misses too many real duplicates after one sprint of production use, add `pg_trgm` extension and a similarity-score fallback. Track as a follow-up backlog item.
- **Apply same flow to company create (POST /api/companies)** — currently Phase 12 only intercepts the edit path. Create-time dedup is already partly covered by `find_existing_company` (domain + name LIKE), but it should also use the new normalization pipeline. Note for next sprint.
- **Apply same flow to contact full-name editing** — different domain entirely (contacts have email/linkedin/phone as stronger keys); revisit only if false-positive contact duplicates become a complaint.
- **Bulk merge UI / "find all dupes" report** — show all in-tenant `normalized_name` groups with > 1 row, let user merge in a queue. Useful but not required for Phase 12.
- **Choose merge direction** — current design always merges edited → existing. If users complain they want to keep the edited record as the survivor, add a "switch direction" toggle inside the merge modal.
- **Co-locate edited+existing comparison view** — side-by-side diff before merge ("which fields will change?"). Adds clarity but doubles the modal size; skip for v1.

</deferred>

---

*Phase: 12-allow-edit-company-name-both-inline-and-from-company-detail-*
*Context gathered: 2026-05-14 via auto-decided defaults (user requested "full auto to prod")*
