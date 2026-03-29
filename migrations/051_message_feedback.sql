CREATE TABLE IF NOT EXISTS message_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    campaign_id UUID REFERENCES campaigns(id),
    action VARCHAR(50) NOT NULL,
    edit_diff JSONB,
    edit_reason VARCHAR(100),
    edit_reason_text TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_message_feedback_campaign ON message_feedback(campaign_id);
CREATE INDEX IF NOT EXISTS idx_message_feedback_message ON message_feedback(message_id);
