# Leadgen Pipeline -- Product Overview

> Last updated: 2026-03-27

---

## 1. What It Is

Leadgen Pipeline is a multi-tenant B2B lead enrichment and outreach platform that transforms the go-to-market process from a linear, manual effort into an AI-driven closed loop. It ingests company and contact lists, runs multi-stage AI-powered enrichment to build deep intelligence on each prospect, generates personalized outreach messages calibrated to buyer personas, and provides a complete dashboard for review, campaign management, and performance tracking. The platform is designed so that every outreach cycle feeds results back into the strategy, making each subsequent campaign smarter than the last.

### Target User

The primary user is a **technical founder or early-stage CEO** -- typically at a seed or Series A B2B SaaS company -- who is personally responsible for go-to-market. This person has deep product expertise but limited time and no dedicated sales team. They need a system that acts less like a tool to operate and more like a competent first hire: an AI strategist that does the research, builds the playbook, sources contacts, drafts messages, and learns from results -- while the founder makes decisions and steers direction.

### Core Value Proposition

- **AI as a proactive strategist**, not a passive tool. The system researches, recommends, and follows up -- it does not wait to be prompted.
- **Closed-loop learning.** Campaign results feed back into strategy refinement. Every cycle makes the AI smarter about your market, your ICP, and what messaging resonates.
- **Zero busywork.** Auto-save, auto-extract, persistent chat context, readiness gates, and guided phase transitions eliminate operational overhead. Every interaction either gathers a decision or delivers a result.

---

## 2. Current Capabilities

### Contact and Company Management

The platform maintains a full CRM-style database of companies and contacts, organized by tenant (namespace).

- **Import**: CSV file upload with AI-powered column mapping (the system auto-detects which CSV columns correspond to which database fields). Google Contacts import via OAuth and Gmail scan with AI-powered email signature extraction for discovering new contacts from email history. Chrome extension (Sales Navigator scraper + LinkedIn activity monitor) pushes leads and activities directly into the platform.
- **Companies page**: Browsable table with virtual scrolling (DOM windowing renders only 60-80 rows regardless of dataset size). Company detail pages show core fields, enrichment modules (L1 triage, L2 deep research, strategic signals, market intel, opportunity analysis), legal profile from EU government registries, and tag assignments.
- **Contacts page**: Filterable table with an 8-dimension ICP filter system -- industry, company size, geo region, revenue range, seniority level, department, job titles (with typeahead search), and LinkedIn activity. Each filter supports multi-value selection with include/exclude toggle and faceted counts that update dynamically. Contact detail pages show person enrichment data, career information, social profiles, and scoring.
- **Tags**: Contacts and companies can be tagged (formerly called "batches") for organizing into cohorts, import batches, or campaign segments. Multi-tag assignment is supported.

### Enrichment Pipeline

The enrichment system is a configurable DAG (directed acyclic graph) of stages that can be run selectively and in parallel.

- **L1 Company Enrichment**: Fast initial triage using Perplexity AI. Scrapes the company website, analyzes the business, and produces a tier classification (Platinum, Gold, Silver, etc.) with a rationale. Runs natively in Python.
- **L2 Deep Research**: Comprehensive company intelligence split into four modules -- company profile, strategic signals, market intelligence, and pain/opportunity analysis. Powered by Claude (Anthropic) via n8n workflow orchestration.
- **EU Government Registries**: Automated lookup against five national registries -- ARES (Czech Republic), BRREG (Norway), PRH (Finland), Recherche Entreprises (France), and ISIR (Czech insolvency). The system auto-detects company country and runs applicable adapters. Results are stored with credibility scoring in a unified legal profile.
- **Person Enrichment**: Contact-level research including scoring, career trajectory, social profile analysis, and relevance assessment.
- **QC Checker**: End-of-pipeline quality checks -- registry name mismatch detection, HQ country conflicts, active insolvency flags, dissolved status, data completeness scoring, and low-confidence registry results.
- **DAG Executor**: Each stage runs in its own thread. Completion records in `entity_stage_completions` track what has been done per entity, enabling stages to be re-run selectively. Cross-entity-type dependencies are supported (e.g., contact enrichment stages can depend on company enrichment completion).
- **Pipeline UI**: Visual DAG representation with stage cards showing status, completion counts, and controls. Supports starting/stopping individual stages or the entire pipeline.

### Triage and Qualification

After L1 enrichment, companies are classified into tiers and assigned a qualification status.

- **Tier system**: Companies receive tier labels (Tier 1 - Platinum through Tier 3 - Silver and beyond) based on AI analysis of their fit with the user's ideal customer profile.
- **Triage Review page**: A dedicated review interface where users can approve, reject, or flag companies after L1 enrichment. Companies with status "Triage: Passed" proceed to L2 deep research; those marked "Triage: Review" or "Disqualified" are filtered out or held for manual review.
- **Status flow**: New -> L1 Enriched -> Triage: Passed / Triage: Review / Disqualified -> Enriched L2 (after deep research).

### Message Generation

AI-generated outreach messages are a core feature, tightly integrated with campaign management.

- **Generation engine**: Background thread iterates over contacts and enabled campaign steps, calling Claude Haiku to generate each message. Prompts incorporate company summary, L2 intelligence, person enrichment, strategic signals, tone preferences, and custom instructions.
- **Channel-specific constraints**: LinkedIn connection requests are capped at 300 characters (body only), LinkedIn messages at 2,000 characters, and emails require both subject and body.
- **Template presets**: Three built-in templates (LinkedIn + Email, Email 3-Step, LinkedIn Only) with configurable steps per campaign. Tenant-custom templates are also supported.
- **Cost tracking**: Every API call to the LLM is logged with token counts and cost. Costs are aggregated per message, per campaign contact, and per campaign.

### Message Review Workflow

The review experience is designed as a focused, sequential queue rather than a bulk editing interface.

- **Single-message review**: One message at a time with gated navigation -- you must approve or reject the current message to advance. Keyboard shortcuts support rapid review.
- **Manual editing**: Original body and subject are preserved immutably. Edits are tracked with structured reason tags (useful for future LLM training feedback). Version history is maintained.
- **Per-message regeneration**: Users can regenerate individual messages with overrides for language, formality (Ty/Vy for Czech formal/informal address), tone, and custom instructions (up to 200 characters). A cost estimate is shown before regeneration.
- **Contact disqualification**: From the review flow, users can disqualify a contact for the current campaign only or globally.
- **Campaign approval gate**: All messages in a campaign must be reviewed (approved or rejected) before the campaign can transition to "approved" status.

### Campaign Management

Campaigns are the container for organizing outreach at scale.

- **Campaign lifecycle**: draft -> ready -> generating -> review -> approved -> exported -> archived.
- **Contact assignment**: Add contacts individually or by company (all contacts of a company), with duplicate detection.
- **Campaign steps**: Each campaign has a sequence of steps (e.g., LinkedIn connect, follow-up email, second follow-up). Steps are defined by the campaign template and can be customized.
- **Enrichment readiness check**: Before generation starts, the system checks `entity_stage_completions` to verify that each contact's company has been sufficiently enriched.
- **Outreach approval dialog**: A confirmation gate before the campaign transitions to "approved" and is ready for export.
- **Campaigns page**: Lists all campaigns with status, contact count, and message generation progress. Campaign detail page shows contacts, steps, and per-step message status.

### Playbook (AI Strategy Chat)

The Playbook is a conversational AI interface that guides users through the full GTM workflow.

- **8-phase workflow**: Contacts -> Strategy -> Playbook -> Enrichment -> Messages -> Campaigns -> Generation -> Ready. Each phase has a specific purpose and the UI shows phase progress with a stepper.
- **Persistent chat**: The same conversation thread spans all phases. Full history is preserved so the AI never asks duplicate questions and maintains context across the entire workflow.
- **Strategy document**: A living document that the AI co-creates with the user. Covers ICP definition, buyer personas, value propositions, channel strategy, and messaging framework. Auto-saves with 2.5-second debounce.
- **Auto-extract**: Structured data (ICP tiers, value propositions, positioning) is silently extracted from the strategy document after every save, keeping the AI's understanding current.
- **Tool-augmented agent**: The chat agent has access to 24+ tools including web search, company research, strategy editing, contact filtering, enrichment control, and campaign management. Tools are phase-filtered so only relevant capabilities are available at each stage.
- **Readiness gates**: The AI evaluates whether the strategy is specific enough before allowing progression to the next phase. This prevents premature campaign launches with undercooked strategy.

### Admin and Multi-Tenancy

The platform supports multiple organizations (tenants) on a shared infrastructure.

- **Namespace routing**: URLs follow the pattern `/{tenant-slug}/page`. The React Router reads the namespace from the URL, and all API calls include an `X-Namespace` header for tenant resolution.
- **User roles**: Users can have different roles per tenant. Super admins can manage all namespaces and see cross-tenant data. Namespace admins manage users and settings within their organization.
- **IAM SSO**: Authentication supports both local email/password login and SSO via an external IAM service (VisionVolve IAM) with Google and GitHub OAuth providers. The auth callback handles token exchange and session establishment.
- **Admin page**: Namespace management (create, view namespaces) and user management (add users, assign roles) for super admins.
- **Preferences page**: User-level settings including Chrome extension connection status and sync statistics.

### Analytics and Dashboards

- **LLM Costs page**: Tracks AI compute spend across operations. Super admins see raw USD costs with per-provider breakdown (Anthropic, Perplexity) and margin analysis. Namespace admins see token/credit balances and usage by operation.
- **Tokens page**: Token and credit management interface for namespace admins.
- **Echo Analytics** (placeholder): Planned outreach performance dashboard -- conversion funnels, response rates by channel, pipeline velocity. Currently a placeholder page.
- **Enrichment stats**: The enrichment pipeline UI shows per-stage completion counts, estimated costs, and DAG status.

### Chrome Extension

A browser extension for Chrome (Manifest V3) that bridges LinkedIn Sales Navigator with the platform.

- **Lead extraction**: Scrapes lead data from Sales Navigator search results and pushes it to the API with deduplication by LinkedIn URL and company matching by name.
- **Activity monitoring**: Monitors LinkedIn activity feed events (messages, events) and syncs them as activity records.
- **Dual builds**: Vite produces two variants -- purple icons for production, orange for staging -- so both can be installed simultaneously.
- **Auth**: Login via popup with email/password. JWT tokens stored in Chrome storage with automatic refresh via the service worker.

---

## 3. Technical Architecture

### Backend

- **Flask + SQLAlchemy + Gunicorn**: The API server runs as a Docker container (`leadgen-api`) on port 5000. Routes cover auth, tenants, users, companies, contacts, messages, campaigns, pipeline control, enrichment, imports, LLM usage, OAuth, Gmail integration, bulk operations, and the Chrome extension.
- **PostgreSQL (AWS RDS)**: 19 entity tables, 3 junction tables, 2 auth tables, and approximately 30 enum types. Multi-tenant via shared schema with `tenant_id` on all entity tables. 28 migration files track schema evolution.
- **n8n (self-hosted)**: Orchestrates the L2 and person enrichment workflows as multi-stage pipelines. The orchestrator workflow fans out to sub-workflows for L1, L2, and person enrichment with batch processing, progress reporting, and loop-back patterns.
- **Native Python enrichment**: L1 enrichment (Perplexity), EU government registry lookups, QC checks, and the DAG executor all run natively in the Flask process, reducing dependency on n8n for new enrichment stages.

### Frontend

- **React 19 + TypeScript + Vite**: Single-page application with TanStack Query v5 for server state management and Tailwind CSS v4 for styling.
- **Virtual scrolling**: Companies and Contacts tables use DOM windowing -- only 60-80 rows are rendered at any time regardless of dataset size, with data fetched via infinite scroll (IntersectionObserver).
- **Chat streaming**: The Playbook chat uses Server-Sent Events (SSE) for real-time streaming of AI responses, tool execution status, and strategy document updates.
- **API layer**: Centralized `apiFetch` (JSON) and `apiUpload` (FormData) functions with TanStack Query hooks for data fetching, caching, and mutation.

### Authentication

- **Local auth**: JWT access + refresh tokens with bcrypt password hashing. Tokens stored in localStorage.
- **IAM SSO**: Integration with VisionVolve IAM service supporting Google and GitHub OAuth. The `/auth/callback` route handles the OAuth code exchange flow.
- **Chrome extension auth**: Same JWT flow via `chrome.storage.local` with service worker auto-refresh.

### Deployment

- **Docker + Caddy**: The API runs in a Docker container. Caddy acts as a reverse proxy handling TLS (automatic via Let's Encrypt), routing (`/api/*` to Flask, everything else to the dashboard), and namespace URL rewriting. Caddy does routing and TLS only -- it never serves static files directly.
- **Nginx sidecar**: Static frontend content is served by an nginx:alpine sidecar container. An init container copies build output to a shared Docker volume, and nginx serves it.
- **Staging**: Separate VPS (3.124.110.199) with its own database (`leadgen_staging`). GitHub Actions CI/CD deploys on push to the `staging` branch. Feature branches can deploy API-only revisions as `/api-rev-{commit}/` for isolated testing.
- **Production**: VPS at 52.58.119.191 with the same architecture. Deploys only from the `main` branch via protected PR workflow.
- **CI/CD**: GitHub Actions runs context-aware testing -- changed files only on staging PRs, full suite on main PRs. Ruff linting, pytest, TypeScript checks, and Playwright E2E tests.

---

## 4. Product Vision

The product vision, documented as a standalone microsite, frames the platform as a **Closed-Loop GTM Engine** -- not a point solution for any single part of go-to-market, but an integrated system where every phase feeds the next and every cycle makes the AI smarter.

### The Flywheel: Try, Run, Evaluate, Improve

The core mental model is a four-phase flywheel that replaces the traditional linear GTM process (plan, execute, hope):

1. **Try** -- Build your strategy. Define your ICP, buyer personas, value propositions, and messaging framework. The AI researches your company, analyzes your market, and co-creates the playbook with you.
2. **Run** -- Source contacts matching your ICP. Enrich them with real data from company websites and government registries. Generate personalized outreach messages calibrated to each persona. Launch campaigns across chosen channels.
3. **Evaluate** -- Track open rates, reply rates, meeting rates, and pipeline generated. The AI surfaces not just metrics but narratives: "ROI framing outperformed innovation framing 3:1 for manufacturing CTOs in DACH."
4. **Improve** -- The AI updates your strategy based on real results. It refines ICP scoring, adjusts messaging frameworks, and reprioritizes channels. The next campaign starts where the last one left off. The loop closes and cycle two begins smarter than cycle one.

Most GTM tools are linear. This is a loop. Results feed back into strategy. Every campaign teaches the next one what to do better.

### AI as Proactive Strategist

The AI is not positioned as a tool to be operated but as a teammate with initiative. The vision defines six core traits:

1. **Asks the right questions** -- Proactively identifies gaps in the strategy and asks targeted, specific questions to fill them. Never generic prompts.
2. **Does the homework** -- Researches company websites, scrapes data, analyzes markets, all without being asked. Comes back with findings, not questions.
3. **Reports and recommends** -- Presents structured findings with clear recommendations. Not data dumps -- actionable insights with a point of view.
4. **Checks in, does not check out** -- Follows up when the founder goes quiet. Suggests next steps. Maintains momentum without being pushy.
5. **Knows when it has enough** -- Recognizes when the strategy is specific enough to proceed. Triggers readiness gates and suggests phase transitions.
6. **Adapts in real time** -- Detects frustration, language switches, and topic shifts. Adjusts tone and approach immediately.

### The Founder-as-CEO, AI-as-Strategist Model

The relationship between user and AI is modeled on a CEO and their first strategic hire:

- **The Founder (CEO)**: Approves direction. Steers when needed. Makes the final decisions. Does not have to manage -- just leads.
- **The AI (Strategist)**: Asks the right questions proactively. Does the homework without being asked. Reports back with findings. Makes recommendations. Knows when it has enough.

The design principle: "Your AI strategist doesn't just execute -- it thinks alongside you. It's the first hire that never sleeps, never forgets, and never needs a pep talk."

### Zero Busywork Principle

Every interaction should gather a decision or deliver a result. Specific design commitments include:

- **Auto-save**: Debounced 2.5-second save with no Save button and no "unsaved changes" dialogs.
- **Auto-extract**: Structured data extracted silently after every save so the AI always has current context.
- **Persistent chat**: Same conversation thread across all phases with full history preserved. No context loss, no duplicate questions.
- **Readiness gates**: The AI evaluates when strategy is specific enough to proceed, preventing premature phase jumps.
- **Decision-ready briefings**: No raw data or long reports. Just "here's what I found, here's what I recommend, here's what I need from you."

### The Six-Step Journey

The vision lays out the full user journey as six steps within the continuous loop:

1. **Research** (AI as Analyst) -- AI scrapes your website, researches your market, analyzes competitors, maps your space. You answer 3-5 key questions. The AI does the rest.
2. **Strategize** (AI as GTM Consultant) -- AI builds your GTM playbook: ICP, personas, value propositions, channel strategy, messaging framework. You review, refine, approve. The AI challenges weak assumptions.
3. **Source** (AI as Sourcing Assistant) -- AI finds contacts matching your ICP. Filters by intent signals (hiring patterns, growth indicators, tech stack). Enriches with company data from real websites.
4. **Engage** (AI as Messaging Coach) -- AI generates personalized messages per persona. Calibrates tone, depth, and framing per segment. You review, tweak, approve. Campaigns launch across channels.
5. **Measure** (AI as Performance Analyst) -- Track results. AI surfaces what worked and what did not -- as narratives, not just metrics.
6. **Learn** (AI as Strategist-in-Residence) -- AI updates strategy based on results. Refines ICP scoring. Adjusts frameworks. The next campaign starts where the last left off.

### Compounding Intelligence

The vision describes two layers of learning that compound over time:

- **Your Data (private)**: Every campaign result trains your AI on your market. It learns your language, your buyer psychology, your competitive position. No one else gets this data.
- **Network Intelligence (anonymized, aggregated)**: Insights from all customers make everyone's AI smarter. Patterns that no single company could discover alone -- such as which channels outperform for specific segments, or which framing resonates with particular buyer personas.

The AI evolves along a trajectory: Day 1 (Good Strategist) -> Month 1 (Great Strategist) -> Month 6 (Expert Strategist) -> Year 1 (Unfair Advantage). The accumulated insight from hundreds of cycles creates an intelligence moat that competitors cannot replicate.

### Unit Economics

The vision projects AI-native margins:

- AI costs of $1-17 per user per month, yielding 96-97% gross margins at SaaS pricing.
- Three pricing tiers: Starter ($49/mo, 50 companies), Growth ($149/mo, 200 companies), Scale ($399/mo, 500 companies).
- Per-unit costs: $0.015 per fully enriched company, $0.004 per researched contact, $0.008 per chat turn, $0.0016 per outreach message.
- Cost composition: L2 enrichment (47%), person enrichment (22%), playbook chat (16%), everything else (15%).
- Break-even at 25 users. 80+ months runway on the 4M CZK founder investment.

---

## 5. Roadmap Themes

Based on the agentic architecture documentation and current system design, the following themes define the product's technical evolution.

### Agentic Orchestration (LangGraph Multi-Agent)

The platform is migrating from a monolithic agent loop to a LangGraph StateGraph-based multi-agent architecture. The orchestrator agent classifies user intent and routes to specialist agents:

- **Strategy Agent**: Playbook editing, section generation, ICP and persona definition.
- **Research Agent**: Web search, company research, enrichment coordination. Orchestrates sub-agents (Company Profiler, Contact Enricher, Market Analyst, Document Processor) for parallel research.
- **Outreach Agent**: Message generation, personalization, campaign planning.
- **Data Agent**: Contact management, enrichment pipeline orchestration, CRM queries.

Orchestration patterns include sequential handoff (research completes, results pass to strategy), parallel fan-out (company profiler and contact enricher run simultaneously), and hierarchical delegation (research agent orchestrates its own sub-agents).

### Multi-Model Routing

Different agent nodes use different models based on task complexity: Haiku for intent classification and simple Q&A (fast, cheap), Sonnet for strategy generation and research synthesis (strong reasoning), and Opus for complex reasoning when the task warrants premium quality. This reduces cost while maintaining output quality where it matters.

### Generative UI

The target architecture enables the agent to send state updates that the frontend renders as rich components inline in the chat -- tables, charts, approval forms, contact previews -- rather than plain text. This is enabled by the AG-UI protocol's `STATE_DELTA` events and shared state synchronization between agent and frontend.

### AG-UI Protocol

AG-UI (Agent-to-User Interface) is an open protocol replacing the current custom SSE event types with standardized events: `RUN_STARTED`, `TEXT_MESSAGE_CONTENT`, `TOOL_CALL_START`, `STATE_DELTA`, `STATE_SNAPSHOT`, and others. This enables:

- Real-time shared state between agent and frontend (agent updates company data, frontend table updates immediately).
- Inline approval gates with proper UI (not just text prompts).
- Tool approval UX ("Agent wants to enrich 50 contacts at an estimated cost of 500 tokens. Approve?").
- Standardized streaming that third-party clients can consume.

### Halt Gates and Human-in-the-Loop

LangGraph's `interrupt()` mechanism pauses graph execution, serializes state, and resumes when the user responds. This enables structured decision points:

- **Scope gate**: When research finds multiple products, pause and ask the user which to focus on.
- **Direction gate**: When multiple ICP directions are viable, present options and wait for a decision.
- **Review gate**: Before finalizing strategy or launching a campaign, present a summary for explicit approval.

These gates replace ad-hoc confirmation prompts with a formal mechanism that preserves full execution state.

### Prompt Architecture Optimization

The target prompt architecture uses layered caching to reduce token consumption by 50-70%:

- **Layer 0 (Identity)**: Cacheable role definition, rules, and tone (~800 tokens).
- **Layer 1 (Capabilities)**: Cacheable, phase-filtered tool descriptions (~1-2K tokens).
- **Layer 2 (Context)**: Dynamic phase instructions, completeness status, enrichment summary (~1-5K tokens).
- **Layer 3 (Conversation)**: Summarized older messages plus recent verbatim messages (~1-4K tokens).

Combined with Anthropic's prompt caching, this reduces per-turn input from 200-500K tokens to approximately 50K cached plus 75-175K dynamic tokens.

### Cost Controls and Token Management

The platform tracks LLM usage at every level -- per API call, per message, per campaign contact, per campaign, and per tenant. This enables:

- Pre-generation cost estimates shown to users before committing to expensive operations.
- Token/credit budgets for namespace admins with usage dashboards.
- Per-provider cost breakdown for super admins.
- Cost-aware model selection (Haiku for cheap operations, Sonnet for important ones, Opus reserved for high-value reasoning).

### Future Horizon

The longer-term vision includes capabilities not yet in active development:

- **Continuous learning loop**: Campaign results automatically refine strategy and ICP scoring without manual intervention.
- **Cross-customer intelligence**: Anonymized, aggregated insights from all customers improve the AI for everyone.
- **Voice dialog**: Hands-free GTM strategy sessions -- review contacts while walking, approve messages over coffee.
- **AI avatar**: An animated visual presence for the AI strategist, making solo founder work feel less isolated.
- **Multi-language adaptation**: Seamless switching when the user shifts languages mid-conversation.
- **Predictive conversion scoring**: AI predicts which contacts are most likely to convert based on accumulated cycle data.
