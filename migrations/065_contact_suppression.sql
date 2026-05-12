-- Migration 065: Add suppression columns to contacts (BL-1103, BL-1105).
--
-- Context (Milestone v25, Phase 3 — Unsubscribe Loop):
--   When a recipient unsubscribes (via the List-Unsubscribe one-click flow,
--   the public POST /api/unsubscribe endpoint, hard-bounces, or a spam
--   complaint), the contact must be flagged so no future campaign send
--   touches them again. This migration adds three columns:
--
--   * is_suppressed        — boolean gate read by send_service.py
--   * suppressed_at        — first time the suppression was applied
--   * suppression_reason   — free-form code ("resend_webhook",
--                            "hard_bounce", "spam_complaint",
--                            "user_one_click", "manual", ...)
--
--   A partial index on (tenant_id, is_suppressed) WHERE is_suppressed=TRUE
--   keeps the dashboard "suppressed list" query and any send-side
--   anti-join cheap without bloating the contacts index footprint.
--
-- Idempotent: uses IF NOT EXISTS for both columns and index.

BEGIN;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS is_suppressed BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS suppressed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS suppression_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_contacts_suppressed
    ON contacts (tenant_id, is_suppressed)
    WHERE is_suppressed = TRUE;

COMMIT;
