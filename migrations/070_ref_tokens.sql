-- Migration 070: Per-contact ref tokens for unique catalog tracking links
--                 (BL-1104 / Milestone v25, Phase 7).
--
-- Context:
--   LCC client requested every contact gets a unique URL to the catalog,
--   with two variants: one showing prices and one without. Each visit must
--   be attributed back to the contact for downstream analytics.
--
--   These ref tokens are distinct from the existing CampaignContact
--   `microsite_partner_token` (campaign-bound, EventFest-only). A ref token
--   is contact-bound, independent of any campaign, and powers the
--   "Generate catalog link" buttons on the Contact detail page.
--
-- Schema:
--   token            CHAR(32) primary key (base32 of 16 random bytes)
--   tenant_id        UUID — tenant ownership (FK enforced in app code)
--   contact_id       UUID — the contact this token is bound to
--   variant          'with_prices' | 'without_prices' (CHECK constraint)
--   created_at       row creation
--   created_by       optional user UUID (FK enforced in app code)
--   expires_at       optional cutoff (NULL = never expires)
--   notes            free-form operator note
--   visit_count      bumped on each public-visit ingestion
--   first_visited_at first time the URL was opened
--   last_visited_at  most recent visit
--
-- Index:
--   (tenant_id, contact_id) speeds the per-contact list endpoint and the
--   idempotency lookup ("does this contact already have a non-expired
--   token of this variant?").
--
-- Idempotent: all `IF NOT EXISTS` so it can replay safely.

BEGIN;

CREATE TABLE IF NOT EXISTS ref_tokens (
    token            CHAR(32) PRIMARY KEY,
    tenant_id        UUID NOT NULL,
    contact_id       UUID NOT NULL,
    variant          TEXT NOT NULL DEFAULT 'with_prices'
                       CHECK (variant IN ('with_prices', 'without_prices')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by       UUID,
    expires_at       TIMESTAMPTZ,
    notes            TEXT,
    visit_count      INTEGER NOT NULL DEFAULT 0,
    first_visited_at TIMESTAMPTZ,
    last_visited_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ref_tokens_contact
    ON ref_tokens (tenant_id, contact_id);

COMMIT;
