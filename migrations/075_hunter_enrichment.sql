-- 075_hunter_enrichment.sql
--
-- BL-1212: Hunter.io contact-enrichment results table.
--
-- Holds one row per (contact_id, source, method) for emails sourced from
-- Hunter.io. Distinct from `contact_enrichment_wave2` (Perplexity + SMTP
-- pattern verification) so we can attribute, audit, and roll back Hunter
-- batches independently.
--
-- Conventions:
--   * `source` is a per-batch tag like 'hunter-pilot-2026-05-18' or
--     'hunter-bulk-2026-05-18'. Distinct sources are independent runs and
--     do NOT clash via the UNIQUE constraint.
--   * `method` is one of 'email-finder', 'domain-search', or 'verify'.
--   * `credits_used` defaults to 1; the verifier path may insert
--     supplementary rows with credits_used=1 against the same contact.
--   * `raw_response` keeps the full Hunter payload for auditability.
--
-- Safe to re-run (IF NOT EXISTS throughout).

CREATE TABLE IF NOT EXISTS contact_enrichment_hunter (
    id                    BIGSERIAL PRIMARY KEY,
    contact_id            UUID NOT NULL,
    tenant_id             UUID NOT NULL,
    domain                TEXT,
    found_email           TEXT,
    confidence_score      INTEGER,
    position              TEXT,
    sources_count         INTEGER,
    verification_status   TEXT,
    method                TEXT NOT NULL CHECK (method IN ('email-finder', 'domain-search', 'verify')),
    raw_response          JSONB,
    credits_used          INTEGER NOT NULL DEFAULT 1,
    source                TEXT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT contact_enrichment_hunter_unique
        UNIQUE (contact_id, source, method)
);

CREATE INDEX IF NOT EXISTS idx_hunter_contact ON contact_enrichment_hunter (contact_id);
CREATE INDEX IF NOT EXISTS idx_hunter_tenant  ON contact_enrichment_hunter (tenant_id);
CREATE INDEX IF NOT EXISTS idx_hunter_source  ON contact_enrichment_hunter (source);

COMMENT ON TABLE contact_enrichment_hunter IS
    'Hunter.io per-contact enrichment results (BL-1212). One row per (contact_id, source, method).';
COMMENT ON COLUMN contact_enrichment_hunter.source IS
    'Per-batch tag, e.g. ''hunter-pilot-2026-05-18''. Distinct sources never collide via the UNIQUE constraint.';
COMMENT ON COLUMN contact_enrichment_hunter.method IS
    'One of: email-finder, domain-search, verify. Maps to the Hunter API endpoint that produced the row.';
