# United Arts Campaign Design — Leadgen App Implementation

**Created**: 2026-03-29
**Source**: `docs/specs/ua-demandgen-strategy-v3.md`
**Status**: Design

---

## Section 1: Campaign Definitions

Six starter campaigns derived from the three pillars of the UA demand generation strategy. Each maps to a concrete segment, outreach sequence, and product recommendation.

### Campaign 1: P1-A Reactivace aktivnich agentur (Active Agency Reactivation)

**Pillar**: 1 — Retention | **Segment**: Active agencies (collaboration within last 18 months)

**Target criteria**:
- `company.industry_category` IN ('Event Agency', 'Creative Agency') OR `company.business_type` = 'agency'
- Last collaboration <= 18 months ago (requires `last_collaboration_date` field or tag-based filtering)
- `contact.language` = 'cs'

**Product recommendation**: Up-sell from animations to catalogue/custom shows (Glamour in Red, Flying Welcome Drink, catalogue 30-min block)

**Step sequence**:

| Position | Day | Channel | Label | Template Content (CZ) |
|----------|-----|---------|-------|----------------------|
| 1 | D0 | email | Osobni podekovaní | "Dekujeme za spolupráci na [konkrétní akce]. Pro letošek máme nové animacní programy — Glamour in Red a Flying Welcome Drink. Krátká ukázka: [showreel link]." |
| 2 | D7 | email | Case study | Konkrétní príklad akce pro podobný typ klienta. Co jsme dodali, jak to vypadalo, co rekl klient. |
| 3 | D14 | email | Exkluzivní nabídka | Osobní pozvánka na preview nového show / setkání. "Rádi vám ukážeme, co nového umíme — u kávy nebo na naší show." |

**Condition logic**: Step 2 = `always`, Step 3 = `no_response` (only if they haven't replied)

**Expected funnel**: 50 contacts -> 30% open -> 10% reply -> 3-5 meetings -> 2-3 bookings

---

### Campaign 2: P1-B Reaktivace spícich kontaktu (Sleeping Contact Reactivation)

**Pillar**: 1 — Retention | **Segment**: Sleeping contacts (18+ months without interaction)

**Target criteria**:
- Last collaboration > 18 months ago OR no collaboration on record
- Known email exists, not bounced
- `contact.language` = 'cs'

**Product recommendation**: Entry products based on segment — animations for agencies, Živé Sochy for gala organizers

**Step sequence**:

| Position | Day | Channel | Label | Template Content (CZ) |
|----------|-----|---------|-------|----------------------|
| 1 | D0 | email | Co je nového | "Od ledna vede eventovou komunikaci Hanka Faková. Tým se rozrostl, repertoár taky. Krátký prehled novinek: [90s highlight reel]." |
| 2 | D10 | email | Sezónní nabídka | Konkrétní program vhodný pro aktuální sezónu + orientacní cena. "Pro letní akce: Chudaci od 9.000 Kc/osoba, Hrající Chudac od 10.000 Kc." |
| 3 | D21 | email | Poslední pokus | "Stále se venujete eventum? Rádi pošleme aktuální nabídku. Pokud ne, dejte vedet." |

**Condition logic**: Step 2 = `always`, Step 3 = `no_response`

**Expected funnel**: 100 contacts -> 25% open -> 5% reply -> 5-8 reactivated relationships

---

### Campaign 3: P2-A Obce — formální outreach (Municipality Formal Outreach)

**Pillar**: 2 — Regions | **Segment**: Cultural committees of municipalities (5,000+ inhabitants)

**Target criteria**:
- `company.business_type` = 'municipality' OR segment tag = 'Obec'
- `company.company_size` >= '5000' (population)
- `contact.job_title` LIKE '%kultura%' OR '%starosta%' OR '%kulturní komise%'
- `contact.language` = 'cs'

**Product recommendation**: Chudaci (2 os. = 18,000 CZK) or Hrající Chudac (10,000 CZK) as entry; catalogue show as up-sell

**Step sequence**:

| Position | Day | Channel | Label | Template Content (CZ) |
|----------|-----|---------|-------|----------------------|
| 1 | D0 | email | Úvodní oslovení | "Videli jsme, že [obec] organizuje [dny mesta / slavnost]. Máme program, který vaši akci posune na jinou úroven — od 10.000 Kc." + odkaz na 90s showreel (outdoor záběry) |
| 2 | D5 | email | One-pager v príloze | One-pager "Pro dny mest" — Chudaci + Hrající Chudac s cenami, reference, fotky |
| 3 | D10 | call | Telefonát | "Posílal jsem e-mail s nabídkou programu pro vaše dny mesta. Mel/a jste možnost se podívat?" |
| 4 | D14 | email | Cenová nabídka | Konkrétní cenová nabídka pro jejich akci + nabídka nezávazného callu s Hankou |
| 5 | D21 | email | Follow-up závěrecný | "Plánujete program na [sezónu]? Rádi pomužeme. Nechte nám kontakt." |

**Condition logic**: Steps 1-2 = `always`, Step 3 = `always`, Step 4 = `no_response`, Step 5 = `no_response`

**Expected funnel**: 100 contacts -> 40% open -> 10% reply/answer phone -> 15 meetings -> 4-6 bookings

---

### Campaign 4: P2-B Spolky — neformální outreach (Clubs/Associations Informal Outreach)

**Pillar**: 2 — Regions | **Segment**: Clubs, associations (Sokol, Orel, fire brigades, Rotary/Lions, cultural clubs)

**Target criteria**:
- Segment tag IN ('Spolek', 'Hasiči', 'Rotary/Lions', 'Sokol')
- `contact.language` = 'cs'

**Product recommendation**: Živé Sochy (2 os. = 10,000 CZK) or Glamour in Red (2 os. = 12,000 CZK) as entry; catalogue show as up-sell

**Step sequence**:

| Position | Day | Channel | Label | Template Content (CZ) |
|----------|-----|---------|-------|----------------------|
| 1 | D0 | call | Úvodní telefonát | "Organizujete letos ples / slavnost? Máme program, který jste ješte nevideli — elegantní živé sochy nebo akrobatky od 10.000 Kc za celý vecer." |
| 2 | D1 | email | Follow-up po telefonu | Showreel + one-pager "Pro spolecenské plesy" s Živé Sochy a Glamour in Red |
| 3 | D7 | email | Case study | Case study z podobné akce (ples, slavnost) + konkrétní cena pro jejich typ akce |
| 4 | D14 | call | Druhý telefonát | "Meli jste cas se podívat? Muzu odpovedět na otázky." |
| 5 | D21 | email | Sleva pro nové | "První spolupráce se slevou 15 % pro nové klienty z vašeho regionu" |

**Condition logic**: Steps 1-3 = `always`, Steps 4-5 = `no_response`

**Expected funnel**: 100 contacts -> phone answer 30% -> 10 meetings -> 4-6 bookings

---

### Campaign 5: P2-C Školy — maturitní plesy (Schools — Prom Outreach)

**Pillar**: 2 — Regions | **Segment**: High schools and universities (prom balls January-March)

**Target criteria**:
- Segment tag = 'Škola' OR `company.business_type` = 'school'
- `contact.job_title` LIKE '%student%' OR '%organizátor%' OR '%ucitel%'
- `contact.language` = 'cs'

**Product recommendation**: Živé Sochy (2 os. = 10,000 CZK) as entry; Glamour in Red or 30-min catalogue show as up-sell

**Seasonal timing**: Outreach in September-October for January-March prom season

**Step sequence**:

| Position | Day | Channel | Label | Template Content (CZ) |
|----------|-----|---------|-------|----------------------|
| 1 | D0 | email | Úvodní e-mail | "Plánujete maturitní ples? Máme elegantní program pro slavnostní vecer — živé sochy od 10.000 Kc. Podívejte se: [showreel indoor]" |
| 2 | D5 | email | Reference + cena | Reference z podobných plesu + konkrétní cenová nabídka |
| 3 | D12 | call | Telefonát | "Posílal jsem nabídku pro váš ples. Mel/a jste možnost se podívat?" |
| 4 | D18 | email | Pozvánka na ukázku | "Rádi vám ukážeme naše umění naživo — pozvánka na nejbližší predstavení" |

**Condition logic**: Steps 1-2 = `always`, Steps 3-4 = `no_response`

**Expected funnel**: 50 contacts -> 35% open -> 8% reply -> 5 meetings -> 2-3 bookings

---

### Campaign 6: P3 DACH Pilot — Event Agenturen (German-Language Agency Outreach)

**Pillar**: 3 — DACH | **Segment**: Event agencies in Munich, Vienna, Frankfurt, Stuttgart

**Target criteria**:
- `contact.location_country` IN ('DE', 'AT', 'CH') OR `company.geo_region` = 'DACH'
- `company.industry_category` IN ('Event Agency', 'Creative Agency')
- `contact.language` = 'de'

**Product recommendation**: Catalogue shows (2,500-4,000 EUR) as entry; custom full-evening program (8,000-18,000 EUR) as up-sell

**Step sequence**:

| Position | Day | Channel | Label | Template Content (DE) |
|----------|-----|---------|-------|----------------------|
| 1 | D0 | email | Intro | "Wir sind eine tschechische Zirkuscompagnie mit Kunden wie Mercedes-Benz und Bosch. Unsere Gruppenakrobatik mit 10-14 Performern ist einzigartig in der DACH-Region. Showreel: [link]" |
| 2 | D4 | linkedin_connect | LinkedIn Connect | Connection request + kurze persoenliche Nachricht |
| 3 | D8 | email | Showreel + Preise | Video showreel + konkreter Preisrahmen fuer erste Veranstaltung (Katalogshow ab 2.500 EUR) |
| 4 | D14 | email | Case Study | Case study von internationaler Veranstaltung (Mercedes, Bosch, etc.) |
| 5 | D21 | call | Follow-up Anruf | Persoenlicher Kontakt — in DACH unersetzlich |

**Condition logic**: Steps 1-3 = `always`, Steps 4-5 = `no_response`

**Expected funnel**: 100 contacts -> 35% open -> 5-8% reply -> 3-5 meetings -> 2-4 pilot bookings

---

## Section 2: Feature Gap Analysis

| Feature | Status | Priority for UA | Notes |
|---------|--------|----------------|-------|
| **Campaign CRUD** | Exists | -- | Create, update, delete, clone all work |
| **Campaign templates** | Exists | High | Used to pre-populate step sequences; needs UA-specific templates |
| **Multi-step sequences (CampaignStep)** | Exists | -- | `campaign_steps` table with position, day_offset, channel, condition |
| **Email channel** | Exists | -- | Full send via Resend with tracking |
| **LinkedIn Connect channel** | Exists | -- | Via extension queue (`linkedin_connect`) |
| **LinkedIn Message channel** | Exists | -- | Via extension queue (`linkedin_message`) |
| **Call/Phone channel** | Exists | -- | `call` channel type defined in StepsTab UI |
| **Step conditions (always/no_response/opened_not_replied)** | Exists | -- | `condition` field on CampaignStep |
| **Day offset timing (D0, D5, D10...)** | Exists | -- | `day_offset` field on CampaignStep |
| **Sequence timeline view** | Exists | -- | StepsTab has editor + sequence view modes |
| **AI-designed steps** | Exists | -- | `useAiDesignSteps` hook for AI step generation |
| **Step execution status tracking** | Exists | -- | `execution_status` on CampaignStep (pending/active/completed/skipped) |
| **Campaign cloning** | Exists | -- | POST `/api/campaigns/:id/clone` |
| **Save campaign as template** | Exists | -- | Frontend `useSaveAsTemplate` hook |
| **Contact language field** | Exists | -- | `contact.language` column exists |
| **Message language field** | Exists | -- | `message.language` column exists |
| **Contact overlap detection** | Exists | -- | `campaign_overlap_log` table, `contact_cooldown_days` |
| **Strategy-linked campaigns** | Exists | -- | `strategy_id` FK, auto-populates generation_config from strategy |
| **Target criteria (JSONB)** | Exists | -- | `target_criteria` on Campaign, but filtering logic is manual |
| **Feedback summary per step** | Exists | -- | `useFeedbackSummary` hook on StepsTab |
| **Asset attachments** | Exists | -- | `useAssets`, `useUploadAsset` on StepsTab for PDF one-pagers |
| --- | --- | --- | --- |
| **Step template content (body text per step)** | Partial | **Critical** | Step `config` JSONB can hold template text, but no dedicated `body`/`template_body` field. AI generation uses generation_config, not step-level templates. Need step-level template content that feeds into message generation. |
| **Segment-based contact targeting** | Partial | **Critical** | `target_criteria` exists as JSONB but there is no automated filter/query engine. Contacts are added manually via ContactPicker. Need segment tags (Obec, Spolek, Agentura, Skola, DACH) on contacts or companies, plus auto-population from criteria. |
| **Product recommendation per segment** | Missing | **High** | No field for recommended products on Campaign, CampaignStep, or Contact. Strategy has clear product-segment mapping. Need `recommended_products` JSONB on Campaign or as part of `target_criteria`. |
| **Seasonal timing rules** | Missing | **High** | No concept of "send window" or "seasonal launch date". Campaigns can be created anytime but there is no scheduling for "launch this in September for January prom season". Need `scheduled_launch_at` on Campaign. |
| **Automated sequence execution engine** | Missing | **Critical** | Steps exist as data but there is no scheduler/worker that advances contacts through the sequence automatically (wait D5, check condition, send next step). Currently manual: generate messages, review, queue/send per step. This is the biggest gap. |
| **Non-responder detection** | Missing | **High** | No endpoint to check which contacts haven't responded between steps. Needed for `no_response` condition to actually trigger. Partially noted in meetup-campaign-outreach spec. |
| **Conversion funnel tracking** | Partial | **Medium** | `campaign_contacts.status` tracks (pending/generated/etc.) but no pipeline stages like contacted -> opened -> replied -> meeting -> booked. Email open/click tracking exists via Resend webhooks. |
| **Multi-language campaign support** | Partial | **Medium** | Message language field exists. Generation prompts could accept language. But no campaign-level language setting and no language-aware template switching. |
| **Contact segment field** | Missing | **High** | No `segment` field on Contact or Company (e.g., Obec, Spolek, Agentura, Skola, DACH). Could use tags, custom_fields, or a new column. |
| **Last collaboration date** | Missing | **High** | No `last_collaboration_date` on Contact or Company. Needed to distinguish active vs sleeping contacts. Could be derived from Activity table or added as explicit field. |
| **Campaign-level language** | Missing | **Medium** | No `language` field on Campaign. Each campaign should specify CZ or DE to guide generation. |
| **Bulk contact import from segment filter** | Missing | **High** | Cannot auto-populate campaign contacts from segment criteria. Must add one by one via ContactPicker. |
| **One-pager/attachment per step** | Partial | **Medium** | Asset system exists but linking assets to specific steps (e.g., "attach PDF one-pager to step 2") may need UI work. |

---

## Section 3: Implementation Plan

Prioritized by what is needed to run the first campaign (P1-A Active Agency Reactivation) within one week.

### Phase 0: Data Preparation (Day 1) — No Code Changes

1. **Tag contacts with segments** — Use existing tag system or `custom_fields` to label contacts as Agentura, Obec, Spolek, Skola, DACH. This can be done via bulk update in the app or direct SQL.
2. **Set contact language** — Ensure `language` is set to 'cs' or 'de' on all contacts.
3. **Identify active vs sleeping** — Use Activity table timestamps or manual tagging to mark last collaboration date.

### Phase 1: Campaign Templates + Step Content (Day 1-2)

**Goal**: Create the 6 campaign templates so users can create campaigns from them.

4. **Create 6 system CampaignTemplate records** via migration or seed script. Each template has the `steps` JSONB array with channel, day_offset, label, and a `template_body` key in each step's config.

5. **Add `template_body` support to step config** — The `CampaignStep.config` JSONB already exists. Store template content as `config.template_body`. No schema change needed, just convention.

6. **Add `language` field to Campaign** — Migration 053: `ALTER TABLE campaigns ADD COLUMN language TEXT DEFAULT 'cs';`

7. **Add `recommended_products` to Campaign** — Store as part of `generation_config` JSONB (no schema change needed, just convention: `generation_config.recommended_products = ["Chudaci", "Hrající Chudac"]`).

### Phase 2: Segment Filtering + Bulk Add (Day 2-3)

**Goal**: Auto-populate campaign contacts from segment criteria.

8. **Add `segment` column to companies** — Migration 053: `ALTER TABLE companies ADD COLUMN segment TEXT;` Values: 'agentura', 'obec', 'spolek', 'skola', 'korporace', 'dach', 'ostatni'.

9. **Bulk add contacts endpoint** — New route `POST /api/campaigns/:id/contacts/bulk` that accepts filter criteria (segment, language, tags) and adds matching contacts. This replaces manual ContactPicker for large campaigns.

10. **Frontend: Add segment filter to ContactPicker** — Allow filtering by company segment when adding contacts to a campaign.

### Phase 3: Sequence Execution MVP (Day 3-5)

**Goal**: Minimal automated sequence advancement.

11. **Scheduled launch date** — Migration 053: `ALTER TABLE campaigns ADD COLUMN scheduled_launch_at TIMESTAMPTZ;` UI shows date picker on campaign settings.

12. **Non-responder check endpoint** — `GET /api/campaigns/:id/steps/:position/eligible` returns contacts eligible for this step based on condition logic (e.g., `no_response` checks if contact replied to any previous step message).

13. **Step activation workflow** — Extend campaign status machine: when a step's day_offset arrives (relative to campaign launch or previous step), mark it `active` and make contacts available for message generation for that step. This can be a manual "Activate Next Step" button initially, with full automation later.

### Phase 4: Conversion Funnel + Analytics (Day 5-7)

14. **Add funnel stages to campaign_contacts** — Extend `status` enum: `pending -> contacted -> opened -> replied -> meeting_scheduled -> booked -> lost`. Track transitions with timestamps.

15. **Campaign analytics funnel chart** — The `CampaignAnalytics` component already exists. Add funnel visualization showing conversion rates per step and per stage.

### Phase 5: Full Automation (Future Sprint)

16. **Background worker for sequence advancement** — Celery/APScheduler task that checks active campaigns daily, evaluates step conditions, and auto-generates + queues messages for eligible contacts.

17. **Seasonal campaign scheduling** — Allow campaigns to be created in advance and auto-launch on `scheduled_launch_at`.

18. **Multi-language template switching** — Campaign language determines which template variant to use during generation.

---

## Section 4: Data Model Changes

### Migration 053: UA Campaign Support

```sql
-- Campaign-level language
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'cs';

-- Campaign scheduled launch
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS scheduled_launch_at TIMESTAMPTZ;

-- Company segment (Obec, Spolek, Agentura, Skola, DACH, etc.)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS segment TEXT;

-- Contact last collaboration date (for active vs sleeping classification)
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_collaboration_at TIMESTAMPTZ;

-- Expand campaign_contacts.status for funnel tracking
-- (status is TEXT, no enum change needed — just new convention values)
-- Values: pending, contacted, opened, replied, meeting_scheduled, booked, lost

-- Index for segment-based queries
CREATE INDEX IF NOT EXISTS idx_companies_segment ON companies(segment) WHERE segment IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_last_collab ON contacts(last_collaboration_at) WHERE last_collaboration_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_campaigns_language ON campaigns(language) WHERE language IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_campaigns_scheduled ON campaigns(scheduled_launch_at) WHERE scheduled_launch_at IS NOT NULL;
```

### Model Changes (api/models.py)

```python
# Campaign model — add:
language = db.Column(db.Text, default="cs")
scheduled_launch_at = db.Column(db.DateTime(timezone=True))

# Company model — add:
segment = db.Column(db.Text)  # agentura, obec, spolek, skola, korporace, dach, ostatni

# Contact model — add:
last_collaboration_at = db.Column(db.DateTime(timezone=True))
```

### Step Config Convention (no schema change)

CampaignStep `config` JSONB will follow this structure:

```json
{
  "template_body": "Dekujeme za spolupráci na {{last_event}}. Pro letošek máme...",
  "template_subject": "Nové programy od Losers Cirque Company",
  "attachments": ["asset-uuid-for-one-pager"],
  "tone": "professional",
  "language": "cs",
  "personalization_vars": ["last_event", "contact_name", "company_name", "recommended_product"]
}
```

### Campaign generation_config Convention (no schema change)

```json
{
  "recommended_products": ["Chudaci", "Hrající Chudac"],
  "product_prices": {"Chudaci": "9,000 Kc/osoba", "Hrající Chudac": "10,000 Kc"},
  "value_proposition": "Wow efekt za cenu lokální kapely",
  "segment": "obec",
  "language": "cs",
  "seasonal_context": "letní akce (kveten-zárí)"
}
```

---

## Summary: What Can Run Today vs What Needs Building

### Can run today (with manual effort):
- Create a campaign, add steps with correct channels/day_offsets/conditions
- Add contacts manually via ContactPicker
- Generate messages per step (AI generation already iterates contacts x steps)
- Review and approve messages
- Send emails via Resend, queue LinkedIn via extension
- Track email opens/clicks

### Needs building for full UA execution:
1. **Campaign templates with UA content** (Phase 1, ~1 day) — seed 6 templates
2. **Company segment + contact last_collaboration_at fields** (Phase 2, ~1 day) — migration + backfill
3. **Bulk contact add from segment filter** (Phase 2, ~1 day) — new endpoint + UI
4. **Step template content in generation** (Phase 1, ~0.5 day) — feed `config.template_body` into prompt
5. **Non-responder detection** (Phase 3, ~1 day) — endpoint for condition evaluation
6. **Campaign language field** (Phase 1, ~0.5 day) — migration + UI

**Minimum viable for first campaign (P1-A)**: Items 1 + 4 + 6. The active agency reactivation is a 3-step email-only sequence that can be run with manual contact selection and per-step message generation. Templates with body content and language field are the only blockers.
