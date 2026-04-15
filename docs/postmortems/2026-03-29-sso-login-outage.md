# Incident Post-Mortem: SSO Login Outage

**Date**: 2026-03-27 to 2026-03-29
**Severity**: High (complete SSO login failure)
**Duration**: ~48 hours
**Author**: Engineering team
**Status**: Resolved

---

## Summary

SSO login via Google was completely broken on both staging and production for approximately two days. Users clicking "Sign in with Google" on the leadgen platform saw a broken, unstyled page from the IAM service instead of being redirected to Google's OAuth consent screen. The incident revealed 9 distinct bugs across 4 systems (leadgen frontend, leadgen API, IAM service, and infrastructure) that had accumulated silently due to gaps in integration testing and deployment automation.

Password-based login was unaffected throughout the incident. No data was lost.

---

## Impact

- **Who was affected**: All users attempting to log in via SSO (Google OAuth) on both staging and production environments.
- **What was broken**: The entire SSO redirect chain -- from the frontend's initial OAuth request through IAM, Google, and back to the application.
- **Duration**: ~48 hours (2026-03-27 through 2026-03-29).
- **Workaround**: Password-based login remained functional throughout.
- **Data impact**: None. No data loss or corruption occurred.

---

## Timeline

### 2026-03-27 -- Initial Report

- **User reported**: SSO login broken. Clicking "Sign in with Google" on leadgen showed a broken, unstyled page from IAM instead of redirecting to Google.
- **Broken URL**: `https://iam.visionvolve.com/oauth/google?redirect=https%3A%2F%2Fleadgen.visionvolve.com%2Fapi%2Fauth%2Fiam%2Fcallback`

### 2026-03-27 -- Investigation Phase 1: IAM SPA Fallback (Bugs 1 and 2)

- **Root cause found**: Two issues identified.
  1. **Bug 1 -- Wrong OAuth URL path**: Frontend constructed the OAuth URL as `/oauth/google`, but IAM routes are mounted at `/auth/oauth/google`.
  2. **Bug 2 -- SPA fallback masking 404s**: IAM's `serveStatic` catch-all middleware served `dashboard/index.html` for ANY unmatched path, masking the 404 as a "broken page" instead of returning an error.
- **Fix for Bug 2**: Updated IAM `src/index.ts` to return 404 JSON for API paths (`/auth/*`, `/token/*`, etc.) instead of serving SPA HTML.
- **Fix for Bug 1**: Updated leadgen `LoginPage.tsx` OAuth URLs from `/oauth/google` to `/auth/oauth/google`.
- IAM fix deployed to production via GitHub Actions. Leadgen fix pushed to staging.

### 2026-03-29 -- Production Push

- Created PR #108 (staging to main).
- **CI failed** on pre-existing lint error (unused `CampaignContact` import). Fixed.
- **CI failed again** on pre-existing test failures (`test_login_success_via_iam`, `test_contact_filters` x3). Fixed mock key mismatch and SQLite compatibility for JSONB queries.
- PR passed CI and auto-merged.

### 2026-03-29 -- Bug 3: Staging env var mismatch

- Staging `docker-compose.leadgen.yml` set `IAM_URL` but Flask reads `IAM_BASE_URL`.
- Flask fell back to the production IAM URL, which rejected staging-issued OAuth codes.
- **Fix**: Renamed the environment variable in the compose file to `IAM_BASE_URL`.

### 2026-03-29 -- Bug 4: Staging nginx missing SPA fallback

- The `/auth/callback` route returned 404 from nginx because there was no `try_files` fallback to `index.html` for React SPA routes.
- **Fix**: Created `staging/nginx/leadgen-dashboard.conf` with proper SPA fallback and mounted it in the compose file.

### 2026-03-29 -- Bug 5: Production frontend not redeployed

- PR merged to main, but the GitHub Actions workflow only builds the Docker API image. It does not deploy frontend static files.
- Production was still serving the old JS bundle with the incorrect `/oauth/google` URLs.
- **Fix**: Manual frontend build and SCP to production VPS. Had to be done twice because the first deploy used a stale worktree.

### 2026-03-29 -- Bug 6: AuthCallbackPage race condition

- `AuthCallbackPage` stored tokens in `localStorage` then used React Router `navigate()` for SPA navigation.
- `AuthProvider` had already set `isAuthenticated: false` on mount (before tokens existed in storage).
- SPA navigation did not re-run `AuthProvider`'s mount `useEffect`, so stale state redirected the user back to the login page.
- **Fix**: Changed to `window.location.href` for a full page reload after storing tokens, forcing `AuthProvider` to re-initialize with the new tokens.

### 2026-03-29 -- Bug 7: Refresh endpoint wrong key

- `auth_routes.py:224` read `iam_data.get("access_token")` but IAM returns `accessToken` (camelCase).
- The login handler (line 84) correctly used `accessToken`; the refresh handler did not.
- This would cause token refresh to return null, breaking sessions after access token expiry.
- **Fix**: Changed to `iam_data.get("accessToken")`.

### 2026-03-29 -- Bug 8: Stale production API Docker image

- The production API container was running an image from March 16 (two weeks old).
- The GitHub Actions "Build Production Image" workflow pushes to GHCR but does NOT pull or restart the container on the VPS.
- The old image could not validate RS256 tokens from IAM because the auth code changes from weeks of work had never been deployed.
- RS256 validation failed silently due to a bare `except Exception: pass` block, falling back to HS256 which also failed, returning 401.
- The `apiFetch` client received 401, called `clearTokens()` and `window.location.href = '/'`, wiping tokens and redirecting to login.
- **Fix**: Pulled the latest GHCR image and restarted the container manually. The GHCR auth token on the VPS had also expired and needed a refresh.

### 2026-03-29 -- Bug 9: Test user had no tenant permissions

- `leadgen.visionvolve@gmail.com` completed OAuth successfully but had no IAM `app_access` record for the leadgen application.
- `find_or_create_local_user` created the user, but `sync_iam_roles` found no permissions to sync.
- The user had no namespace, so `getDefaultNamespace()` returned null, causing a redirect to `/` (the login page).
- **Fix**: Inserted an `app_access` record in the IAM database directly.

### 2026-03-29 -- Resolution

- Full SSO flow verified end-to-end using Playwright MCP with a real Google account.
- Both staging and production confirmed working.

---

## Root Cause Analysis

### Why did 9 bugs exist simultaneously?

The SSO integration spans 4 systems (leadgen frontend, leadgen API, IAM service, infrastructure/Caddy/nginx) but was tested in isolation. Each system's tests passed individually while the integrated flow was completely broken.

#### 1. No contract tests

Each service tested its own routes with mocks. Nobody tested that the URL the frontend constructs matches the route IAM actually exposes. Nobody tested that field names in API responses (`accessToken` vs `access_token`) match what consumers read.

#### 2. No integration tests with middleware

IAM unit tests mocked routes directly without the `serveStatic` middleware. The SPA fallback masking bug was invisible to tests because the middleware that caused it was never included in the test setup.

#### 3. No post-deploy smoke tests

No automated check verified that deployed services can actually communicate. A simple `curl` after deployment would have caught bugs 1 through 5. The deploy pipeline assumed that a successful build means a successful deployment.

#### 4. No frontend deployment automation

GitHub Actions builds the frontend but throws away the artifacts. Manual SCP deployment meant the frontend was always potentially stale. There was no mechanism to ensure the deployed frontend matched the merged code.

#### 5. Silent error swallowing

The `except Exception: pass` block in `decode_token()` silently swallowed RS256 validation failures, making the actual error completely invisible. When RS256 failed, the code silently fell through to HS256, which also failed, producing a generic 401 with no indication of what went wrong.

#### 6. No E2E test for the SSO flow

The entire redirect chain (frontend -> IAM -> Google -> IAM -> Flask -> frontend callback -> app) was never tested end-to-end. Each hop was tested in isolation, but the chain as a whole was never validated.

---

## What Went Well

- **Systematic investigation**: The debugging process traced each redirect in the chain methodically, identifying bugs in sequence rather than guessing.
- **Independent fixes**: Each bug was identified, understood, and fixed independently without introducing new issues.
- **End-to-end verification**: Playwright MCP was used to verify the complete fix with a real Google account, confirming the entire redirect chain worked.
- **Test strategy produced**: A comprehensive test strategy document was created identifying exactly which tests would have prevented each specific bug, providing a clear roadmap for prevention.
- **No data loss**: The incident was purely an authentication flow failure with no impact on stored data.

---

## What Went Wrong

- **9 bugs accumulated silently**: The lack of integration and contract tests allowed bugs to pile up across services without detection.
- **Deployment gaps**: The production deploy workflow was incomplete -- it built Docker images but did not deploy the frontend or restart containers.
- **Silent failures**: The bare `except: pass` in token validation made debugging significantly harder by hiding the actual error.
- **Manual deployment steps**: Relying on manual SCP for frontend deployment introduced human error (deploying from a stale worktree).
- **No monitoring or alerting**: There were no health checks that would have detected the SSO failure automatically.
- **Pre-existing test failures in CI**: The CI pipeline had pre-existing test failures that had to be fixed before the actual fix could be merged, adding delay.

---

## Action Items

### Immediate (P0)

| # | Action | Owner | Status |
|---|--------|-------|--------|
| 1 | Add post-deploy smoke tests to staging and production deploy workflows. Checks: OAuth route availability, SPA fallback behavior, bundle version hash, API health endpoint, IAM connectivity. | Engineering | TODO |
| 2 | Fix GHA `deploy-prod.yml` to include frontend deployment (build + SCP) and API container pull + restart on VPS. | Engineering | TODO |
| 3 | Remove `except Exception: pass` in `decode_token()`. Log the actual error so RS256 validation failures are visible in container logs. | Engineering | TODO |

### Short-term (P1)

| # | Action | Owner | Status |
|---|--------|-------|--------|
| 4 | Add contract test: frontend OAuth URL path matches IAM route (test ID: A1). | Engineering | TODO |
| 5 | Add contract test: token field names (`accessToken` vs `access_token`) match between IAM response and Flask reader (test ID: A2). | Engineering | TODO |
| 6 | Add Playwright E2E test: full SSO flow with test Google account using `storageState` for cookie reuse (test ID: D1). | Engineering | TODO |
| 7 | Add config validation CI check: env var names in `docker-compose` files match `os.environ.get()` calls in code (test ID: E1). | Engineering | TODO |

### Medium-term (P2)

| # | Action | Owner | Status |
|---|--------|-------|--------|
| 8 | Add IAM test bypass mode for CI: skip Google OAuth, issue tokens directly for a test user. | Engineering | TODO |
| 9 | Add RS256 token validation integration test in leadgen (currently only HS256 is tested). | Engineering | TODO |
| 10 | Add nginx config lint check: verify `try_files` SPA fallback exists for all frontend services. | Engineering | TODO |

---

## Lessons Learned

### Contract tests are essential for multi-service auth flows

Unit tests in isolation give false confidence. When Service A constructs a URL that Service B must handle, or when Service A reads a field that Service B writes, a contract test must verify the agreement. Without contract tests, each service can pass its own tests while the integration is completely broken.

### Post-deploy smoke tests are the highest-ROI investment

Five of the nine bugs would have been caught by simple HTTP checks after deployment: "Does this URL return 200?", "Does the API respond to health checks?", "Can the API reach IAM?" These checks take seconds to run and minutes to implement, yet they were absent from every deploy workflow.

### Silent error handling is a debugging nightmare

The `except Exception: pass` pattern in `decode_token()` turned a clear RS256 validation error into a mysterious 401. The actual root cause was invisible. Every exception handler must at minimum log the error. Swallowing exceptions silently should be treated as a code review blocker.

### Frontend deployment must be automated

Manual SCP deployment is a single point of failure. It requires remembering to do it, being in the right directory, and building from the right branch. The first attempt in this incident deployed from a stale worktree. Automating this step in the GitHub Actions workflow eliminates an entire class of errors.

### Test what you deploy, not what you build

A passing CI pipeline means the code is correct in a test environment. It does not mean the deployed artifact matches the code, that the container is running the latest image, or that the frontend bundle has been updated. The deployed state can differ from the built state in many ways, and only post-deploy verification catches these gaps.

---

## Appendix: Bug-to-Test Coverage Matrix

This matrix maps each bug to the test categories that would have prevented it.

| Bug | Description | Contract | Integration | Smoke | E2E | Config |
|-----|-------------|----------|-------------|-------|-----|--------|
| 1 | Wrong OAuth URL path | A1 | -- | C1 | D1 | -- |
| 2 | SPA fallback masking 404s | -- | B1 | C2 | -- | -- |
| 3 | Env var name mismatch | A6 | -- | C3 | -- | E1 |
| 4 | Nginx missing SPA fallback | -- | -- | C5 | D5 | E3 |
| 5 | Frontend not deployed | -- | -- | C4, C6 | D5 | E4 |
| 6 | Callback race condition | A4 | -- | -- | D2 | -- |
| 7 | Refresh key mismatch | A2 | -- | -- | -- | -- |
| 8 | Stale API Docker image | -- | -- | C3 | -- | -- |
| 9 | No user permissions | -- | -- | -- | D6 | -- |

**Legend:**
- **Contract (A)**: Tests that verify agreements between services (URL paths, field names, env var names).
- **Integration (B)**: Tests that run services with their real middleware and configuration.
- **Smoke (C)**: Post-deploy HTTP checks that verify services are reachable and responding correctly.
- **E2E (D)**: Full browser-based tests that exercise the complete user flow.
- **Config (E)**: Static analysis checks that verify configuration consistency across services.

---

## Appendix: Systems Involved

| System | Role in SSO Flow | Bugs Found |
|--------|-----------------|------------|
| Leadgen Frontend (React SPA) | Constructs OAuth URL, handles callback, stores tokens | 1, 6 |
| Leadgen API (Flask) | Exchanges OAuth code, issues JWT, refreshes tokens | 7, 8 |
| IAM Service (Node.js) | OAuth provider, token issuer, permission store | 2, 9 |
| Infrastructure (Caddy, nginx, Docker, GHA) | Routing, static file serving, deployment | 3, 4, 5, 8 |
