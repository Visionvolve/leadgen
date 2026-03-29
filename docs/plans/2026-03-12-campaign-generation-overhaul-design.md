# Campaign Message Generation Overhaul — Design

## Problem

Currently campaign generation steps can only be added via templates (`CampaignTemplate.steps` JSONB). Users need:

1. **Blank slate** — build step sequences from scratch
2. **Agent-designed** — AI proposes steps based on campaign goal, user reviews/edits
3. **Per-step configuration** — example messages (few-shot), length limits, tone, custom instructions, attachable assets (JPG/PDF)
4. **Learning loop** — user edits/approvals/rejections feed back into future generation quality
5. **LinkedIn account tracking** — extension detects logged-in user, campaigns specify which account for outreach

## Approach: Hybrid (Relational Steps + JSONB Config)

Relational `CampaignStep` for queryable structure (ordering, channel, timing). JSONB `config` per step for extensible generation params (examples, tone, assets). Dedicated `MessageFeedback` table for learning signals.

## Data Model

### New Tables

#### `campaign_step`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `campaign_id` | FK → campaigns | |
| `tenant_id` | FK → tenants | |
| `position` | int | ordering (1, 2, 3...) |
| `channel` | enum | linkedin_connect, linkedin_message, email, call |
| `day_offset` | int | days after previous step (0 = same day) |
| `label` | varchar | user-visible name, e.g. "Connection request" |
| `config` | JSONB | see schema below |

`config` JSONB schema:

```json
{
  "max_length": 300,
  "tone": "informal",
  "language": "en",
  "custom_instructions": "mention their recent funding",
  "example_messages": [
    {"body": "Hey {{first_name}}, saw your talk at...", "note": "casual opener"},
    {"body": "Hi {{first_name}}, your work on..."}
  ],
  "asset_ids": ["uuid1", "uuid2"],
  "asset_mode": {"uuid1": "attach", "uuid2": "reference"}
}
```

#### `asset`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `tenant_id` | FK → tenants | |
| `campaign_id` | FK → campaigns (nullable) | null = shared/tenant-wide asset |
| `filename` | varchar | original filename |
| `content_type` | varchar | image/jpeg, application/pdf |
| `storage_path` | varchar | S3 key |
| `size_bytes` | int | |
| `metadata` | JSONB | dimensions, page count, AI-extracted summary |
| `created_at` | timestamp | |

#### `message_feedback`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `message_id` | FK → messages | |
| `campaign_id` | FK → campaigns | denormalized for fast queries |
| `action` | enum | approved, rejected, edited, regenerated |
| `edit_diff` | JSONB | `{field: "body", before: "...", after: "..."}` |
| `edit_reason` | varchar | reuses existing 10 edit reasons |
| `edit_reason_text` | text | free-form |
| `created_at` | timestamp | |

#### `linkedin_account` (BL-091 — being built separately)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `tenant_id` | FK → tenants | |
| `owner_id` | FK → owners | |
| `linkedin_name` | varchar | display name from LinkedIn |
| `linkedin_url` | varchar | profile URL (unique per tenant) |
| `last_seen_at` | timestamp | |
| `is_active` | boolean | |

### Changes to Existing Tables

- **`messages`**: add `campaign_step_id` FK → campaign_step
- **`campaigns`**: add `linkedin_account_id` FK → linkedin_account (which account sends outreach)
- **`campaign_templates`**: `steps` JSONB stays as export/import format — runtime uses `campaign_step` rows

## API Design

### Campaign Steps CRUD

| Method | Endpoint | Notes |
|--------|----------|-------|
| `GET` | `/api/campaigns/{id}/steps` | Returns ordered steps with config |
| `POST` | `/api/campaigns/{id}/steps` | Add step (position auto-incremented or specified) |
| `PATCH` | `/api/campaigns/{id}/steps/{step_id}` | Update step config, channel, timing, label |
| `PUT` | `/api/campaigns/{id}/steps/reorder` | Accepts `[{id, position}]` array |
| `DELETE` | `/api/campaigns/{id}/steps/{step_id}` | Remove step, reorder remaining |
| `POST` | `/api/campaigns/{id}/steps/from-template` | Populate steps from template (clears existing) |
| `POST` | `/api/campaigns/{id}/steps/ai-design` | Agent designs steps, returns proposal (not saved until confirmed) |
| `POST` | `/api/campaigns/{id}/steps/ai-design/confirm` | Accept agent proposal, saves steps |

### Assets

| Method | Endpoint | Notes |
|--------|----------|-------|
| `POST` | `/api/assets/upload` | Multipart upload → S3, returns asset record |
| `GET` | `/api/assets` | List tenant assets (filterable by campaign_id) |
| `GET` | `/api/assets/{id}/download` | Presigned S3 URL redirect |
| `DELETE` | `/api/assets/{id}` | Remove asset + S3 object |

### AI Step Designer Flow

1. `POST /steps/ai-design` with `{goal, channel_preference, num_steps, context}`
2. Backend calls Claude with: campaign contacts summary, strategy doc, previous campaign performance (from message_feedback), user's goal
3. Returns `{proposal_id, steps: [{channel, day_offset, label, config}], reasoning: "..."}`
4. User reviews in UI, edits if needed
5. `POST /steps/ai-design/confirm` with `{proposal_id, steps: [edited steps]}` → saves to DB

### Message Generation Changes

`POST /api/campaigns/{id}/generate` now:

- Reads from `campaign_step` rows instead of `template_config` JSONB
- Per step: injects `example_messages` as few-shot in the prompt
- Respects `max_length` from step config
- Attaches assets marked as "reference" to prompt context (AI-extracted summary from `asset.metadata`)
- Sets `campaign_step_id` on generated messages

### Learning Feedback

- Existing `PATCH /api/messages/{id}` already captures `edit_reason` + stores `original_body`
- Auto-insert into `message_feedback` on every message status change (approve, reject, edit, regenerate)
- New: `GET /api/campaigns/{id}/feedback-summary` — aggregated signals (top edit reasons, most-edited steps, approval rate per step)
- AI designer references feedback from previous campaigns when proposing new steps

## UI Design

### Step Builder (CampaignDetailPage → new "Steps" tab)

Three modes at top:

- Start from scratch (blank)
- Use template (dropdown)
- Let AI design steps (text input for goal)

Steps render as ordered cards:

```
+--- Step 1 ------------------------------------------ x --+
| * LinkedIn Connect  . Day 0                               |
| Max: 300 chars . Tone: informal                           |
| Examples: 2 added  . Assets: case-study.pdf               |
| [Edit config v]                                           |
+-----------------------------------------------------------+
```

Expandable config per step:

- Channel selector + day offset
- Max length slider (channel defaults: LI connect=300, LI message=1900, email=unlimited)
- Tone (formal/informal) + language
- Custom instructions textarea
- Example messages: add/remove text blocks with optional note
- Assets: upload or pick existing, toggle attach vs reference per asset

Bottom actions: [+ Add Step] [Save as Template] [Generate Messages →]

Campaign header shows: LinkedIn account selector (from linkedin_accounts), contact count, step count

### AI Design Flow

1. User selects "Let AI design steps"
2. Types goal: "3-step LinkedIn outreach for SaaS CTOs, mention case study"
3. Spinner → agent returns proposed steps with reasoning
4. Steps render as editable cards (same UI as manual)
5. User tweaks → clicks "Accept & Save"

### Learning Indicators

- Review tab: badge per step showing approval rate + top edit reasons
- New campaign creation: AI designer references stats ("Step 2 had high edit rate for tone — adjusting to informal")

## File Storage

- S3 bucket: `leadgen-assets-{env}` (staging/production)
- Path: `{tenant_id}/{campaign_id}/{asset_id}/{filename}`
- Max file size: 10MB
- Allowed types: image/jpeg, image/png, application/pdf
- Presigned URLs for download (1hr expiry)
- Upload via multipart form to API → API streams to S3

## Implementation Phases

### Phase 1: Step Builder + Examples + Length Limits (v1)

- Migration: campaign_step table
- API: steps CRUD endpoints
- UI: step builder tab with manual add/edit/reorder
- Generation: read from campaign_step instead of template_config
- Per-step: example_messages + max_length in prompt

### Phase 2: Assets + File Storage

- Migration: asset table
- S3 integration (upload, download, presigned URLs)
- API: asset CRUD
- UI: asset upload/picker per step, attach vs reference toggle
- Generation: include reference asset summaries in prompt
- Email send: attach assets to outbound emails

### Phase 3: AI Step Designer

- AI design endpoint (Claude call with campaign context + strategy + feedback)
- Proposal review UI
- Previous campaign performance as input
- UI: "Let AI design steps" mode

### Phase 4: Learning Loop

- Migration: message_feedback table
- Auto-capture feedback on message status changes
- Feedback summary endpoint + UI badges
- Feed signals into generation prompts (few-shot from approved messages, avoid patterns from rejected ones)
- AI designer uses feedback when proposing new campaigns
