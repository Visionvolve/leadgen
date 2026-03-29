CREATE TABLE IF NOT EXISTS assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL,
    filename VARCHAR(500) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    storage_path VARCHAR(1000) NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assets_tenant ON assets(tenant_id);
CREATE INDEX IF NOT EXISTS idx_assets_campaign ON assets(campaign_id);
