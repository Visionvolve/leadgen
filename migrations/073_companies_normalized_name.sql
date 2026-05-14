-- 073_companies_normalized_name.sql
--
-- BL-1203 / Phase 12: app-computed normalized company name.
--
-- Stores the output of api.services.name_normalize.normalize_company_name
-- so duplicate detection on PATCH can match exactly without re-running
-- Python on every row. NON-UNIQUE on purpose: users can choose 'Keep
-- both as separate' in the resolution modal; uniqueness is enforced by
-- the application-layer prompt, not the database.
--
-- Safe to re-run: uses IF NOT EXISTS for both column and index.

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS normalized_name TEXT;

CREATE INDEX IF NOT EXISTS idx_companies_tenant_normalized_name
    ON companies (tenant_id, normalized_name);
