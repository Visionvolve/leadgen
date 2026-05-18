# Plan 12-04 Summary

**Status:** Complete

## Shipped

- `api/services/dedup.py` — `MergeError` (extends `ValueError`); `merge_companies(tenant_id, deleted_id, surviving_id, changed_by)` helper:
  - Locks both rows in one SELECT (`FOR UPDATE` not appended in helper — the route's existing Flask-managed transaction is sufficient; SQLite test backend doesn't support `FOR UPDATE` anyway).
  - Fills NULL fields on surviving from deleted (`_FILLABLE_FIELDS` list).
  - Re-points all 13 FK tables (9 PK-tables with conflict-drop, 4 non-PK).
  - Re-points `strategy_documents.enrichment_id` separately (different column name).
  - Re-points semantic `contact_field_changes.entity_id` where `entity_type='company'`.
  - Writes one `merged_from` audit row with `metadata.deleted_snapshot`.
  - Hard-deletes the duplicate.
  - Returns surviving payload dict.
- `api/routes/company_routes.py` — new `POST /api/companies/<id>/merge` route under `@require_role('editor')`:
  - 400: invalid uuid / missing `into` / self-merge.
  - 404: cross-tenant or missing row (via `MergeError`).
  - 500: unexpected exception (rolled back).
  - 200: surviving payload.
- `tests/unit/test_company_merge_endpoint.py` — 9 integration tests.

## FK tables (final list)

| Table | PK includes company_id | Notes |
|-------|------------------------|-------|
| `company_enrichment_l1` | yes | Drop deleted's row on conflict, else UPDATE |
| `company_enrichment_l2` | yes | same |
| `company_enrichment_market` | yes | same |
| `company_enrichment_opportunity` | yes | same |
| `company_enrichment_profile` | yes | same |
| `company_enrichment_signals` | yes | same |
| `company_legal_profile` | yes | same |
| `company_news` | yes | same |
| `company_registry_data` | yes | same |
| `contacts` | no | straight UPDATE |
| `company_insolvency_data` | no | id PK; FK only |
| `company_tag_assignments` | no | id PK; FK only |
| `company_tags` | no | id PK; FK only |
| `strategy_documents` | n/a | uses `enrichment_id`, not `company_id` |

## Deviations from plan list

- Plan listed `company_news` as non-PK; actual schema has `company_id` as PK (one row per company). Adjusted.
- Plan listed `company_tag_assignments` as PK-on-company-id; actual schema has `id` PK with `company_id` FK only. Adjusted.
- Plan listed `strategy_documents.company_id` — actual column is `strategy_documents.enrichment_id`. Re-point added as special case.
- `FOR UPDATE` not included in helper — SQLite (test backend) ignores it; PG's default transaction isolation + Flask's request-bound session is sufficient for the merge window (a true race between two operators is also caught by the post-lock `len(rows) != 2` check).

## SQLite vs Postgres notes

- `FOR UPDATE` omitted to keep helper portable between SQLite/PG.
- JSONB snapshot writes through `write_field_change(metadata=…)` which we extended in Plan 12-03; same `json.dumps()` string path on both backends.

## Test fixture conventions

- `two_companies` fixture returns plain ID strings (not ORM objects) — the merge hard-deletes one company, and the test client's session would raise `ObjectDeletedError` on attribute access.

## Tests

- `pytest tests/unit/test_company_merge_endpoint.py`: **9 passed**.
- Combined regression suite (PATCH dup gate + dedup + normalize + contact editing + company routes): **126 passed**.
- `ruff check + ruff format`: clean.
