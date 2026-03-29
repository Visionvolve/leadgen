-- Campaign steps: relational structure + JSONB config
CREATE TABLE IF NOT EXISTS campaign_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    position INTEGER NOT NULL DEFAULT 1,
    channel VARCHAR(50) NOT NULL DEFAULT 'linkedin_message',
    day_offset INTEGER NOT NULL DEFAULT 0,
    label VARCHAR(255) NOT NULL DEFAULT '',
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(campaign_id, position)
);

CREATE INDEX IF NOT EXISTS idx_campaign_steps_campaign ON campaign_steps(campaign_id);

-- Link messages to steps
ALTER TABLE messages ADD COLUMN IF NOT EXISTS campaign_step_id UUID REFERENCES campaign_steps(id);
CREATE INDEX IF NOT EXISTS idx_messages_campaign_step ON messages(campaign_step_id);

-- Link campaigns to LinkedIn accounts
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS linkedin_account_id UUID REFERENCES linkedin_accounts(id);
