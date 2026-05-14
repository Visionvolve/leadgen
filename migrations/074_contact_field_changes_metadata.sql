-- 074_contact_field_changes_metadata.sql
--
-- BL-1203 / Phase 12: extensible metadata slot for audit rows.
--
-- Required by the merge endpoint (POST /api/companies/<id>/merge)
-- which stores a JSON snapshot of the deleted row alongside its
-- merged_from audit entry. Also used by the PATCH 'keep both'
-- path to flag duplicate_kept_intentionally.
--
-- Safe to re-run: uses IF NOT EXISTS.

ALTER TABLE contact_field_changes
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
