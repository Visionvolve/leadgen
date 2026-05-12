-- Migration 068: Company.organization_type — market-facing categorization
--
-- Adds a controlled-vocabulary "organization type" field to companies for
-- segmenting outreach by the kind of organization (B2B agency, B2C end client,
-- public sector, cultural institution, event organizer, non-profit, other).
--
-- This is orthogonal to existing fields:
--   - business_model (b2b/b2c/gov/...)    — generic GTM model
--   - segment (obec/spolek/agentura/...)   — Czech legal form (migration 054)
--   - industry / geo_region / company_size — separate axes
--
-- Source: BL-1108 (LCC client request #9, v25 Phase 6). Drives campaign
-- audience selection for BL-1111/1112/1113.
--
-- Allowed values are validated at the API layer (api/routes/company_routes.py
-- update_company endpoint). The column is intentionally a free VARCHAR(40)
-- — no PostgreSQL enum — so we can evolve categories without ALTER TYPE.
--
-- Backfill: existing rows get NULL. Operators categorize incrementally via
-- the dashboard (detail page dropdown + companies-table filter).

ALTER TABLE companies ADD COLUMN IF NOT EXISTS organization_type VARCHAR(40);

CREATE INDEX IF NOT EXISTS idx_companies_org_type
    ON companies(tenant_id, organization_type)
    WHERE organization_type IS NOT NULL;
