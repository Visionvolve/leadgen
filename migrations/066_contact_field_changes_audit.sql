-- BL-1107: audit log for inline-edit changes to contacts and companies.
--
-- Captures every per-field diff applied via the PATCH endpoints
-- (contact_routes.update_contact, company_routes.update_company).
--
-- Goals:
--   1. Reconstruct who changed what / when for compliance and undo workflows.
--   2. Surface "auto-generated" vs "user-curated" provenance — pairs with
--      contacts.salutation_overridden (migration 067).
--   3. Cheap to write (single row per changed field) and cheap to read by
--      (entity_type, entity_id) for a contact/company detail history view.
--
-- Naming: kept generic so future entities (campaigns, owners, tags) can reuse
-- the same table without another migration.

CREATE TABLE IF NOT EXISTS contact_field_changes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('contact', 'company')),
    entity_id UUID NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_by UUID,  -- users.id, nullable for system / migration updates
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source TEXT NOT NULL DEFAULT 'user_patch'  -- 'user_patch' | 'enrichment' | 'system'
);

CREATE INDEX IF NOT EXISTS idx_field_changes_entity
    ON contact_field_changes (tenant_id, entity_type, entity_id, changed_at DESC);

CREATE INDEX IF NOT EXISTS idx_field_changes_changed_by
    ON contact_field_changes (changed_by, changed_at DESC);
