# Leadgen Pipeline - Architecture

> Last updated: 2026-02-20

## System Overview

Leadgen Pipeline is a multi-tenant B2B lead enrichment and outreach platform. It ingests company/contact lists, runs AI-powered enrichment through a multi-stage pipeline, generates personalized outreach messages, and provides a dashboard for review and management.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        BROWSER (Dashboard)                          │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ Pipeline  │  │ Messages │  │  Admin   │  │ Login / Auth     │   │
│  │ Control   │  │ Review   │  │ Panel    │  │ (JWT)            │   │
│  └─────┬─────┘  └─────┬────┘  └────┬─────┘  └─────────────────┘   │
│        │              │             │                                │
└────────┼──────────────┼─────────────┼───────────────────────────────┘
         │              │             │
    n8n webhooks    REST API      REST API
         │              │             │
┌────────┼──────────────┼─────────────┼───────────────────────────────┐
│        │    Caddy Reverse Proxy (leadgen.visionvolve.com)           │
│        │              │             │                                │
│   /webhook/*     /api/*        /api/*                               │
│        │              │             │                                │
│   ┌────▼────┐    ┌────▼─────────────▼────┐                         │
│   │   n8n   │    │   Flask API           │                         │
│   │ (5678)  │    │   (Gunicorn :5000)    │                         │
│   │         │    │                       │                         │
│   │ Orch.   │    │ - Auth (JWT/bcrypt)   │                         │
│   │ L1/L2   │    │ - Tenants CRUD        │                         │
│   │ Person  │    │ - Users CRUD          │                         │
│   │ Progress│    │ - Messages CRUD       │                         │
│   │         │    │ - Batches / Stats     │                         │
│   └────┬────┘    └────────┬──────────────┘                         │
│        │                  │                                         │
│        └──────┬───────────┘                                        │
│               │                                                     │
│        ┌──────▼──────┐                                             │
│        │  PostgreSQL  │                                             │
│        │  (RDS)       │                                             │
│        │              │                                             │
│        │  leadgen DB  │                                             │
│        └──────────────┘                                             │
│                                                                     │
│   Docker host: 52.58.119.191 (Amazon Linux 2023)                   │
└─────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Dashboard (React SPA)
- **Tech**: React 19 + TypeScript + Vite + Tailwind CSS v4 + TanStack Query v5
- **Hosting**: Caddy file server at `leadgen.visionvolve.com`, SPA fallback to `index.html`
- **Pages**: Contacts, Companies, Messages, Campaigns, Enrich (pipeline control), Import (CSV + Google wizard), Admin (namespace/user CRUD), Placeholders (Playbook, Echo, LLM Costs)
- **Standalone**: `roadmap.html` — standalone backlog viewer, no auth, no SPA routing
- **Virtual scroll**: Companies and Contacts tables use DOM windowing — only ~60-80 rows rendered at any time regardless of dataset size. Data fetched via infinite scroll (IntersectionObserver), rendered via `renderWindow()` on scroll (see ADR-001)
- **Auth**: JWT stored in localStorage, managed by `useAuth` hook
- **Namespace routing**: `/{tenant-slug}/page` — React Router reads namespace from URL, API calls include `X-Namespace` header
- **API layer**: `apiFetch` (JSON) + `apiUpload` (FormData) in `api/client.ts`, TanStack Query hooks in `api/queries/`

### 2. Flask API
- **Tech**: Flask + SQLAlchemy + Gunicorn
- **Container**: `leadgen-api` (Docker, port 5000)
- **Routes**: `/api/auth/*`, `/api/tenants/*`, `/api/users/*`, `/api/tags/*`, `/api/companies/*`, `/api/contacts/*`, `/api/messages/*`, `/api/campaigns/*`, `/api/campaign-templates`, `/api/pipeline/*`, `/api/enrich/*`, `/api/imports/*`, `/api/llm-usage/*`, `/api/oauth/*`, `/api/gmail/*`, `/api/bulk/*`, `/api/extension/*`, `/api/health`
- **Services**: `pipeline_engine.py` (stage orchestration), `dag_executor.py` (DAG-based executor with completion-record eligibility, see ADR-005), `stage_registry.py` (configurable DAG of enrichment stages), `qc_checker.py` (end-of-pipeline quality checks), `l1_enricher.py` (native L1 via Perplexity, see ADR-003), `registries/` (EU registry adapters + unified orchestrator — see ADR-004, ADR-005), `csv_mapper.py` (AI column mapping), `dedup.py` (contact/company deduplication), `llm_logger.py` (LLM usage cost tracking), `google_oauth.py` (OAuth token management), `google_contacts.py` (People API fetch/mapping), `gmail_scanner.py` (background Gmail scan + AI signature extraction), `message_generator.py` (campaign message generation via Claude API), `generation_prompts.py` (channel-specific prompt templates)
- **Auth**: JWT Bearer tokens, bcrypt password hashing
- **Multi-tenant**: Shared PG schema, `tenant_id` on all entity tables

### 3. n8n Workflows
- **Tech**: n8n (self-hosted, Docker)
- **Orchestrator**: Multi-stage enrichment pipeline (L1 → Triage → L2 → Person)
- **Sub-workflows**: L1 Company, L2 Company, L2 Person (each called via Execute Workflow)
- **Support**: Progress Store (webhook-based progress tracking), Batch List/Stats APIs
- **Data**: Currently reads/writes Airtable (PG migration pending for workflow nodes)

### 4. PostgreSQL (RDS)
- **Instance**: AWS Lightsail managed PostgreSQL
- **Databases**: `n8n` (n8n internal), `leadgen` (application data)
- **Schema**: 19 entity tables + 3 junction tables + 2 auth tables, ~30 enum types
- **Multi-tenant**: `tenant_id` column on all entity tables
- **DDL**: `migrations/001_initial_schema.sql` through `028_extension_activities.sql`

### 5. Contact ICP Filter System
- **Purpose**: Faceted multi-value filtering on the Contacts page to narrow contacts by ICP (Ideal Customer Profile) criteria
- **Filters (8 total)**: `industry`, `company_size`, `geo_region`, `revenue_range`, `seniority_level`, `department`, `job_titles`, `linkedin_activity` — each supports multi-value selection with an include/exclude toggle
- **Faceted counts**: `POST /api/contacts/filter-counts` returns available option counts under current filter state, enabling dynamic facet UI (options with zero results are de-emphasized)
- **Job title typeahead**: `GET /api/contacts/job-titles?q=<term>` returns ranked suggestions from existing contact records for free-text job title search
- **Frontend components** (`frontend/src/components/ui/`):
  - `MultiSelectFilter`: Reusable dropdown with checkbox list, include/exclude toggle, and active-count badge
  - `JobTitleFilter`: Extends `MultiSelectFilter` with debounced typeahead search input
  - `useAdvancedFilters` hook: Manages filter state, serialization to URL query params, and reset logic — consumed by the ContactsPage

### 6. Campaign & Message Generation
- **Campaign lifecycle**: draft → ready → generating → review → approved → exported → archived
- **Contact assignment**: Add contacts by individual IDs or by company (all contacts of a company), with duplicate detection
- **Template presets**: 3 system templates (LinkedIn + Email, Email 3-Step, LinkedIn Only), configurable per-campaign
- **Enrichment readiness**: Pre-generation check querying entity_stage_completions per contact's company
- **Generation engine** (`message_generator.py`): Background thread iterates contacts × enabled steps, calls Claude Haiku API per message
- **Channel constraints**: LinkedIn connect ≤ 300 chars (body only), LinkedIn message ≤ 2000 chars, email requires subject + body
- **Prompts** (`generation_prompts.py`): Incorporates company summary, L2 intel, person enrichment, signals, tone, custom instructions
- **Cost tracking**: Per-message cost logged via `llm_logger.py`, aggregated per campaign_contact and campaign
- **Review workflow**: Focused single-message queue with sequential gated navigation (approve/reject to advance). Manual editing with version tracking (original_body/original_subject preserved immutably, structured edit_reason tags for LLM training feedback — ADR-007). Per-message regeneration with language, formality (Ty/Vy), tone overrides, custom instruction (max 200 chars), cost estimate. Contact disqualification (campaign-only exclusion or global). Campaign outreach approval gate (all messages must be reviewed before campaign → approved).

### 8. Browser Extension (Chrome)
- **Tech**: TypeScript + Vite, Chrome Manifest V3
- **Components**:
  - **Popup** (`popup.ts`): Login form (email/password), connection status display, manual sync trigger
  - **Content Scripts**: `sales-navigator.ts` (extracts lead data from Sales Navigator search results), `activity-monitor.ts` (monitors LinkedIn activity feed events)
  - **Service Worker** (`service-worker.ts`): Background sync queue, JWT auto-refresh via `chrome.storage`, badge notifications for sync status
- **Auth flow**: User logs in via popup (email + password) -> API returns JWT access + refresh tokens -> tokens stored in `chrome.storage.local` -> service worker auto-refreshes before expiry
- **Data flow**:
  - **Leads**: Content script extracts lead data from Sales Navigator -> queued in service worker -> `POST /api/extension/leads` (dedup by LinkedIn URL, company matching by name)
  - **Activities**: Content script monitors LinkedIn events -> queued in service worker -> `POST /api/extension/activities` (dedup by `external_id`, stub contact creation for unknown LinkedIn URLs)
- **Configuration** (`config.ts`): Environment-specific API base URLs (prod: `leadgen.visionvolve.com`, staging: `leadgen-staging.visionvolve.com`)
- **Dual builds**: Vite build produces two variants via manifest overlays — purple icons for production, orange icons for staging — allowing both to be installed simultaneously
- **Dashboard integration**: `GET /api/extension/status` surfaces connection state and sync stats on the Preferences page

### 7. Caddy (Reverse Proxy)
- **Subdomains**: `n8n.visionvolve.com`, `leadgen.visionvolve.com`, `vps.visionvolve.com`, `ds.visionvolve.com`
- **Leadgen routing**: `/api/*` → Flask API, everything else → static dashboard files
- **Namespace routing**: `/{slug}/page` → strips prefix → serves `/page.html`
- **TLS**: Automatic via Let's Encrypt

## Data Flow

### Enrichment Pipeline (DAG Model)

The enrichment pipeline uses a configurable DAG of stages with per-entity completion tracking.

```
                    ┌──→ [L2 Deep Research]         ──┐
[L1 Company] ──────┼──→ [Strategic Signals]          ──┼──→ [Person] ──→ [Generate] ──→ [QC]
                    ├──→ [ARES] (CZ companies)        │
                    ├──→ [BRREG] (NO companies)       │
                    ├──→ [PRH] (FI companies)         │
                    ├──→ [Recherche] (FR companies)   │
                    └──→ [ISIR] (CZ w/ ICO)           ┘
```

**Stage Registry** (`stage_registry.py`): 11 stages with hard/soft dependencies, country gates, and execution modes.

**DAG Executor** (`dag_executor.py`): Eligibility determined by `entity_stage_completions` records. Each stage thread polls for eligible entities. Cross-entity-type deps supported (contact stages check company completions).

**QC Checker** (`qc_checker.py`): End-of-pipeline checks — registry name mismatch, HQ country conflict, active insolvency, dissolved status, data completeness, low registry confidence.

**API endpoints**:
- `POST /api/pipeline/dag-run`: Start DAG execution with stage list + soft dep config
- `GET /api/pipeline/dag-status`: Per-stage status + DAG structure + completion counts
- `POST /api/pipeline/dag-stop`: Stop entire DAG run
- Legacy endpoints (`/api/enrich/start`, `/api/pipeline/run-all`) still work via old executor

```
POST /api/pipeline/dag-run {stages, soft_deps, batch_name, ...}
    │
    ▼
DAG Executor → spawns thread per stage
    │
    ├──→ L1: Native Python (l1_enricher.py → Perplexity sonar)
    ├──→ Registries: Native Python (ARES/BRREG/PRH/recherche/ISIR)
    ├──→ L2: n8n webhook
    ├──→ Person: n8n webhook
    ├──→ Generate: n8n webhook
    └──→ QC: Native Python (qc_checker.py)

Each completion → INSERT entity_stage_completions → unblocks downstream
```

### Authentication Flow
```
Browser → POST /api/auth/login {email, password}
    │
    ▼
Flask API → bcrypt verify → JWT (access + refresh)
    │
    ▼
Browser stores tokens in localStorage
    │
    ▼
Subsequent requests: Authorization: Bearer {access_token}
    │
    ▼
Token expired → POST /api/auth/refresh {refresh_token}
```

### Google OAuth + Gmail Import Flow
```
Dashboard → GET /api/oauth/google/auth-url
    │
    ▼
Browser → Google OAuth consent screen (contacts.readonly + gmail.readonly)
    │
    ▼
Google callback → GET /api/oauth/google/callback?code=...
    │
    ▼
Flask API → exchange code → encrypt tokens (Fernet) → store in oauth_connections
    │
    ▼
Google Contacts: POST /api/gmail/contacts/fetch → People API → dedup preview → import
    │
Gmail Scan: POST /api/gmail/scan/start → background thread:
    ├── Scan message headers (From/To/CC) — deterministic
    ├── Extract signatures via Claude Haiku — batched AI
    ├── Aggregate by email → contact rows
    └── dedup preview → import
```

## Database Schema (High Level)

```
tenants ─┬── owners
         ├── tags (renamed from batches)
         ├── import_jobs (CSV/Gmail import lifecycle tracking)
         ├── oauth_connections (Google OAuth tokens, Fernet-encrypted)
         ├── companies ─┬── company_enrichment_l1 (1:1, L1 triage detail)
         │              ├── company_enrichment_profile (1:1, L2 company intel)
         │              ├── company_enrichment_signals (1:1, L2 strategic signals)
         │              ├── company_enrichment_market (1:1, L2 market intel)
         │              ├── company_enrichment_opportunity (1:1, L2 pain & opportunity)
         │              ├── company_enrichment_l2 (1:1, deprecated — replaced by 4 modules above)
         │              ├── company_legal_profile (1:1, unified registry+insolvency+credibility)
         │              ├── company_registry_data (1:1, legacy ARES)
         │              ├── company_insolvency_data (1:1, legacy ISIR)
         │              └── company_tags (1:∞)
         ├── contact_tag_assignments (junction: contact×tag, multi-tag)
         ├── company_tag_assignments (junction: company×tag, multi-tag)
         ├── contacts ──── contact_enrichment (1:1, expanded: scoring + career + social)
         ├── messages ─── campaign_contacts (optional FK)
         ├── campaigns ── campaign_contacts (junction: campaign×contact)
         ├── campaign_templates (system + tenant-custom presets)
         ├── activities
         ├── crm_events ── crm_event_participants
         ├── tasks ─┬── task_contacts
         │          └── task_activities
         ├── research_assets (polymorphic)
         ├── pipeline_runs ── stage_runs
         ├── entity_stage_completions (DAG completion tracking)
         ├── llm_usage_log (per-call LLM cost tracking)
         └── audit_log

users ── user_tenant_roles ── tenants
     └── oauth_connections (per-user, per-provider)
```

## Deployment

| Component | Deploy Command | Container |
|-----------|---------------|-----------|
| Dashboard | `bash deploy/deploy-dashboard.sh` | Caddy (static files) |
| API | `bash deploy/deploy-api.sh` | `leadgen-api` |
| Caddy config | `cd visionvolve-vps && bash scripts/deploy-caddy.sh` | `caddy` |
| n8n workflows | Via n8n UI or API | `n8n` |

## External Dependencies

- **Airtable**: Data store for n8n workflows (dashboard APIs migrated to PG)
- **EU Government Registries** (all free, no auth): Unified `registry` stage via `RegistryOrchestrator` (ADR-005). Auto-detects country and runs applicable adapters. Results stored in `company_legal_profile` with credibility scoring.
  - **ARES (ares.gov.cz)**: Czech Republic — ICO/DIC, legal form, directors, capital, NACE codes, insolvency
  - **BRREG (data.brreg.no)**: Norway — organisasjonsnummer, legal form, NACE codes, capital, bankruptcy flags
  - **PRH (avoindata.prh.fi)**: Finland — Y-tunnus, company form, TOL codes, trade register status
  - **recherche-entreprises (api.gouv.fr)**: France — SIREN, nature juridique, NAF codes, directors, administrative status
  - **ISIR (isir.justice.cz)**: Czech Insolvency Register — SOAP/XML, supplementary to ARES (requires ICO)
- **Google APIs**: OAuth 2.0 (identity), People API (contacts), Gmail API (email scan)
- **Perplexity API**: L1/L2 company research
- **Anthropic API**: AI analysis, message generation, email signature extraction (Haiku)
- **Lemlist**: Outreach campaign delivery
- **AWS RDS**: PostgreSQL hosting
