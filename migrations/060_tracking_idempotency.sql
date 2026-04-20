-- Migration 060: Idempotency guarantee for microsite event ingestion (Phase 3 WIRE-02)
-- A duplicate POST from UA microsite with the same (contact_id, event_type,
-- occurred_at) tuple must NOT create a second Activity row. Enforced via
-- a unique partial index scoped to source='microsite' so other activity
-- sources (manual logging, sales touches) remain duplicate-tolerant.

BEGIN;

-- Drop any existing non-unique index on the same columns if present.
DROP INDEX IF EXISTS idx_activities_microsite_dedup;

CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_microsite_dedup
  ON activities (contact_id, event_type, occurred_at)
  WHERE source = 'microsite' AND contact_id IS NOT NULL;

COMMIT;
