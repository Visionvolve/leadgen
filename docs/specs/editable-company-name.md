# Editable Company Name + Duplicate Detection

## Backlog

- **Short ID:** BL-1203 (originally planned as BL-1117 but that ID was already taken by a different bug item in another sprint)
- **Sprint:** Sprint 25 — LCC client requests
- **Dashboard:** <https://backlog.visionvolve.com/leadgen-pipeline/>
- **GSD phase:** `12-allow-edit-company-name-both-inline-and-from-company-detail-`
- **Branch:** `feature/bl1117-editable-company-name` (slug retained for plan compatibility)

## Problem

Company-name typos and inconsistent legal-suffix capitalization mean duplicates accumulate in the LCC tenant (and any other tenant that imports from multiple sources). Today operators cannot fix a name from the Companies table or from the company detail page because no inline-edit affordance exists — the read-only `name` column links to the detail page, and the detail page renders the name as static text. Operators currently work around this by exporting CSV, fixing names manually, and re-importing, which is slow and error-prone.

## User Stories

- As an operator, I can rename a company from the Companies table without leaving the page.
- As an operator, I can rename a company from its detail page header.
- As an operator, when I save a name that already exists in my tenant (after server-side normalization), I am prompted with the matching companies and four explicit choices: merge into one, use the existing one, keep both intentionally, or cancel.
- As an operator, I never see another tenant's companies in the duplicate-match list, even if the names normalize identically.

## Acceptance Criteria

- **AC-1** Given a company "Foo Bar s.r.o." exists in tenant T,
       When an operator renames "Foo Bar" to "Foo Bar s.r.o." in tenant T,
       Then PATCH returns 409 with body `{code:"duplicate_company_name", matches:[{id,name,domain,status,owner,contact_count,last_activity_at}]}`.
- **AC-2** Given the 409 prompt is shown,
       When the operator clicks "Use this one" on a match,
       Then the modal closes, the input reverts to its pre-edit value, and the page navigates to `/companies/{match.id}`.
- **AC-3** Given the 409 prompt is shown,
       When the operator clicks "Merge into this one",
       Then `POST /api/companies/{edited.id}/merge?into={match.id}` executes; on success the user lands on the surviving record's detail page and the edited record is hard-deleted.
- **AC-4** Given the 409 prompt is shown,
       When the operator clicks "Keep both as separate",
       Then PATCH is retried with `?confirm_duplicate=keep_both` and succeeds; an audit row with `field_name='name'` and metadata note `duplicate_kept_intentionally` is written.
- **AC-5** Given a name normalizes to empty,
       When the operator submits,
       Then PATCH returns 400 with an empty-name error and no DB write happens.
- **AC-6** Given two tenants T1 and T2 each have a company "Acme s.r.o.",
       When an operator in T1 renames an unrelated company to "Acme s.r.o.",
       Then only T1's existing Acme appears as a match (cross-tenant isolation).
- **AC-7** Given a merge succeeds,
       When you query the surviving company,
       Then every contact / company_tags / enrichment_l1 / enrichment_l2 / company_tag_assignments / company_enrichment_market / company_enrichment_opportunity / company_enrichment_profile / company_enrichment_signals / company_legal_profile / company_news / company_registry_data / company_insolvency_data / strategy_documents row that pointed at the deleted company now points at the surviving company.

## Data Model Changes

- `companies.normalized_name TEXT NULL` — app-computed via `api.services.name_normalize.normalize_company_name`.
- Index `idx_companies_tenant_normalized_name` on `(tenant_id, normalized_name)` — **NON-UNIQUE** (the "keep both" path requires duplicates to coexist).
- `contact_field_changes.metadata JSONB DEFAULT '{}'::jsonb` — added if not already present. Used by the merge endpoint to store a JSON snapshot of the deleted row, and by the "keep both" path to flag `duplicate_kept_intentionally`.

## API Contracts

### PATCH /api/companies/{id} (existing — extended)

- Body: `{ name?: string, ... }` (other fields unchanged)
- Query: `?confirm_duplicate=keep_both` (optional, only meaningful when `name` changes)
- **200** on success
- **400** on empty-after-normalize (codes: `empty_name`, `empty_name_after_normalize`)
- **404** on cross-tenant company id
- **409** on collision when `confirm_duplicate` is not set:
  ```json
  {
    "code": "duplicate_company_name",
    "error": "A company with this normalized name already exists in this tenant.",
    "matches": [
      {
        "id": "uuid",
        "name": "string",
        "domain": "string|null",
        "status": "string|null",
        "owner": {"id": "uuid", "name": "string"} | null,
        "contact_count": 0,
        "last_activity_at": "iso8601|null"
      }
    ]
  }
  ```

### POST /api/companies/{id}/merge?into={surviving_id} (NEW)

- RBAC: editor; both companies must be in the caller's tenant.
- **200**: returns the surviving company payload (same shape as `GET /api/companies/{id}`).
- **400**: invalid uuid OR `id == into` OR missing `into` query param.
- **404**: either id missing in caller's tenant (avoids existence leak).
- Wrapped in a single Postgres transaction with `SELECT ... FOR UPDATE`. On any FK re-point failure, the entire transaction rolls back.

## Modal Wireframe

```
┌──────────────────────────────────────────────────────────┐
│ Company name already exists                              │
│ We found N companies with normalized name "{norm}".      │
│                                                          │
│ ┌─ {match.name}  ({domain})  ────────────────────────┐  │
│ │  Owner: 🟢 {owner_name}   Status: {status}         │  │
│ │  {contact_count} contacts · Last active {date}     │  │
│ │  [Use this one]              [Merge into this one] │  │
│ └────────────────────────────────────────────────────┘  │
│                ... one card per match ...                │
│                                                          │
│           [Keep both as separate]   [Cancel]             │
└──────────────────────────────────────────────────────────┘
```

Behavior:
- Default focus: "Use this one" on the first match (highest contact count when matches are pre-sorted by the API).
- Esc and overlay click trigger Cancel.
- If a match's `owner.id` differs from the edited company's `owner_id`, a yellow warning appears on that card ("Owner differs — after merge, this company will belong to {owner_name}.").

## Out of Scope (Deferred)

- **Fuzzy / trigram matching** — if exact-after-normalize misses too many real duplicates after one sprint of production use, add `pg_trgm` extension and a similarity-score fallback. Track as a follow-up backlog item.
- **Apply same flow to company create (`POST /api/companies`)** — currently Phase 12 only intercepts the edit path. Create-time dedup is already partly covered by `find_existing_company` (domain + name LIKE) but it should also use the new normalization pipeline. Note for next sprint.
- **Apply same flow to contact full-name editing** — different domain entirely (contacts have email/linkedin/phone as stronger keys); revisit only if false-positive contact duplicates become a complaint.
- **Bulk merge UI / "find all dupes" report** — show all in-tenant `normalized_name` groups with > 1 row, let user merge in a queue. Useful but not required for Phase 12.
- **Choose merge direction** — current design always merges edited → existing. If users complain they want to keep the edited record as the survivor, add a "switch direction" toggle inside the merge modal.
- **Co-locate edited+existing comparison view** — side-by-side diff before merge ("which fields will change?"). Adds clarity but doubles the modal size; skip for v1.

## Test Plan

- Unit tests: `tests/unit/test_name_normalize.py` (CZ/DE/EN suffix + diacritic edge cases); `tests/unit/test_dedup_name_collisions.py` (tenant scoping + exclude_id).
- Integration tests: `tests/unit/test_company_patch_duplicate_gate.py` (5 PATCH scenarios), `tests/unit/test_company_merge_endpoint.py` (9 merge scenarios), `tests/unit/test_company_duplicate_full_flow.py` (composed PATCH-409 → merge → survival).
- Frontend component test: `frontend/tests/components/DuplicateCompanyModal.test.tsx` (8 interaction cases).
- E2E (Playwright, queued for sprint-completion run): `frontend/tests/e2e/company-duplicate-merge.spec.ts`.
- Manual test script for the LCC sign-off run: `docs/testing/sprint-25-manual-tests.md` Phase 12 section (T12.1..T12.10).
