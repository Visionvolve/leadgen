# EventFest Campaign Outreach Workflow

**Created**: 2026-04-13
**Status**: Spec'd
**Target send date**: Monday 2026-04-21 (event: April 22)
**Campaign**: United Arts / Losers Cirque → EventFest partner invite
**Sender**: hana@unitedarts.cz via Resend (reply_to: hana@unitedarts.cz → her Gmail)

---

## Purpose

Enable a one-shot styled email campaign for EventFest (April 22) that:
1. Sends branded HTML emails from hana@unitedarts.cz via Resend
2. Generates unique microsite invite links per contact (ua-microsite /api/invites)
3. Tracks the full funnel: Sent → Delivered → Opened → Clicked → Visited Microsite → Viewed Products
4. Feeds microsite behavioral data (PostHog + custom webhook) back into leadgen for campaign-level reporting

This is NOT a sequence campaign. It is a single email blast with deep tracking across two systems (leadgen + ua-microsite).

---

## Requirements

### Must Have

1. **Resend domain verification for unitedarts.cz** — generate SPF/DKIM DNS records via Resend API, provide to Hana's team, verify domain status before send
2. **Resend webhook handler** — receive email.delivered / email.opened / email.clicked / email.bounced events, update EmailSendLog
3. **EventFest HTML email template** — styled with UA/Losers Cirque branding, Czech vocative name, microsite invite button
4. **Microsite invite link generation** — for each contact, call ua-microsite /api/invites to get/create a unique partner link; store invite token
5. **Microsite → leadgen activity webhook** — microsite POSTs partner engagement events to leadgen; leadgen stores in activities table
6. **Enhanced campaign analytics** — full-funnel view: email metrics + microsite engagement per contact

### Should Have

7. **Deterministic Czech vocative lookup** — replace LLM-generated vocative with a reliable lookup table for common Czech names (avoids hallucination risk in the template variable)
8. **Per-contact timeline** — contact history tab shows email events + microsite visits as a unified timeline

### Could Have

9. **PostHog API integration** — query PostHog for deep behavioral analytics (scroll depth, video play, session duration) and display in campaign dashboard
10. **Bounce handling automation** — auto-mark contacts with hard bounces as invalid_email

---

## Acceptance Criteria

### AC-1: Domain Verification
- **Given** Resend API key is configured in tenant settings
- **When** admin triggers domain verification for unitedarts.cz
- **Then** the system returns SPF and DKIM DNS records to add, and a status endpoint shows verification progress (pending → verified)

### AC-2: Webhook Processing
- **Given** Resend is configured with webhook URL pointing to /api/webhooks/resend
- **When** Resend sends an email.opened event with a valid signature
- **Then** the matching EmailSendLog row is updated: opened_at = event timestamp, open_count incremented
- **When** Resend sends an email.clicked event
- **Then** clicked_at and click_count are updated
- **When** Resend sends an email.bounced event
- **Then** bounced_at is set, bounce_type is recorded, status changes to "bounced"
- **When** Resend sends an email.delivered event
- **Then** delivered_at is set, status changes to "delivered"
- **When** the webhook signature is invalid
- **Then** the request is rejected with 401

### AC-3: Email Template Rendering
- **Given** a contact named "Jana Novakova" with an invite token "abc123"
- **When** the template is rendered
- **Then** the greeting uses vocative "Jano", the invite button links to {MICROSITE_URL}/invite/abc123, and the HTML passes email client rendering (no broken images, proper responsive layout)

### AC-4: Invite Link Generation
- **Given** a campaign with 50 contacts
- **When** the send flow is triggered
- **Then** for each contact, a unique invite link is created via ua-microsite /api/invites (idempotent by email), and the invite token is stored in campaign_contacts.metadata

### AC-5: Microsite Activity Webhook
- **Given** a partner (contact) visits the microsite and views a product
- **When** the microsite POSTs a product_viewed event to leadgen /api/tracking/partner-event
- **Then** an Activity record is created linked to the contact, visible in campaign analytics and contact history

### AC-6: Full-Funnel Analytics
- **Given** a campaign with sent emails and microsite visits
- **When** viewing campaign analytics
- **Then** the funnel shows: Sent → Delivered → Opened → Clicked → Visited Microsite → Viewed Products with conversion rates at each stage

---

## UX / Design

### Email Template

The email is a single-column responsive HTML email (600px max-width) with:
- UA/Losers Cirque header logo
- Personal Czech greeting with vocative name
- Short body text about EventFest
- Styled CTA button linking to microsite invite
- Hanka's signature with role and UA branding
- Footer with unsubscribe link

### Campaign Dashboard Enhancement

The existing campaign analytics page (`GET /api/campaigns/<id>/analytics`) is extended with:
- A "Microsite Engagement" section below email metrics
- Per-contact expansion showing: email status + microsite visit count + products viewed
- Funnel visualization (numbers + bars, not a chart library — keep it lightweight)

---

## Technical Design

### 1. Resend Domain Verification

**New endpoint**: `POST /api/admin/resend/verify-domain`

```
Request:
  { "domain": "unitedarts.cz" }

Response (201):
  {
    "domain_id": "d_abc123",
    "status": "pending",
    "dns_records": [
      { "type": "TXT", "name": "unitedarts.cz", "value": "v=spf1 include:amazonses.com ~all" },
      { "type": "CNAME", "name": "resend._domainkey.unitedarts.cz", "value": "..." },
      { "type": "CNAME", "name": "..." , "value": "..." }
    ]
  }
```

**New endpoint**: `GET /api/admin/resend/domain-status?domain=unitedarts.cz`

```
Response (200):
  { "domain": "unitedarts.cz", "status": "verified" | "pending" | "failed" }
```

Implementation: thin wrapper around Resend SDK `resend.Domains.create()` and `resend.Domains.get()`. Super-admin only.

### 2. Resend Webhook Handler

**New endpoint**: `POST /api/webhooks/resend`

No auth header — uses Resend webhook signature verification (svix library).

```
Request (from Resend):
  Headers:
    svix-id: msg_xxx
    svix-timestamp: 1234567890
    svix-signature: v1,xxx
  Body:
    {
      "type": "email.opened",
      "data": {
        "email_id": "re_xxx",
        "created_at": "2026-04-21T10:00:00Z"
      }
    }
```

**Handling logic:**

| Event Type | EmailSendLog Update |
|---|---|
| email.delivered | status = "delivered", delivered_at = event timestamp |
| email.opened | opened_at = min(existing, event timestamp), open_count += 1 |
| email.clicked | clicked_at = min(existing, event timestamp), click_count += 1 |
| email.bounced | status = "bounced", bounced_at = event timestamp, bounce_type = data.bounce.type |
| email.complained | status = "complained" (new status value) |

Lookup: match `data.email_id` to `EmailSendLog.resend_message_id`.

**Signature verification**: Use `svix` Python package to verify webhook signatures. The webhook signing secret is stored in tenant settings as `resend_webhook_secret`.

**New file**: `api/routes/webhook_routes.py`

**Registration**: Add blueprint to `api/__init__.py`

### 3. EventFest Email Template

The template is stored as the campaign step body (CampaignStep.config.body_html). Variables are replaced at send time.

**Variable placeholders** (double-brace syntax, replaced by send_service before sending):

| Variable | Source |
|---|---|
| `{{vocative_name}}` | Deterministic vocative lookup from contact.first_name |
| `{{microsite_link}}` | `{MICROSITE_URL}/invite/{token}` from campaign_contacts.metadata.invite_token |
| `{{first_name}}` | contact.first_name (nominative, for signature area if needed) |

**Czech email text** (copy for the template):

```
Subject: Pozvánka na EventFest — speciální nabídka od United Arts

Body:

Dobrý den, {{vocative_name}},

ráda bych Vás pozvala na EventFest, který se koná už zítra, 22. dubna.

United Arts a Losers Cirque Company připravili speciální nabídku vystoupení
a zážitků pro Vaši firemní akci nebo event. Vybrali jsme to nejlepší
z našeho portfolia — od akrobatických show přes moderování až po unikátní
team-buildingové formáty.

Podívejte se na naši nabídku:

[CTA BUTTON: Prohlédnout nabídku → {{microsite_link}}]

Pokud Vás cokoliv zaujme nebo budete chtít probrat možnosti spolupráce,
ozvěte se mi — ráda vše doladíme na míru.

S pozdravem,
Hanka Faková
United Arts | Losers Cirque Company
hana@unitedarts.cz
```

**HTML structure** (inline CSS for email client compatibility):

```html
<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pozvánka na EventFest</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f4;font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f4;">
    <tr>
      <td align="center" style="padding:24px 16px;">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0"
               style="background-color:#ffffff;border-radius:8px;overflow:hidden;max-width:600px;width:100%;">

          <!-- HEADER: UA + Losers Cirque logo bar -->
          <tr>
            <td style="background-color:#1a1a2e;padding:24px 32px;text-align:center;">
              <!-- Logo served from microsite CDN or inline base64 -->
              <img src="https://demo.visionvolve.com/images/ua-logo-white.png"
                   alt="United Arts × Losers Cirque Company"
                   width="280" style="display:block;margin:0 auto;max-width:280px;height:auto;">
            </td>
          </tr>

          <!-- BODY -->
          <tr>
            <td style="padding:32px 32px 16px 32px;color:#333333;font-size:15px;line-height:1.6;">
              <p style="margin:0 0 16px 0;">
                Dobrý den, {{vocative_name}},
              </p>
              <p style="margin:0 0 16px 0;">
                ráda bych Vás pozvala na <strong>EventFest</strong>, který se koná už zítra,
                <strong>22.&nbsp;dubna</strong>.
              </p>
              <p style="margin:0 0 16px 0;">
                United Arts a Losers Cirque Company připravili speciální nabídku vystoupení
                a&nbsp;zážitků pro Vaši firemní akci nebo event. Vybrali jsme to nejlepší
                z&nbsp;našeho portfolia&nbsp;— od akrobatických show přes moderování
                až po unikátní team-buildingové formáty.
              </p>
              <p style="margin:0 0 24px 0;">
                Podívejte se na naši nabídku:
              </p>
            </td>
          </tr>

          <!-- CTA BUTTON -->
          <tr>
            <td align="center" style="padding:0 32px 32px 32px;">
              <a href="{{microsite_link}}"
                 target="_blank"
                 style="display:inline-block;background-color:#e63946;color:#ffffff;
                        font-size:16px;font-weight:bold;text-decoration:none;
                        padding:14px 32px;border-radius:6px;
                        mso-padding-alt:14px 32px;">
                Prohlédnout nabídku&nbsp;→
              </a>
            </td>
          </tr>

          <!-- CLOSING -->
          <tr>
            <td style="padding:0 32px 32px 32px;color:#333333;font-size:15px;line-height:1.6;">
              <p style="margin:0 0 16px 0;">
                Pokud Vás cokoliv zaujme nebo budete chtít probrat možnosti spolupráce,
                ozvěte se mi&nbsp;— ráda vše doladíme na&nbsp;míru.
              </p>
              <p style="margin:0 0 0 0;">
                S&nbsp;pozdravem,<br>
                <strong>Hanka Faková</strong><br>
                <span style="color:#666666;font-size:13px;">
                  United Arts | Losers Cirque Company<br>
                  hana@unitedarts.cz
                </span>
              </p>
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td style="background-color:#f8f8f8;padding:16px 32px;
                       font-size:11px;color:#999999;text-align:center;
                       border-top:1px solid #eeeeee;">
              United Arts s.r.o. | Praha, Česká republika<br>
              <a href="mailto:hana@unitedarts.cz?subject=unsubscribe"
                 style="color:#999999;text-decoration:underline;">Odhlásit se</a>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
```

### 4. Template Variable Replacement in Send Flow

Modify `send_service.py` to support template variable replacement before sending.

**New function** in `api/services/send_service.py`:

```python
def _replace_template_variables(html: str, variables: dict) -> str:
    """Replace {{variable}} placeholders in email HTML."""
    for key, value in variables.items():
        html = html.replace("{{" + key + "}}", value or "")
    return html
```

**Send flow change**: Before calling `_send_single_email`, build variables dict from contact + campaign_contact metadata, then call `_replace_template_variables` on the body.

### 5. Deterministic Czech Vocative Lookup

**New file**: `api/services/czech_vocative.py`

A lookup table + rule-based fallback for Czech first-name vocative forms. Covers the ~200 most common Czech names. Falls back to nominative if no rule matches.

```python
# Feminine names: -a → -o (most common), -ka → -ko, etc.
# Masculine names: consonant → +e, -ek → -ku, etc.
VOCATIVE_MAP = {
    "jana": "Jano", "hana": "Hanko", "petra": "Petro",
    "martin": "Martine", "petr": "Petře", "jakub": "Jakube",
    # ... ~200 entries
}

def get_vocative(first_name: str) -> str:
    """Return Czech vocative form of a first name.
    Falls back to nominative if unknown."""
    if not first_name:
        return ""
    lookup = VOCATIVE_MAP.get(first_name.lower().strip())
    if lookup:
        return lookup
    # Rule-based fallback for common patterns
    return _apply_rules(first_name)
```

This replaces the LLM-generated vocative for template variables. The LLM vocative in generation_prompts.py remains for free-text message generation.

### 6. Microsite Invite Integration (Campaign Send Flow)

**Modified flow** in `send_campaign_emails()`:

Before sending each email:
1. Check if `campaign_contact.metadata` already has `invite_token` (idempotent)
2. If not, call ua-microsite `POST /api/invites`:
   ```
   POST https://demo.visionvolve.com/api/invites
   Headers: { "x-api-key": INVITE_API_KEY }
   Body: {
     "email": contact.email_address,
     "name": contact.first_name + " " + contact.last_name,
     "company": contact.company_name
   }
   Response: { "token": "abc123", "url": "/invite/abc123" }
   ```
3. Store `invite_token` in `campaign_contact.metadata` (JSONB)
4. Build `microsite_link` = `https://demo.visionvolve.com/invite/{token}`

**Config**: `MICROSITE_URL` and `INVITE_API_KEY` stored in tenant settings (or env vars).

### 7. Microsite → Leadgen Activity Webhook

**New endpoint**: `POST /api/tracking/partner-event`

```
Request:
  Headers:
    x-api-key: {TRACKING_API_KEY}
  Body:
    {
      "event": "product_viewed" | "invite_redeemed" | "page_viewed" | "video_played",
      "email": "jana@example.com",
      "timestamp": "2026-04-21T14:30:00Z",
      "properties": {
        "product_id": "123",
        "product_name": "Akrobatická show",
        "page_url": "/products/akrobaticka-show",
        "duration_seconds": 45
      }
    }

Response (200):
  { "ok": true, "activity_id": "uuid" }

Response (404):
  { "error": "contact_not_found", "email": "..." }
```

**Logic**:
1. Look up contact by email_address within the tenant
2. Create Activity record:
   - `event_type` = event name (e.g. "microsite_product_viewed")
   - `source` = "ua_microsite"
   - `activity_detail` = JSON-serialized properties
   - `contact_id` = matched contact
3. If contact has an active campaign, also link to campaign via activity payload

**Auth**: API key verification (shared secret between microsite and leadgen).

**New file**: `api/routes/tracking_routes.py`

**Microsite-side change** (in /Users/michal/git/ua-microsite):
- Add a webhook dispatch in the invite redemption and product view handlers
- POST to `{LEADGEN_API_URL}/api/tracking/partner-event` with the event data
- Fire-and-forget (async, don't block the user experience)
- Configure via env var: `LEADGEN_WEBHOOK_URL`, `LEADGEN_TRACKING_KEY`

### 8. Enhanced Campaign Analytics

**Modified endpoint**: `GET /api/campaigns/<id>/analytics`

Add to the existing response:

```json
{
  "email_funnel": {
    "sent": 48,
    "delivered": 47,
    "opened": 31,
    "clicked": 18,
    "bounced": 1
  },
  "microsite_funnel": {
    "visited": 15,
    "products_viewed": 42,
    "unique_viewers": 12,
    "avg_session_seconds": 95
  },
  "conversion_rates": {
    "delivery_rate": 0.979,
    "open_rate": 0.660,
    "click_rate": 0.383,
    "visit_rate": 0.319,
    "product_view_rate": 0.255
  },
  "per_contact": [
    {
      "contact_id": "uuid",
      "contact_name": "Jana Novakova",
      "email_status": "opened",
      "opened_at": "2026-04-21T10:15:00Z",
      "clicked_at": "2026-04-21T10:16:00Z",
      "microsite_visits": 2,
      "products_viewed": ["Akrobatická show", "Moderování"]
    }
  ]
}
```

Microsite data comes from Activity records with `source = "ua_microsite"`.

---

## Data Model Changes

### Migration 058: Resend webhooks + tracking

```sql
-- 1. Add webhook-related columns to email_send_log (if not present from migration 041)
-- opened_at, open_count, clicked_at, click_count, bounced_at, bounce_type already exist.
-- Add:
ALTER TABLE email_send_log ADD COLUMN IF NOT EXISTS complained_at TIMESTAMP WITH TIME ZONE;

-- 2. Add event_type to activities for structured event tracking
-- (activity_type exists but is legacy 'message'/'event' enum)
ALTER TABLE activities ADD COLUMN IF NOT EXISTS event_type TEXT;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS payload JSONB;

-- 3. Index for webhook lookups by resend_message_id
CREATE INDEX IF NOT EXISTS idx_email_send_log_resend_msg_id
  ON email_send_log (resend_message_id) WHERE resend_message_id IS NOT NULL;

-- 4. Index for microsite activity lookups
CREATE INDEX IF NOT EXISTS idx_activities_source_event
  ON activities (source, event_type) WHERE source IS NOT NULL;

-- 5. Index for contact email lookups (used by tracking webhook)
CREATE INDEX IF NOT EXISTS idx_contacts_email_tenant
  ON contacts (tenant_id, email_address) WHERE email_address IS NOT NULL;
```

### No new tables needed

- EmailSendLog already has all engagement tracking columns
- Activity already supports contact-linked events
- campaign_contacts.metadata (JSONB) stores invite_token — no schema change needed

---

## New Files

| File | Purpose |
|---|---|
| `api/routes/webhook_routes.py` | Resend webhook handler (POST /api/webhooks/resend) |
| `api/routes/tracking_routes.py` | Microsite activity webhook (POST /api/tracking/partner-event) |
| `api/services/czech_vocative.py` | Deterministic Czech vocative name lookup |
| `migrations/058_eventfest_tracking.sql` | Indexes + minor column additions |

### Modified Files

| File | Change |
|---|---|
| `api/__init__.py` | Register webhook_routes and tracking_routes blueprints |
| `api/models.py` | Add event_type, payload columns to Activity; complained_at to EmailSendLog |
| `api/services/send_service.py` | Template variable replacement, microsite invite creation pre-send |
| `api/routes/campaign_routes.py` | Enhanced analytics response with microsite funnel data |
| `api/routes/admin_routes.py` | Domain verification endpoints (or new admin blueprint) |

---

## Edge Cases

1. **Contact has no email** — skip silently (existing validation in send_service handles this)
2. **Microsite /api/invites is down** — retry once, then send email without invite link (use fallback URL to microsite homepage). Log warning.
3. **Duplicate webhook events** — Resend may send the same event multiple times. opened_at uses min() to keep first open time; open_count always increments (accept minor over-count vs. complexity of dedup)
4. **Contact email not found in tracking webhook** — return 404, log for investigation. Microsite should handle gracefully (fire-and-forget).
5. **Domain not verified by send date** — block send with clear error: "Domain unitedarts.cz is not verified. Cannot send." Check domain status in pre-send validation.
6. **Vocative lookup miss** — fall back to nominative (base) form. "Dobrý den, Jordan" is better than "Dobrý den, Jordane" (wrong guess).
7. **Contact already has invite_token** — idempotent: reuse existing token, don't create duplicate invite.
8. **Webhook signature verification fails** — return 401, do not process. Log the attempt for security monitoring.

---

## Security

- **Resend webhook signature verification** — mandatory. Use svix library to verify the `svix-signature` header against the webhook signing secret. Reject unsigned/invalid requests.
- **Tracking webhook API key** — shared secret between microsite and leadgen. Stored in env, not in code.
- **Domain verification endpoints** — super_admin only (existing auth middleware).
- **No PII in logs** — log email IDs and contact IDs, never email addresses or names.
- **INVITE_API_KEY** — stored in tenant settings or env var, never committed to source.
- **Rate limiting on tracking endpoint** — basic rate limit (100 req/min per IP) to prevent abuse.

---

## Testing Strategy

### Unit Tests

| Test File | Coverage |
|---|---|
| `tests/unit/test_czech_vocative.py` | Comprehensive Czech name vocative conversion: feminine -a→-o, masculine consonant+e, -ek→-ku, -ie stays, edge cases (empty, unknown, non-Czech names) |
| `tests/unit/test_resend_webhook.py` | Webhook signature verification (valid, invalid, missing), each event type updates correct EmailSendLog fields, unknown resend_message_id returns 200 (idempotent), duplicate event handling |
| `tests/unit/test_template_rendering.py` | Variable replacement (all vars, missing vars, empty values), HTML structure preserved after replacement |
| `tests/unit/test_tracking_webhook.py` | Valid event creates Activity, unknown email returns 404, invalid API key returns 401, all event types handled |
| `tests/unit/test_invite_generation.py` | Invite creation for new contact, idempotent for existing, microsite API failure fallback |

### Integration Tests

- **Mock Resend API** → send email → verify EmailSendLog created → mock webhook → verify engagement columns updated
- **Mock microsite /api/invites** → verify invite token stored in campaign_contacts.metadata
- **Analytics endpoint** → seed email logs + activity records → verify funnel numbers correct

### E2E Test (Sprint Completion)

Full flow against staging:
1. Create campaign with EventFest template
2. Add 3 test contacts
3. Generate invite links (mock or real microsite staging)
4. Send emails (Resend test mode or real staging domain)
5. Simulate webhook events (curl POST to /api/webhooks/resend)
6. Simulate microsite events (curl POST to /api/tracking/partner-event)
7. Verify analytics show complete funnel

### Pre-Send Smoke Test (CRITICAL — before Monday)

Manual checklist before the real send:
- [ ] unitedarts.cz domain verified in Resend
- [ ] Test email to hana@unitedarts.cz renders correctly in Gmail
- [ ] Test email to a second address renders correctly in Outlook/Apple Mail
- [ ] Invite link in test email resolves to microsite with correct partner session
- [ ] Reply-to works (reply goes to hana@unitedarts.cz Gmail)
- [ ] Webhook endpoint receives test events from Resend
- [ ] Tracking webhook receives test events from microsite
- [ ] Analytics page shows test data correctly
- [ ] Unsubscribe link works (mailto: opens compose)

---

## Dependencies

### External (blocking)

| Dependency | Owner | Deadline | Risk |
|---|---|---|---|
| DNS records added for unitedarts.cz (SPF + DKIM) | Hana / UA team | Wed April 16 | **High** — DNS propagation takes 24-48h. Records must be added by Wednesday to verify by Friday. |
| UA/Losers Cirque logo assets (white-on-dark PNG, max 280px wide) | Hana | Thu April 17 | Medium — can use text fallback if delayed |
| Microsite webhook dispatch (fire partner events to leadgen) | ua-microsite repo | Fri April 18 | Medium — microsite tracking works without this (PostHog still captures), just no leadgen integration |

### Internal

| Dependency | Status |
|---|---|
| Resend API key in tenant settings | Already configured |
| EmailSendLog engagement columns (opened_at, clicked_at, etc.) | Already exist (migration 041) |
| campaign_contacts.metadata JSONB column | Already exists |
| ua-microsite /api/invites endpoint | Already deployed at demo.visionvolve.com |
| PostHog integration in microsite | Already active |
| send_service.py Resend integration | Already working |

---

## Timeline

| Day | Milestone |
|---|---|
| **Sun Apr 13** | Spec complete, DNS record instructions sent to Hana |
| **Mon Apr 14** | Build: webhook handler, vocative lookup, template rendering, invite integration |
| **Tue Apr 15** | Build: tracking webhook, analytics enhancement, migration |
| **Wed Apr 16** | DNS records added by Hana (deadline). Integration testing on staging. |
| **Thu Apr 17** | End-to-end test on staging. Fix issues. Microsite webhook dispatch. |
| **Fri Apr 18** | Domain verification confirmed. Smoke test with real test emails. |
| **Sat-Sun Apr 19-20** | Buffer for DNS propagation issues or fixes |
| **Mon Apr 21** | **SEND DAY** — campaign goes out morning CET |
| **Tue Apr 22** | EventFest. Monitor opens/clicks/visits throughout the day. |

---

## Out of Scope

- **Automated follow-up sequence** — this is a one-shot campaign. Sequence automation (from meetup-campaign-outreach spec) is a separate feature.
- **A/B testing** — single variant for this campaign. A/B infrastructure exists but not used here.
- **LinkedIn outreach** — email only for EventFest.
- **Resend domain verification UI** — admin uses API endpoints directly (or CLI). No frontend needed for a one-time setup.
- **Unsubscribe management system** — mailto: unsubscribe link is sufficient for this campaign size. Full unsubscribe management is a future feature.
- **Email preview/test-send UI** — testing done via direct API calls or manual staging send. No frontend needed.
- **PostHog API queries in leadgen** — PostHog dashboard is sufficient for deep analytics. Leadgen shows the funnel from its own Activity data. PostHog integration is a Could Have for later.
