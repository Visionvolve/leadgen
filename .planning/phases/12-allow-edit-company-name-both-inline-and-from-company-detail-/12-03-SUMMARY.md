# Plan 12-03 Summary

**Status:** Complete

## Shipped

- `api/services/contact_helpers.py` — `write_field_change` now accepts `metadata: dict | None = None`. JSON-encoded via `json.dumps` and passed as a string in both Postgres (auto-cast to JSONB) and SQLite (TEXT column). Default `{}` matches the migration default.
- `api/routes/company_routes.py` (`update_company` PATCH handler):
  - Imported `normalize_company_name` and `find_name_collisions`.
  - Duplicate gate inserted AFTER enum validation, BEFORE the existing SELECT.
  - Empty-after-normalize returns 400 (codes `empty_name` or `empty_name_after_normalize`).
  - Collision returns 409 with `code='duplicate_company_name'` + `matches[]`.
  - `?confirm_duplicate=keep_both` skips the gate.
  - The existing UPDATE SQL now also writes `normalized_name = :normalized_name` when `name` is in the payload (raw-SQL writer, ORM listener does NOT fire).
  - Audit row for `name` gets `metadata={"note":"duplicate_kept_intentionally", "normalized_name":...}` when keep_both is used.
- `tests/unit/test_company_patch_duplicate_gate.py` — 6 integration cases (clean rename, empty-after-normalize, collision 409, keep_both 200+audit metadata, cross-tenant isolation, mass-assignment guard).

## Diff insertion point

Inside `update_company` (`api/routes/company_routes.py`):
- Gate block inserted between the enum-validation loop (ends ~L1334) and the existing tenant SELECT (~L1357).
- UPDATE SQL extended with `normalized_name = :normalized_name` set-part inside the existing set_parts loop.
- Audit loop extended to pass `metadata` when keep_both + name field.

## SQLite vs Postgres compat tweaks

- The JSONB column maps to TEXT in `_patch_pg_types_for_sqlite`. We pass `json.dumps(metadata or {})` as a string in both backends — Postgres auto-casts the string literal to JSONB on insert; SQLite stores it as text and the test reads it back with `json.loads`. No dialect-aware branching needed.

## Test fixture conventions used

- `seed_companies_contacts` fixture from `tests/conftest.py` supplies Acme Corp (normalized `acme`), Beta Inc (normalized `beta`), Gamma LLC, Delta GmbH, Epsilon SA across one tenant `Test Corp` (slug `test-corp`).
- `auth_header(client)` returns an HS256 test token for admin@test.com; `X-Namespace: test-corp` resolves the tenant.
- For the cross-tenant test, a second tenant + editor user is created inline (the seed only has one tenant).

## Tests

- `pytest tests/unit/test_company_patch_duplicate_gate.py`: **6 passed**.
- `pytest tests/unit/test_company_routes.py test_company_org_type.py test_company_detail_fields.py`: **37 passed** (no regression).
- `pytest tests/unit/test_contact_editing.py`: **13 passed** (no regression — write_field_change kwarg addition is backward compatible).
- `ruff check` + `ruff format --check`: clean.
