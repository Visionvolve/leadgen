-- LinkedIn account identity tracking for browser extension
CREATE TABLE IF NOT EXISTS linkedin_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    owner_id UUID REFERENCES owners(id),
    linkedin_name VARCHAR(255) NOT NULL,
    linkedin_url VARCHAR(500) NOT NULL,
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, linkedin_url)
);
