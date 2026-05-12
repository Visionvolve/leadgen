-- BL-1044 (security review): single-use OAuth state nonce store.
--
-- Adds replay protection for the Gmail OAuth callback. At `connect` time the
-- handler issues a JWT-signed state carrying a random nonce and persists that
-- nonce here with its expiry. At `callback` time the handler atomically
-- deletes the nonce row: a second redemption of the same state finds no row
-- and is rejected with 400.
--
-- The table is shared infrastructure and not Gmail-specific -- naming is
-- deliberately generic so other OAuth flows (generic Google OAuth, future
-- providers) can reuse the same guard.
--
-- Retention: rows are deleted on successful redemption. Stale rows (user
-- abandoned the flow) are expired opportunistically by callers or by the
-- scheduled GC noted below.

CREATE TABLE IF NOT EXISTS oauth_state_nonces (
    nonce VARCHAR(64) PRIMARY KEY,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_state_nonces_expires
    ON oauth_state_nonces(expires_at);

-- TODO: add scheduled job to DELETE FROM oauth_state_nonces WHERE expires_at < NOW()
-- (opportunistic cleanup runs at each callback for now).
