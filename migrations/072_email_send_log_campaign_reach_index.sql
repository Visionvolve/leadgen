-- 072_email_send_log_campaign_reach_index.sql
--
-- Campaign Reach Reporting (BL-1114, milestone v25 phase 11).
--
-- The reach endpoint aggregates EmailSendLog rows scoped to a single
-- campaign and (for the timeline) groups by send date. The join path
-- is `email_send_log → messages → campaign_contacts`, so the actual
-- lookup key on the send-log side is the `message_id` foreign key
-- (already indexed) plus a tenant filter (already covered by
-- `idx_email_send_log_tenant_status`).
--
-- The new index speeds up the timeline aggregation: once we have the
-- candidate send-log rows for a campaign, we order/bucket them by
-- `sent_at`. A composite index on `(tenant_id, sent_at)` lets the
-- planner scan tenant slices ordered by date without a sort step. This
-- also benefits the rollup endpoint (`/api/campaigns/reach/summary`)
-- which scans the tenant's full send log.
--
-- Safe to re-run: uses ``IF NOT EXISTS``.

CREATE INDEX IF NOT EXISTS idx_email_send_log_tenant_sent_at
    ON email_send_log (tenant_id, sent_at)
    WHERE sent_at IS NOT NULL AND superseded_at IS NULL;
