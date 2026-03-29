-- Migration 054: UA Campaign Features
-- Adds campaign language, scheduled launch, company segment, and contact last collaboration date

-- Campaign-level language (cs, de, en, etc.)
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS language VARCHAR(5) DEFAULT 'cs';

-- Campaign scheduled launch date
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS scheduled_launch_at TIMESTAMPTZ;

-- Company segment (obec, spolek, agentura, skola, korporace, dach_agentura)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS segment VARCHAR(50);

-- Contact last collaboration date (active vs sleeping classification)
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_collaboration_at TIMESTAMPTZ;

-- Indexes for segment-based queries
CREATE INDEX IF NOT EXISTS idx_companies_segment ON companies(segment) WHERE segment IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_last_collab ON contacts(last_collaboration_at) WHERE last_collaboration_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_campaigns_language ON campaigns(language) WHERE language IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_campaigns_scheduled ON campaigns(scheduled_launch_at) WHERE scheduled_launch_at IS NOT NULL;
