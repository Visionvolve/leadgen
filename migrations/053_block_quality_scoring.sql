-- Migration 053: Add quality scoring columns to enrichment tables.
-- L1 already has quality_score, confidence, qc_flags — skip it.
-- All new columns are nullable so existing rows remain valid.

-- Deep Research: profile table
ALTER TABLE company_enrichment_profile
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- Deep Research: opportunity table
ALTER TABLE company_enrichment_opportunity
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- Strategic Signals
ALTER TABLE company_enrichment_signals
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- Market (L2 sub-table)
ALTER TABLE company_enrichment_market
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- News & PR
ALTER TABLE company_news
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- Legal & Registry (already has match_confidence as confidence proxy)
ALTER TABLE company_legal_profile
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- Contact Enrichment (single table for all contact blocks)
ALTER TABLE contact_enrichment
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS block_quality jsonb DEFAULT '{}'::jsonb;

-- Indexes for quality-based queries (find low-quality enrichments for re-enrichment)
CREATE INDEX IF NOT EXISTS idx_company_enrichment_profile_quality
  ON company_enrichment_profile (quality_score) WHERE quality_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_company_enrichment_signals_quality
  ON company_enrichment_signals (quality_score) WHERE quality_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_company_news_quality
  ON company_news (quality_score) WHERE quality_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_company_legal_profile_quality
  ON company_legal_profile (quality_score) WHERE quality_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contact_enrichment_quality
  ON contact_enrichment (quality_score) WHERE quality_score IS NOT NULL;
