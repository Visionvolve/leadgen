-- BL-1044: Gmail OAuth foundation — connection metadata + encrypted tokens at rest.
--
-- Stores per-tenant Gmail connections used by the inbound-mail poller (follow-up
-- sub-item) to read reply messages for reply-rate attribution. Tokens are
-- Fernet-encrypted in the application layer before insert; BYTEA here holds the
-- ciphertext directly.
--
-- Scope granted: https://www.googleapis.com/auth/gmail.readonly
--
-- Relationship to existing oauth_connections table:
-- `oauth_connections` is the generic multi-provider/multi-scope OAuth store used
-- by Google Contacts import, Gmail scan, and Gmail send (outbound). This new
-- table is dedicated to the inbound polling foundation so its lifecycle
-- (connected/disconnected/last_synced) can evolve independently without
-- entangling outbound-send state.

CREATE TABLE IF NOT EXISTS gmail_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    email_address TEXT NOT NULL,
    access_token_encrypted BYTEA NOT NULL,
    refresh_token_encrypted BYTEA NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    scopes TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_synced_at TIMESTAMPTZ,
    disconnected_at TIMESTAMPTZ,
    UNIQUE(tenant_id, email_address)
);

CREATE INDEX IF NOT EXISTS idx_gmail_connections_tenant ON gmail_connections(tenant_id);
