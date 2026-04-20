-- Migration 059: EventFest recipient linkage + unsubscribed state
-- Adds unsubscribed_at to email_send_log (Phase 2 LEADGEN-01 6th state)
-- Adds microsite_partner_token to campaign_contacts (Phase 2 cross-repo attribution)

BEGIN;

ALTER TABLE email_send_log
  ADD COLUMN IF NOT EXISTS unsubscribed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_email_send_log_unsubscribed_at
  ON email_send_log (unsubscribed_at)
  WHERE unsubscribed_at IS NOT NULL;

ALTER TABLE campaign_contacts
  ADD COLUMN IF NOT EXISTS microsite_partner_token TEXT;

CREATE INDEX IF NOT EXISTS idx_campaign_contacts_partner_token
  ON campaign_contacts (microsite_partner_token)
  WHERE microsite_partner_token IS NOT NULL;

COMMIT;
