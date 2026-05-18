# Plan 12-02 Summary

**Status:** Complete

## Shipped

- `migrations/073_companies_normalized_name.sql` — `companies.normalized_name TEXT` + non-unique `idx_companies_tenant_normalized_name (tenant_id, normalized_name)`. Idempotent.
- `migrations/074_contact_field_changes_metadata.sql` — `contact_field_changes.metadata JSONB DEFAULT '{}'::jsonb`. Idempotent.
- `api/services/name_normalize.py` — `normalize_company_name()` + `LEGAL_SUFFIXES`. SQLAlchemy `before_insert`/`before_update` listener registered at app bootstrap.
- `api/services/dedup.py` — `find_name_collisions(tenant_id, normalized_name, exclude_id=None)`.
- `api/models.py` — `Company.normalized_name`; `ContactFieldChange.metadata_json` (attr name, DB column `metadata`).
- `api/__init__.py` — `register_listeners()` wired into `create_app`.
- `scripts/backfill_normalized_name.py` — idempotent batched backfill.
- Tests: `test_name_normalize.py` (43 cases), `test_dedup_name_collisions.py` (9 cases).

## LEGAL_SUFFIXES list (canonical order, longest-first)

```
spol s r o, spol s ro, s r o, sro, v o s, vos, k s, ks,
company, limited, gmbh, mbh, ltd, corp, llc, inc,
co, a s, as, ag, kg
```

Downstream PATCH/merge tests should assume this exact list.

## Raw-SQL writers patched

None enumerated yet. The existing PATCH handler uses raw `UPDATE companies SET …` (see `api/routes/company_routes.py` lines 1228+); Plan 12-03 explicitly adds `normalized_name = :normalized_name` to that UPDATE when `name` changes. ORM listener catches every other path. No `INSERT INTO companies` raw SQL was found in `api/` or `scripts/` (only ORM-based creates).

## "Last activity" column used

`Contact.updated_at` — matches plan recommendation. `Contact.last_collaboration_at` is more semantically accurate but is NULL for most contacts (only UA campaign features populate it).

## Local PG backfill

Not run — no local PG available in this session. Staging migration + backfill is scheduled in Plan 12-09 Task 4 (post-merge GHA dispatch).

## SQLite vs Postgres notes

- The JSONB `metadata` column lands as TEXT in the SQLite test backend per the existing `_patch_pg_types_for_sqlite` shim in `tests/conftest.py` — no changes needed.
- `Company` and `Owner` outerjoin in `find_name_collisions` exercised under SQLite in the new tests and passes.

## Tests

- `pytest tests/unit/test_name_normalize.py tests/unit/test_dedup_name_collisions.py`: **52 passed**.
- `pytest tests/unit/test_dedup.py` (regression): **31 passed** — no regression in existing dedup tests.
- `ruff check + ruff format --check` on all changed files: clean.
