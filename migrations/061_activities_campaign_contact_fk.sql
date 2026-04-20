-- Migration 061: Proper FK from activities to campaign_contacts for reliable
-- campaign attribution (Phase 4 Agent Z5 remediation).
--
-- Problem: activities.payload is JSONB. Attributing an activity to a specific
-- campaign required a join like:
--   JOIN campaign_contacts cc ON cc.microsite_partner_token = a.payload->>'token'
-- which (a) requires the token to actually be present in payload (Fix C),
-- (b) is a JSONB extract on every row (no functional index on payload->>'token'
-- today), and (c) is ambiguous if the same partner receives a second token
-- later under a different campaign.
--
-- Fix: add a proper UUID FK column campaign_contact_id on activities, set it
-- at ingest time in tracking_routes._resolve_contact when a partner token
-- matches. Indexed. ON DELETE SET NULL so a deleted campaign_contact does not
-- orphan historical events.

BEGIN;

ALTER TABLE activities
  ADD COLUMN IF NOT EXISTS campaign_contact_id UUID
    REFERENCES campaign_contacts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_activities_campaign_contact_id
  ON activities(campaign_contact_id)
  WHERE campaign_contact_id IS NOT NULL;

COMMIT;
