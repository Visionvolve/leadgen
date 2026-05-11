# Gmail OAuth Setup (BL-1044)

One-time infrastructure setup for the Gmail OAuth foundation. Required before
any tenant can connect their inbox via the in-app Settings -> Gmail Integration
page.

## Summary

We need a Google Cloud project + OAuth 2.0 Web Application credentials with the
`gmail.readonly` scope. Credentials are stored in 1Password and injected into
the API as environment variables.

## Steps

### 1. Create / choose the Google Cloud project

1. Open https://console.cloud.google.com/
2. Create a new project (or reuse `visionvolve-leadgen` if it already exists).
3. Note the project ID.

### 2. Enable the Gmail API

1. APIs & Services -> Library
2. Search for "Gmail API"
3. Click Enable

### 3. OAuth consent screen

1. APIs & Services -> OAuth consent screen
2. User type: **External** (required to authorize Google Workspace / personal
   Gmail accounts outside our org).
3. App information:
   - App name: `VisionVolve Leadgen`
   - User support email: `founder@visionvolve.com`
   - Developer contact: `founder@visionvolve.com`
4. Scopes -- add:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `openid`
   - `email`
5. Test users (while the app is in Testing mode): add any Gmail addresses that
   will be connecting to leadgen during dev/staging.
6. Publish when ready for broader use (requires Google verification if we go
   past 100 users or request sensitive scopes beyond readonly).

### 4. Create OAuth 2.0 credentials

1. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID
2. Application type: **Web application**
3. Name: `Leadgen Gmail OAuth`
4. Authorized JavaScript origins:
   - `http://localhost:5001`
   - `https://leadgen-staging.visionvolve.com`
   - `https://leadgen.visionvolve.com`
5. Authorized redirect URIs -- **must match exactly**:
   - `http://localhost:5001/api/auth/gmail/callback`
   - `https://leadgen-staging.visionvolve.com/api/auth/gmail/callback`
   - `https://leadgen.visionvolve.com/api/auth/gmail/callback`
6. Click Create. Copy the Client ID and Client Secret.

### 5. Generate the token encryption key

Run locally (one-time):

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This produces a URL-safe base64 Fernet key (44 chars). Store it in 1Password.
**Do not reuse the existing `OAUTH_ENCRYPTION_KEY`** -- we keep this key
separate so Gmail tokens can be rotated independently of the generic OAuth
store.

### 6. Store secrets in 1Password

Vault: `visionvolve-prod`. Create an entry called **Gmail OAuth (leadgen)**
with the following fields:

| Field | Value |
|-------|-------|
| `GOOGLE_GMAIL_CLIENT_ID` | from step 4 |
| `GOOGLE_GMAIL_CLIENT_SECRET` | from step 4 |
| `GMAIL_TOKEN_ENCRYPTION_KEY` | from step 5 |
| `GMAIL_OAUTH_REDIRECT_URI` (prod) | `https://leadgen.visionvolve.com/api/auth/gmail/callback` |
| `GMAIL_OAUTH_REDIRECT_URI` (staging) | `https://leadgen-staging.visionvolve.com/api/auth/gmail/callback` |

### 7. Inject into environments

**Staging** (`STAGING_DOTENV` GitHub secret):

```
GOOGLE_GMAIL_CLIENT_ID=<staging-client-id>
GOOGLE_GMAIL_CLIENT_SECRET=<staging-client-secret>
GMAIL_TOKEN_ENCRYPTION_KEY=<44-char-fernet-key>
GMAIL_OAUTH_REDIRECT_URI=https://leadgen-staging.visionvolve.com/api/auth/gmail/callback
FRONTEND_BASE_URL=https://leadgen-staging.visionvolve.com
```

Redeploy staging infra to pick up the new vars:

```bash
gh workflow run deploy-staging-infra.yml
```

**Production** (container env on the VPS, via leadgen-api compose overlay):

Add the same vars to `docker-compose.api.yml` / production secret store.

**Local dev** (`.env.dev`):

```
GOOGLE_GMAIL_CLIENT_ID=<dev-or-shared-staging-client-id>
GOOGLE_GMAIL_CLIENT_SECRET=<dev-secret>
GMAIL_TOKEN_ENCRYPTION_KEY=<44-char-fernet-key>
GMAIL_OAUTH_REDIRECT_URI=http://localhost:5001/api/auth/gmail/callback
FRONTEND_BASE_URL=http://localhost:5173
```

### 8. Run the migration

```bash
gh workflow run migrate-staging
```

Migration `061_gmail_connections.sql` creates the `gmail_connections` table.

### 9. Verify

1. Log in as a tenant admin at `https://leadgen-staging.visionvolve.com`.
2. Navigate to user menu -> Gmail Integration.
3. Click Connect Gmail, complete Google consent.
4. Confirm status endpoint:

```bash
curl -H "Authorization: Bearer <jwt>" \
     -H "X-Namespace: <ns>" \
     https://leadgen-staging.visionvolve.com/api/auth/gmail/status
```

Expected: `{"connected": true, "email": "...", "last_synced_at": null}`.

## Security notes

- Tokens are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256) before
  being stored in the `access_token_encrypted` / `refresh_token_encrypted`
  BYTEA columns.
- The OAuth `state` parameter is a JWT signed with our app's `JWT_SECRET_KEY`
  and expires after 10 minutes, protecting the callback against CSRF.
- Scope is limited to `gmail.readonly` -- we can read message headers and
  bodies but cannot send, modify, or delete mail.
- On disconnect we call Google's `/revoke` endpoint and zero the stored
  ciphertext before marking the row `disconnected_at`.

## Follow-up work

- **BL-1044-b**: inbound-mail polling worker that reads `last_synced_at`,
  fetches new messages via Gmail API, and feeds them into reply-rate
  attribution.
- **BL-1044-c**: reply attribution + reply-rate KPI wiring.
