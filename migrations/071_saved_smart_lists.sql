-- Migration 070: Saved smart lists — campaign-prep audience query primitive.
--
-- Source: BL-1111 / BL-1112 / BL-1113 (LCC client asks #12/#13/#14, v25 Phase 10).
--
-- A smart list is a tenant-scoped, named JSON filter spec over either the
-- contacts or companies table. Operators define filters once (e.g. "CZ B2B
-- agencies that are cold"), then re-run on demand to refresh the matching
-- result set — the foundation for picking campaign audiences without writing
-- ad-hoc SQL.
--
-- The ``filters`` column is a free-form JSONB document interpreted by the
-- ``api/routes/smart_list_routes.py`` run handler. Filter keys match the
-- existing list endpoints (``/api/companies`` and ``/api/contacts``) so a
-- saved list and a manual filter on the corresponding list page produce
-- identical results.
--
-- Tenant + name is unique so operators can re-create deterministic lists
-- without worrying about duplicates.

CREATE TABLE IF NOT EXISTS smart_lists (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    target TEXT NOT NULL CHECK (target IN ('contact', 'company')),
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_run_at TIMESTAMPTZ,
    last_run_count INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_smart_lists_tenant_name
    ON smart_lists(tenant_id, LOWER(name));

CREATE INDEX IF NOT EXISTS idx_smart_lists_tenant
    ON smart_lists(tenant_id);
