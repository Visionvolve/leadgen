-- Migration 061: Add `kind` column to email_send_log (BL-1026)
--
-- Distinguishes preview/test sends from real production sends so default
-- campaign analytics can filter out preview rows (which would otherwise
-- pollute open/click/reply rates). Preview rows are retained for audit.
--
-- Backward-compatible: existing rows default to 'production'; analytics
-- queries filter on `kind != 'preview'` (treats NULL as production too,
-- via the NOT NULL default).

BEGIN;

ALTER TABLE email_send_log
  ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'production';

-- Index on (tenant_id, kind) accelerates "exclude previews" filters in
-- analytics queries; composite index reuses tenant_id locality already
-- present in most access patterns.
CREATE INDEX IF NOT EXISTS idx_email_send_log_tenant_kind
  ON email_send_log (tenant_id, kind);

COMMIT;
