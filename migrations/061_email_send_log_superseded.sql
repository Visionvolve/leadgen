-- Migration 061: Mark superseded email_send_log rows (BL-1029).
--
-- Context: When a campaign send aborts partway (e.g. daily_quota_exceeded) and
-- is later resumed/retried, the retry creates a new `sent` row next to the
-- earlier `failed` row for the same (tenant_id, message_id). Audit queries
-- like "how many partners got the email?" then double-count or miscount
-- without SQL gymnastics.
--
-- This migration adds explicit markers so default analytics exclude
-- superseded rows, while an "all attempts" audit view still exposes them.
--
-- Also applies a one-time backfill for the 110 EventFest round-2 failed rows
-- from 2026-04-21 (and any other historic (message_id) where a later sent
-- row supersedes an earlier failed row).

BEGIN;

ALTER TABLE email_send_log
    ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS superseded_by UUID REFERENCES email_send_log(id) ON DELETE SET NULL;

-- Partial index: analytics queries filter `superseded_at IS NULL` frequently;
-- a partial index keeps the hot path cheap without bloating index size.
CREATE INDEX IF NOT EXISTS idx_email_send_log_not_superseded
    ON email_send_log (tenant_id, message_id)
    WHERE superseded_at IS NULL;

-- Backfill: for any message_id that has BOTH a non-failed row (sent,
-- delivered, opened, clicked, bounced, complained, unsubscribed) AND one or
-- more earlier `failed` rows, mark the failed rows as superseded by the
-- latest non-failed row. "Earlier" is measured by created_at.
--
-- This explicitly covers the 110 EventFest round-2 `failed`
-- (daily_quota_exceeded) rows that sit next to the resume worker's `sent`
-- rows, without touching any row where the only outcome was failure.
WITH survivors AS (
    SELECT
        esl.message_id,
        esl.tenant_id,
        (
            SELECT s.id
            FROM email_send_log s
            WHERE s.message_id = esl.message_id
              AND s.tenant_id = esl.tenant_id
              AND s.status <> 'failed'
            ORDER BY s.created_at DESC
            LIMIT 1
        ) AS survivor_id,
        (
            SELECT s.created_at
            FROM email_send_log s
            WHERE s.message_id = esl.message_id
              AND s.tenant_id = esl.tenant_id
              AND s.status <> 'failed'
            ORDER BY s.created_at DESC
            LIMIT 1
        ) AS survivor_at
    FROM email_send_log esl
    WHERE esl.status = 'failed'
      AND esl.superseded_at IS NULL
    GROUP BY esl.message_id, esl.tenant_id
)
UPDATE email_send_log target
SET superseded_at = survivors.survivor_at,
    superseded_by = survivors.survivor_id
FROM survivors
WHERE target.message_id = survivors.message_id
  AND target.tenant_id = survivors.tenant_id
  AND target.status = 'failed'
  AND target.superseded_at IS NULL
  AND survivors.survivor_id IS NOT NULL
  AND target.created_at < survivors.survivor_at;

COMMIT;
