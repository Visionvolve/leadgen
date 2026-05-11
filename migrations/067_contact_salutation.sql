-- BL-1106: editable salutation field on contacts with Czech vocative auto-derive.
--
-- Adds two columns:
--   * salutation               -- the displayed greeting form, default auto-derived
--                                 from first_name via api.services.czech_vocative.
--   * salutation_overridden    -- TRUE once the user explicitly sets the field;
--                                 prevents future first_name edits from clobbering
--                                 the manual override.
--
-- Auto-derive runs in api/routes/contact_routes.update_contact (and the import
-- pipeline) — kept in application code, not as a SQL trigger, because the
-- vocative engine has a Tier 3 AI fallback that we don't want to invoke from
-- a database transaction.
--
-- Backfill: existing rows can have their salutation lazily populated on next
-- edit / display path. A separate one-off backfill script can call the same
-- helper to seed every row at deploy time if desired.

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS salutation TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS salutation_overridden BOOLEAN NOT NULL DEFAULT FALSE;
