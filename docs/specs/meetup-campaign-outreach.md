# Meetup Campaign Outreach — Gap Analysis & Sprint Plan

**Created**: 2026-03-10
**Status**: Planned
**Goal**: Enable end-to-end meetup outreach: filter Prague business leaders -> LinkedIn invite/message (extension decides at runtime) -> email non-responders after 3 days

---

## Key Discovery

The template system already supports multiple steps with different channels. Generation iterates per-contact x per-enabled-step. A template with both `linkedin_connect` AND `linkedin_message` steps would already generate both messages per contact. The LinkedIn queue already maps channel -> action_type (`linkedin_connect` -> `connection_request`, `linkedin_message` -> `message`).

**What actually works today:**
- Template with 3 steps (linkedin_connect + linkedin_message + email) -> generates 3 messages per contact
- `queue_linkedin()` queues both LinkedIn types to `LinkedInSendQueue` with correct action_types
- Extension picks up queued items and sends them
- Email sends via Resend with full engagement tracking

**What's actually missing (refined):**
1. No system template configured with both LinkedIn types simultaneously
2. Extension gets flat queue - doesn't know invite+DM belong to same contact (can't pick one)
3. Extension doesn't check LinkedIn connection status
4. No mechanism to skip the unused message type
5. No send confirmation as Activity record (extension only PATCHes queue status)
6. No non-responder detection endpoint
7. No sequence timing/delay logic
8. No automated email follow-up trigger
9. No ICP filter presets for quick campaign setup
10. No frontend UI for sequence progress

---

## Current Architecture (Relevant Code)

| Component | File | Key Functions |
|---|---|---|
| Message generation | `api/services/message_generator.py` | `_generate_all()` iterates contacts x steps |
| Generation prompts | `api/services/generation_prompts.py` | `build_generation_prompt()` per channel |
| LinkedIn queue | `api/routes/campaign_routes.py:2223` | `queue_linkedin()` maps channel->action_type |
| Extension pickup | `api/routes/extension_routes.py:261` | `get_linkedin_queue()` returns flat list |
| Extension status | `api/routes/extension_routes.py:339` | PATCH queue item status (sent/failed/skipped) |
| Extension activities | `api/routes/extension_routes.py:113` | `upload_activities()` by external_id |
| Email send | `api/services/send_service.py` | `send_campaign_emails()` via Resend |
| Campaign templates | `api/routes/campaign_routes.py` | System templates with steps array |
| Contact filtering | `api/routes/contact_routes.py` | Filters: location_city, seniority, job_titles |
| Outreach UI | `frontend/src/pages/campaigns/tabs/OutreachTab.tsx` | Email/LinkedIn status + queue buttons |
| Latest migration | `migrations/047_iam_integration.sql` | Next: 048 |

### Template Step Schema (existing)
```json
{"step": 1, "label": "LinkedIn Invite", "channel": "linkedin_connect", "enabled": true}
```

### LinkedInSendQueue Fields (existing)
```
id, tenant_id, message_id, contact_id, owner_id,
action_type ('connection_request'|'message'),
linkedin_url, body, status ('queued'|'claimed'|'sent'|'failed'|'skipped'),
claimed_at, sent_at, error, retry_count, created_at
```

---

## Sprint 6A: Template & Queue Foundation (2 days)

### 1. Create "Meetup Dual LinkedIn + Email" system template
- **Priority**: Must Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: None
- **Files**: `api/routes/campaign_routes.py` (system template initialization)
- **Change**: Add system template with 3 steps:
  ```json
  [
    {"step": 1, "label": "LinkedIn Invite Note", "channel": "linkedin_connect", "enabled": true},
    {"step": 2, "label": "LinkedIn Direct Message", "channel": "linkedin_message", "enabled": true},
    {"step": 3, "label": "Follow-up Email", "channel": "email", "enabled": true}
  ]
  ```
- **AC**: Given system templates list, When user creates campaign, Then "Meetup Dual LinkedIn + Email" is available with all 3 steps enabled

---

### 2. Migration 048: Add contact grouping to LinkedInSendQueue
- **Priority**: Must Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: None
- **Files**: `migrations/048_linkedin_queue_contact_group.sql`, `api/models.py`
- **Change**: Add `contact_group_id` (UUID) and `is_primary` (boolean, default true) to `LinkedInSendQueue`. When both invite+DM are queued for same contact, they share a `contact_group_id`. Extension processes the group, not individual items.
- **AC**: Given dual-queued contact, When queried, Then both queue items share the same contact_group_id

---

### 3. Backend: Dual LinkedIn queue grouping logic
- **Priority**: Must Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #1, #2
- **Files**: `api/routes/campaign_routes.py` (`queue_linkedin()`)
- **Change**: When queuing LinkedIn messages, detect contacts with both `linkedin_connect` and `linkedin_message` approved messages. Assign shared `contact_group_id`. Mark `linkedin_connect` as `is_primary=true` (default action if extension can't determine connection status).
- **AC**: Given campaign with dual LinkedIn messages per contact, When queue-linkedin is called, Then each contact's 2 queue items share a group_id

---

### 4. Backend: Extension queue returns grouped pairs
- **Priority**: Must Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #2, #3
- **Files**: `api/routes/extension_routes.py` (`get_linkedin_queue()`)
- **Change**: Modify response format to group paired messages:
  ```json
  {
    "items": [
      {
        "contact_group_id": "uuid",
        "contact_name": "Jan Novak",
        "linkedin_url": "...",
        "actions": {
          "connection_request": {"queue_id": "uuid", "body": "invite text..."},
          "message": {"queue_id": "uuid", "body": "DM text..."}
        }
      }
    ]
  }
  ```
  Falls back to flat format for single-action items (backward compatible).
- **AC**: Given queued items with groups, When extension polls, Then grouped items are returned with both action options

---

### 5. Backend: Mark message as skipped endpoint
- **Priority**: Must Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: None
- **Files**: `api/routes/extension_routes.py`
- **Change**: Extension already has `PATCH /api/extension/linkedin-queue/<queue_id>` with `status: "skipped"`. Verify it works correctly — when one item in a group is sent, the other should be skipped. Add `skipped_reason` field (optional): `"contact_already_connected"` or `"contact_not_connected"`.
- **AC**: Given a grouped queue pair, When extension sends one and skips the other, Then skipped item has status "skipped" with reason

---

### 6. Backend: Send confirmation creates Activity record
- **Priority**: Must Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: None
- **Files**: `api/routes/extension_routes.py` (PATCH handler at line 339)
- **Change**: When extension PATCHes queue item to `status: "sent"`, automatically create an Activity record:
  ```python
  Activity(
      tenant_id=queue_item.tenant_id,
      contact_id=queue_item.contact_id,
      event_type="linkedin_invite_sent" if action_type == "connection_request" else "linkedin_message_sent",
      source="chrome_extension",
      timestamp=now,
      payload={"message_id": str(queue_item.message_id), "campaign_id": str(message.campaign_id)}
  )
  ```
  This eliminates the need for extension to make a separate Activity POST call.
- **AC**: Given extension marks queue item as sent, Then an Activity record is automatically created with correct event_type

---

### 7. Backend: Non-responder identification endpoint
- **Priority**: Must Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #6
- **Files**: `api/routes/campaign_routes.py`
- **Change**: New endpoint `GET /api/campaigns/<id>/non-responders?days=3`:
  1. Find campaign contacts with LinkedIn Activity (`linkedin_*_sent`) older than `days` param
  2. Exclude contacts with any Activity since the send (reply, connection accepted, profile visit)
  3. Exclude contacts with existing EmailSendLog for this campaign
  4. Return list with contact details + days_since_sent
- **AC**: Given campaign 3 days after LinkedIn sends, When called with `?days=3`, Then returns only contacts with no response and no email yet

---

### 8. Backend: ICP filter preset storage and retrieval
- **Priority**: Should Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: None
- **Files**: `api/routes/campaign_routes.py`, `api/models.py`
- **Change**: `target_criteria` field already exists on Campaign (JSONB, migration 037). Add:
  - `GET /api/filter-presets` — list saved presets (stored as tenant-scoped JSON)
  - `POST /api/filter-presets` — save a new preset
  - Seed "Meetup - Prague Leaders" preset for visionvolve tenant
- **AC**: Given saved presets, When creating campaign, Then presets are listable and loadable into target_criteria

---

### 9. Unit tests: Dual queue grouping + non-responder query
- **Priority**: Must Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: #3, #7
- **Files**: `tests/unit/test_campaign_queue.py` (new), `tests/unit/test_non_responder.py` (new)
- **Change**: Tests for:
  - Dual queue creates correct group_id pairing
  - Extension pickup returns grouped format
  - Non-responder query filters correctly (sent >3 days, no response, no email)
  - Non-responder excludes contacts who responded
  - Non-responder excludes contacts already emailed
- **AC**: All tests pass with `make test-changed`

---

## Sprint 6B: Extension Intelligence (3 days)

### 10. Extension: Connection status detection
- **Priority**: Must Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #4
- **Files**: Chrome extension source (outside this repo)
- **Change**: When extension navigates to contact's LinkedIn profile:
  1. Check DOM for connection indicators ("1st", "Connect" button vs "Message" button)
  2. Return connection status: `connected` | `not_connected` | `pending_invite` | `unknown`
  3. Store result locally for the session
- **AC**: Given a LinkedIn profile page, When extension checks connection status, Then it correctly identifies 1st-degree vs non-connected

---

### 11. Extension: Smart routing logic (pick invite vs DM)
- **Priority**: Must Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #4, #10
- **Change**: When processing a grouped queue item:
  1. Navigate to linkedin_url
  2. Check connection status (#10)
  3. If `connected` -> use `message` action, skip `connection_request`
  4. If `not_connected` -> use `connection_request` action, skip `message`
  5. If `unknown` -> use primary action (connection_request as fallback)
  6. PATCH sent item as "sent", PATCH skipped item as "skipped" with reason
- **AC**: Given grouped queue with both actions, When extension processes contact, Then it sends the correct action based on connection status

---

### 12. Extension: Batch processing UI with progress
- **Priority**: Should Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #11
- **Change**: Extension UI shows:
  - Total contacts to process
  - Progress bar (sent / total)
  - Per-contact status (sent invite, sent DM, skipped, failed)
  - Pause/resume controls
  - Rate limiting (configurable delay between sends, default 30s)
- **AC**: Given 50 queued contacts, When user starts batch send, Then extension processes sequentially with progress visibility and rate limiting

---

### 13. Frontend: ICP preset selector in campaign creation
- **Priority**: Should Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: #8
- **Files**: `frontend/src/pages/campaigns/CampaignsPage.tsx` (create dialog)
- **Change**: Add preset dropdown in campaign creation dialog. When preset selected, auto-populate target_criteria and optionally auto-add matching contacts.
- **AC**: Given presets exist, When creating campaign, Then preset dropdown loads criteria and filters contacts

---

### 14. Frontend: OutreachTab shows dual LinkedIn status
- **Priority**: Should Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: #3
- **Files**: `frontend/src/pages/campaigns/tabs/OutreachTab.tsx`
- **Change**: Show separate counts for:
  - LinkedIn Invites: X queued / Y sent / Z skipped
  - LinkedIn DMs: X queued / Y sent / Z skipped
  - Combined: "150 contacts processed, 89 invites sent, 61 DMs sent"
- **AC**: Given campaign with dual LinkedIn messages, When viewing OutreachTab, Then invite and DM counts are shown separately

---

### 15. Frontend: Non-responder panel in OutreachTab
- **Priority**: Must Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #7
- **Files**: `frontend/src/pages/campaigns/tabs/OutreachTab.tsx`
- **Change**: After LinkedIn sends, show "Follow-up" section:
  - "3 days since LinkedIn outreach"
  - "127 contacts with no response"
  - "Send follow-up email to non-responders" button
  - Calls non-responder endpoint, then triggers email send for those contacts
- **AC**: Given campaign 3+ days after LinkedIn, When user views OutreachTab, Then non-responder count is shown with email follow-up button

---

### 16. Backend: Trigger email for specific contacts (subset send)
- **Priority**: Must Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #7
- **Files**: `api/services/send_service.py`, `api/routes/campaign_routes.py`
- **Change**: `send_campaign_emails()` currently sends ALL approved email messages. Add `contact_ids` parameter to send only to specific contacts (the non-responders). New endpoint:
  ```
  POST /api/campaigns/<id>/send-followup-emails
  Body: {"contact_ids": ["uuid1", "uuid2", ...]}
  ```
  Or reuse existing endpoint with filter parameter.
- **AC**: Given non-responder list, When follow-up email triggered with contact_ids, Then only those contacts receive email

---

### 17. Unit tests: Extension grouped pickup, send confirmation, subset email
- **Priority**: Must Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: #4, #6, #16
- **Files**: `tests/unit/test_extension_queue.py` (new), `tests/unit/test_send_service.py` (extend)
- **Change**: Tests for:
  - Grouped pickup endpoint format
  - Send confirmation auto-creates Activity
  - Skip updates status with reason
  - Subset email send filters by contact_ids
- **AC**: All tests pass with `make test-changed`

---

## Sprint 6C: Sequence Automation (4 days)

### 18. Migration 049: CampaignSequenceStep model
- **Priority**: Must Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: None
- **Files**: `migrations/049_campaign_sequence_steps.sql`, `api/models.py`
- **Change**: New table:
  ```sql
  CREATE TABLE campaign_sequence_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    step_number INTEGER NOT NULL,
    channel TEXT NOT NULL,         -- 'linkedin', 'email'
    delay_days INTEGER DEFAULT 0,
    condition TEXT DEFAULT 'always', -- 'always', 'no_response', 'opened_not_replied'
    status TEXT DEFAULT 'pending',  -- 'pending', 'active', 'completed', 'skipped'
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    UNIQUE(campaign_id, step_number)
  );
  ```
- **AC**: Migration runs, model is available, rollback works

---

### 19. Backend: Sequence step CRUD endpoints
- **Priority**: Must Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #18
- **Files**: `api/routes/campaign_routes.py`
- **Change**:
  - `GET /api/campaigns/<id>/sequence` — list steps for campaign
  - `PUT /api/campaigns/<id>/sequence` — replace all steps (bulk upsert)
  - `PATCH /api/campaigns/<id>/sequence/<step_number>` — update single step
  - Auto-populate steps when campaign is created from template (map template steps to sequence steps with default delays)
- **AC**: Given campaign, When sequence endpoints are called, Then steps are created/read/updated correctly

---

### 20. Backend: Auto-create sequence from template
- **Priority**: Must Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: #18, #19
- **Files**: `api/routes/campaign_routes.py` (campaign create logic)
- **Change**: When campaign is created from "Meetup Dual LinkedIn + Email" template, auto-create 2 sequence steps:
  - Step 1: channel=linkedin, delay_days=0, condition=always
  - Step 2: channel=email, delay_days=3, condition=no_response
  Note: LinkedIn step covers both invite+DM (extension decides which).
- **AC**: Given meetup template, When campaign created, Then 2 sequence steps auto-created with correct delays

---

### 21. Backend: Sequence scheduler service
- **Priority**: Must Have | **Effort**: L | **Theme**: Outreach Engine
- **Depends on**: #7, #18, #19
- **Files**: `api/services/sequence_scheduler.py` (new), `api/__init__.py` (register scheduler)
- **Change**: APScheduler job running every 4 hours:
  1. Find campaigns with `status=approved` and sequence steps with `status=pending`
  2. For each pending step where `delay_days` has elapsed since previous step's `started_at`
  3. Check condition:
     - `always` -> execute for all contacts
     - `no_response` -> call non-responder logic (#7) to get eligible contacts
  4. If `channel=email` -> call `send_campaign_emails()` with filtered contact_ids (#16)
  5. Update step status to `completed` with timestamp
  6. Log execution to Campaign activity
- **AC**: Given campaign with Step 2 (email, delay 3d, no_response), When scheduler runs 3+ days after Step 1, Then emails sent to non-responders only and step marked completed

---

### 22. Backend: Manual sequence step trigger
- **Priority**: Should Have | **Effort**: S | **Theme**: Outreach Engine
- **Depends on**: #21
- **Files**: `api/routes/campaign_routes.py`
- **Change**: `POST /api/campaigns/<id>/sequence/<step_number>/execute` — manually trigger a step regardless of delay. Useful for: "I don't want to wait 3 days, trigger email now."
- **AC**: Given pending step, When manually triggered, Then step executes immediately with same logic as scheduler

---

### 23. Frontend: Sequence step editor in campaign settings
- **Priority**: Should Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #19
- **Files**: `frontend/src/pages/campaigns/tabs/SettingsTab.tsx`
- **Change**: New "Sequence" section in campaign settings:
  - Timeline visualization of steps (Step 1: LinkedIn Day 0 -> Step 2: Email Day 3)
  - Editable delay_days per step
  - Condition selector (always, no_response, opened_not_replied)
  - Add/remove steps
- **AC**: Given campaign with sequence, When user edits settings, Then steps are visualized and editable

---

### 24. Frontend: Sequence funnel view in OutreachTab
- **Priority**: Should Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #19, #21
- **Files**: `frontend/src/pages/campaigns/tabs/OutreachTab.tsx`
- **Change**: Replace flat outreach stats with sequence-aware funnel:
  ```
  Step 1: LinkedIn (Day 0)     ████████████████████ 150 sent
    ├── Responded               ████               23 (15%)
    └── No Response             ████████████████   127 (85%)

  Step 2: Email (Day 3)        ████████████████   127 sent
    ├── Opened                  ████████████       89 (70%)
    ├── Replied                 ██                 12 (9%)
    └── No Open                 ████               38 (30%)
  ```
  Drill-down: click on any segment to see contact list.
- **AC**: Given running campaign with sequence, When viewing OutreachTab, Then funnel shows per-step metrics with drill-down

---

### 25. Unit tests: Sequence model, scheduler, manual trigger
- **Priority**: Must Have | **Effort**: M | **Theme**: Outreach Engine
- **Depends on**: #18, #21, #22
- **Files**: `tests/unit/test_sequence.py` (new)
- **Change**: Tests for:
  - Sequence step creation from template
  - Scheduler identifies eligible steps correctly
  - Condition evaluation (always vs no_response)
  - Manual trigger bypasses delay
  - Step status transitions
  - Edge cases: no contacts eligible, campaign cancelled mid-sequence
- **AC**: All tests pass with `make test-changed`

---

## Dependency Graph

```
Sprint 6A — Template & Queue Foundation
  [1] System template ──┐
  [2] Migration 048 ────┤──→ [3] Queue grouping ──→ [4] Grouped pickup
  [8] Filter presets    │                                    │
                        │    [5] Skip endpoint (standalone)  │
                        │    [6] Send confirmation ──→ [7] Non-responder API
                        └──→ [9] Tests

Sprint 6B — Extension Intelligence
  [10] Connection detect ──→ [11] Smart routing ──→ [12] Batch UI
  [13] FE: ICP presets
  [14] FE: Dual LinkedIn status
  [15] FE: Non-responder panel ──→ [16] Backend: Subset email send
  [17] Tests

Sprint 6C — Sequence Automation
  [18] Migration 049 ──→ [19] Step CRUD ──→ [20] Auto-create from template
                                │
                                └──→ [21] Scheduler ──→ [22] Manual trigger
                                │
                                └──→ [23] FE: Step editor
                                     [24] FE: Funnel view
                                     [25] Tests
```

## Sprint Sizing

| Sprint | Items | Scope | Effort | Duration |
|--------|-------|-------|--------|----------|
| 6A | #1-#9 (9 items) | Backend foundation: template, queue grouping, non-responder, presets, tests | 2x S + 3x M + 4x S = ~5 dev-days | 2-3 days (2 engineers) |
| 6B | #10-#17 (8 items) | Extension + frontend: smart routing, dual status, follow-up UI, subset send | 3x M + 3x S + 1x M + 1x S = ~5 dev-days | 3 days (2 engineers) |
| 6C | #18-#25 (8 items) | Automation: sequence model, scheduler, editor, funnel, tests | 1x L + 2x M + 2x S + 2x M + 1x M = ~7 dev-days | 4 days (2 engineers) |

## What You Can Do at Each Sprint Boundary

**After Sprint 6A**: Create meetup campaign with dual template, generate all 3 message types per contact, queue both LinkedIn types grouped. Manually trigger email for non-responders via API.

**After Sprint 6B**: Extension intelligently picks invite vs DM, sends batch with progress. Dashboard shows non-responders with one-click email follow-up button. Full manual flow works end-to-end.

**After Sprint 6C**: Fully automated: create campaign, trigger LinkedIn, scheduler auto-sends email to non-responders after 3 days. Dashboard shows sequence funnel metrics.

## Key File References

| Capability | File(s) |
|---|---|
| Message generation | `api/services/message_generator.py` — `_generate_all()`, `_generate_single_message()` |
| Generation prompts | `api/services/generation_prompts.py` — `build_generation_prompt()` |
| LinkedIn queue | `api/routes/campaign_routes.py:2223` — `queue_linkedin()` |
| Extension queue pickup | `api/routes/extension_routes.py:261` — `get_linkedin_queue()` |
| Extension status update | `api/routes/extension_routes.py:339` — PATCH handler |
| Extension activities | `api/routes/extension_routes.py:113` — `upload_activities()` |
| Email send service | `api/services/send_service.py` — `send_campaign_emails()` |
| Campaign templates | `api/routes/campaign_routes.py` — system template init |
| Contact filtering | `api/routes/contact_routes.py` — `list_contacts()`, `search_contacts()` |
| Outreach UI | `frontend/src/pages/campaigns/tabs/OutreachTab.tsx` |
| Campaign detail | `frontend/src/pages/campaigns/CampaignDetailPage.tsx` |
| Models | `api/models.py` — Campaign, CampaignContact, Message, LinkedInSendQueue, EmailSendLog, Activity |
| Latest migration | `migrations/047_iam_integration.sql` |
