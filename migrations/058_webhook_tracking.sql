-- Migration 058: Add complained_at column and resend_message_id index for webhook tracking
-- BL-315: Resend webhook handler for email open/click/bounce tracking

-- Add complained_at column if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'email_send_log' AND column_name = 'complained_at'
    ) THEN
        ALTER TABLE email_send_log ADD COLUMN complained_at TIMESTAMPTZ;
    END IF;
END $$;

-- Index on resend_message_id for fast webhook lookup
CREATE INDEX IF NOT EXISTS idx_email_send_log_resend_message_id
    ON email_send_log (resend_message_id)
    WHERE resend_message_id IS NOT NULL;
