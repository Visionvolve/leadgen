-- Add execution tracking columns to campaign_steps
ALTER TABLE campaign_steps ADD COLUMN IF NOT EXISTS condition VARCHAR(50) NOT NULL DEFAULT 'always';
ALTER TABLE campaign_steps ADD COLUMN IF NOT EXISTS execution_status VARCHAR(50) NOT NULL DEFAULT 'pending';
ALTER TABLE campaign_steps ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE campaign_steps ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE;

-- Add "Meetup Dual LinkedIn + Email" system template
INSERT INTO campaign_templates (id, tenant_id, name, description, steps, default_config, is_system) VALUES
(
  'a0000000-0000-0000-0000-000000000004',
  NULL,
  'Meetup Dual LinkedIn + Email',
  'Two-step meetup outreach: LinkedIn connection request, then email follow-up if no response.',
  '[
    {"step": 1, "channel": "linkedin_connect", "label": "LinkedIn Connect", "day_offset": 0, "condition": "always", "enabled": true, "needs_pdf": false, "variant_count": 1},
    {"step": 2, "channel": "email", "label": "Email Follow-up", "day_offset": 3, "condition": "no_response", "enabled": true, "needs_pdf": false, "variant_count": 1}
  ]'::jsonb,
  '{"tone": "casual", "language": "en"}'::jsonb,
  true
)
ON CONFLICT DO NOTHING;
