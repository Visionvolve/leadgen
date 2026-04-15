# Leadgen Extension Current Features Analysis

## High-Level Architecture
- **sales-navigator.ts**: DOM extraction + LinkedIn Sales API enrichment for leads
- **activity-monitor.ts**: Messaging/connections scraping via LinkedIn Voyager API
- **service-worker.ts**: Message relay, multi-page orchestration, activity buffering, SSO auth
- **popup.ts/popup.html**: UI with auth, namespace picker, stats, sync button
- **config.ts**: All rate limiting & timing constants
- **auth.ts**: Token storage, login, refresh, logout (no IAM integration yet)
- **api-client.ts**: Authenticated HTTP wrapper with namespace header

---

## Lead Extraction (sales-navigator.ts)

### How Leads Are Extracted
- **DOM selectors**: `tr[data-row-id]` rows, parse `href="/sales/lead/{leadId},{authType},{authToken}"`
- **Fields**: Name, job title (regex heuristic from nested divs), company + companyId
- **Job title detection**: ~15 keyword patterns (CEO/CFO/etc) + " at " + length heuristic

### Enrichment via LinkedIn Sales API
1. **Public profile URLs**: GET `/sales-api/salesApiProfiles/(profileId:X,authType:Y,authToken:Z)`
   - Decoration params: entityUrn, firstName, lastName, fullName, headline, flagshipProfileUrl
   - Returns: fullName, firstName, lastName, headline, flagshipProfileUrl
2. **Company data**: GET `/sales-api/salesApiCompanies/{companyId}`
   - Fields: industry, employeeCountRange, revenue, website

### Rate Limiting / Delay Mechanisms
- **leadEnrichDelay**: 500ms base delay (config-driven)
- **Exponential backoff**: `delay * (2 ^ consecutive_rate_limits)`, capped at maxDelay (5s)
- **429 handling**: Retry up to 3x with 10s cooldown between attempts
- **Backoff decay**: Decrements consecutiveRateLimits counter on success
- **Per-lead**: Wait enforced BETWEEN requests, not just throttling

### Human Simulation Features
- CSRF token auto-detection from JSESSIONID cookie
- No extra headers (uses standard fetch + CSRF token)
- No User-Agent manipulation detected
- Delays simulate human pacing but minimal obfuscation

### Import Limit Controls
- **None**: Can extract unlimited leads from current page
- Multi-page mode: No enforced limit across pages
- Activity sync: Max 15 API calls per sync (hardcoded in config)

### Multi-Page Handling
- Detects pagination: URL `?page=X`, pagination buttons, "of N pages" text, result count math
- **goToNextPage()**: Updates URL and navigates
- **Multi-page orchestration in service worker**:
  - Stores MultiPageProcess state in chrome.storage.local
  - Triggers extraction via content script message
  - Reports PageExtractionResult back to service worker
  - Auto-navigates to next page with 5s delay (multiPageDelay)
  - Accumulates stats (totalLeads, totalProfileUrls, pagesCompleted)

---

## Activity Monitor (activity-monitor.ts)

### What It Monitors
1. **Messaging**: Conversations list → individual conversation events (message_sent / message_received)
   - Uses LinkedIn Voyager API: `/voyager/api/messaging/conversations`
   - Scrapes message text, timestamp, participant (name + public ID + LinkedIn URL)
   - **Participant detection**: From miniProfile in included data or unwrapped MessagingMember

2. **Connection Requests**: Received invitations
   - API: `/voyager/api/relationships/invitationViews?q=receivedInvitation`
   - Fields: sender name, headline, message, sentTime

3. **Recent Connections**: Accepted connections (RECENTLY_ADDED sort)
   - API: `/voyager/api/relationships/connections?sortType=RECENTLY_ADDED`
   - Timestamp fallback: createdAt, connectedAt, or current time

### External ID Generation
- **Deterministic hash**: SHA-256 of sorted JSON (event_type + contact_url + timestamp + conversation_id)
- **Fallback**: Simple 32-bit hash for older browsers
- **Deduplication**: By event_type + contact_url + timestamp (minute-level precision)

### Rate Limiting / Safety
- **maxApiCallsPerSync**: 15 (hardcoded per config, hard cap)
- **maxConversationsPerSync**: 10 conversations processed
- **activityApiDelay**: 2s delay between API calls
- **Checks**: If API limit approaching after each source (conversations → connection requests → recent connections)
- **Partial sync**: Marks `wasPartial=true` if limit reached mid-scan
- **Timestamp filtering**: Only events after lastSyncTime (prevents re-scraping)

---

## Service Worker (service-worker.ts)

### Message Handling
- `leads_extracted`: Handle upload relay (from content:sales-navigator)
- `activities_scraped`: Buffer events for later upload
- `sync_activities`: Trigger full activity sync (from popup)
- `get_auth_state`: Return stored auth
- **Multi-page messages**: `start_multi_page`, `page_extraction_complete`, `stop_multi_page`, `get_multi_page_state`
- `sso_login`: Initiate SSO flow with IAM service
- `linkedin_page_loaded`: Activity monitor notification

### Multi-Page Orchestration
1. **startMultiPageFromTab()**: Initializes MultiPageProcess state
2. **triggerExtraction()**: Injects content script + sends extract message
3. **handlePageExtractionComplete()**: Updates stats, checks hasNextPage
4. If next page exists: Wait 5s, re-trigger extraction on new page
5. If no next: Finish (set active=false, endTime)

### Rate Limiting
- Per-sync state: apiCallCount in activity-monitor (reset per sync)
- Global activity buffer: accumulated before batch upload
- Batch size: 50 events per upload (activityBatchSize)
- Sync lock: isSyncing flag prevents concurrent syncs

### Batch Upload Logic
1. Receive events from content script
2. Add to activityBuffer
3. Batch process: splice 50 at a time, POST to API
4. On failure: Put batch back in buffer (no events lost)
5. Update lastSyncTime after successful batch

### Periodic Sync
- **chrome.alarms**: "activitySync" alarm every 30 minutes (activitySyncInterval)
- Finds a LinkedIn tab (preferring /messaging or /mynetwork)
- Injects activity-monitor.ts if needed
- Requests scraping with lastSyncTime context

### Tab Listener (chrome.tabs.onUpdated)
- **SSO callback detection**: Listens for `/auth/callback#access_token=...`
  - Parses JWT + user + roles from hash
  - Auto-selects namespace if only one role
  - Closes auth tab automatically
- **Tab-triggered activity sync**: LinkedIn tab loads → throttled sync (min 5 min interval)
- **Multi-page tracking**: If SalesNav page + tracked tabId → trigger extraction after delay

---

## Popup UI (popup.ts/popup.html)

### Controls
- **Environment badge**: Shows "STAGING" if config.environment === staging (orange header)
- **Login view**: Email/password form + Google/GitHub SSO buttons + OR divider
- **Namespace picker**: Dropdown (populated from user.roles keys) + Continue button
- **Connected view**: User email, stats (lead count, activity count), Sync Now button, Logout

### User-Facing Features
- Manual "Sync Now" button (triggers full activity sync)
- Storage listener: Auto-updates UI on auth state change (e.g., after SSO completes)
- Status display: "Syncing activities..." → "Synced: X new activities"
- Stats from GET /api/extension/status

### Missing: 
- No namespace selector in connected view (can't switch mid-session)
- No import limit UI
- No multi-page progress display

---

## Config (config.ts)

### Rate Limiting & Timing
```
leadEnrichDelay: 500ms
maxRetries: 3
backoffMultiplier: 2
maxDelay: 5s
cooldownDelay: 10s
activityApiDelay: 2s
maxConversationsPerSync: 10
maxApiCallsPerSync: 15
minTabSyncInterval: 5 min
multiPageDelay: 5s
activitySyncInterval: 30 min
```

### Batch/Limits
```
activityBatchSize: 50
defaultSyncDate: 2026-01-01
tokenRefreshBuffer: 60s
```

### Build-Time Injected
```
__API_BASE__ → config.apiBase
__EXT_ENV__ → config.environment (prod/staging)
__IAM_BASE__ → config.iamBase
```

---

## Auth (auth.ts)

### Current Implementation
- **Storage**: chrome.storage.local key `auth_state`
- **Login**: POST /api/auth/login (email/password) → returns access_token, refresh_token, user
- **Token refresh**: Checks JWT exp claim, refreshes 60s before expiry
- **Auto-namespace**: Single role → auto-select; multiple → user picks in popup
- **Logout**: Clears storage

### Missing: 
- **No IAM integration**: No OAuth redirect to /oauth/google or /oauth/github
- SSO callback parsing exists in service-worker but no SSO initiation from auth.ts

---

## API Client (api-client.ts)

### Features
- **apiFetch wrapper**: Injects Bearer token + X-Namespace header
- **Auto-refresh**: On 401, refreshes token + retries once
- **Error handling**: Throws ApiError(status, message)
- **Endpoints**:
  - POST /api/extension/leads (source, tag, leads array)
  - POST /api/extension/activities (events array)
  - GET /api/extension/status

### Missing:
- No special handling for 429 on API side (leave to content scripts)
- No request signing or HMAC

---

## SAFETY & ANTI-BAN FEATURES

### What Exists
✓ CSRF token extraction (auto-detect from cookies)
✓ Rate limiting with exponential backoff (leadEnrichDelay + retry logic)
✓ Deterministic deduplication (SHA-256 external_id for activities)
✓ Timestamp filtering (don't re-scrape old events)
✓ Tab-triggered sync throttling (min 5 min between tabs)
✓ Multi-page delay (5s between navigations)
✓ API call hard caps (15 calls/sync for activity monitor)

### What's MISSING (Production LinkedIn Scraper Needs)
✗ **No User-Agent rotation** (uses default browser UA)
✗ **No proxy support** (direct LinkedIn from user's IP)
✗ **No behavioral randomization** (timing is too predictable: exactly 500ms/2s)
✗ **No request signing/headers** (minimal headers, no LinkedIn-specific obfuscation)
✗ **No session validation** (doesn't check if logged in before scraping)
✗ **No IP/device fingerprint rotation** (browser extension tied to single device)
✗ **No request body randomization** (exact API calls every time)
✗ **No captcha handling** (fails silently if challenged)
✗ **No human-like scrolling** (extracts from loaded DOM, no interaction)
✗ **No connection pool warmup** (fresh fetch every request)
✗ **No LinkedIn-specific headers** (e.g., no X-LinkedIn-srs, X-LI-UUID, X-Restli-Protocol-Version added only for Sales API)

### Why These Gaps Don't Matter for Extension
The extension assumes:
1. **User is authenticated** (extension runs in logged-in user's context)
2. **User has legitimate access** (Sales Navigator subscription, network visibility)
3. **Single device** (one IP, one fingerprint)
4. **Transparent to LinkedIn** (no hiding, just automation)
5. **Moderate volume** (not industrial-scale scraping)

This is **NOT** a production scraper. It's **automation within auth boundary**.

---

## TODO Comments & Incomplete Features
None found in code. All features appear complete within current scope.

---

## Namespace/Tenant Selection
- **Current**: Auth state stores namespace (single string)
- **Flow**: Login → multiple roles? → namespace picker → stored in auth_state
- **Headers**: X-Namespace sent with every API request
- **Missing**: No runtime namespace switching after login (would need logout + re-auth)

---

## Import Limit Configuration
- **Leads per page**: Unlimited (no page extraction limit)
- **Activity API calls**: 15 per sync (activityApiCallsPerSync)
- **Activity events per sync**: No hard limit (batched 50 at a time for upload)
- **Multi-page runs**: No total limit across pages

---

## Comparison: Old vs New
**Old extension** (/Users/michal/git/linkedin-lead-uploader):
- Single-page extraction only
- No enrichment
- No activity scraping
- Manual upload button

**New extension** (/Users/michal/git/leadgen-pipeline/extension):
- Multi-page orchestration
- LinkedIn Sales API enrichment (profile URLs, company data)
- Activity scraping (messaging, connections)
- Periodic background sync
- SSO auth flow (partially implemented)
- Namespace/tenant support
