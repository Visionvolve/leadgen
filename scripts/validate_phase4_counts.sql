-- Phase 4 — validate per-status counts for a TEST-PHASE4-<ts> campaign.
--
-- Usage:
--   psql "$DATABASE_URL" -f scripts/validate_phase4_counts.sql \
--     -v campaign_name="TEST-PHASE4-20260420T1530Z"
--
-- Expected values (per 04-CONTEXT.md D-06):
--   sent=10, delivered≈10, opened=6, clicked=3, unsubscribed=1, unopened=4

\echo '=== Phase 4 count validation ==='
\echo

SELECT id, name, status, created_at
FROM campaigns
WHERE name = :'campaign_name';

\echo
\echo '--- Per-recipient status ---'

SELECT
  c.email_address                                    AS recipient,
  cc.microsite_partner_token                         AS partner_token,
  esl.sent_at IS NOT NULL                            AS sent,
  esl.delivered_at IS NOT NULL                       AS delivered,
  esl.opened_at IS NOT NULL                          AS opened,
  esl.clicked_at IS NOT NULL                         AS clicked,
  esl.unsubscribed_at IS NOT NULL                    AS unsubscribed,
  esl.bounced_at IS NOT NULL                         AS bounced,
  esl.open_count,
  esl.click_count
FROM campaigns cam
JOIN campaign_contacts cc      ON cc.campaign_id = cam.id
JOIN contacts c                ON c.id = cc.contact_id
LEFT JOIN messages m           ON m.campaign_contact_id = cc.id
LEFT JOIN email_send_log esl   ON esl.resend_message_id = m.resend_message_id
WHERE cam.name = :'campaign_name'
ORDER BY c.email_address;

\echo
\echo '--- Aggregate counts (compare to D-06 expected) ---'

SELECT
  COUNT(*) FILTER (WHERE esl.sent_at IS NOT NULL)          AS sent,
  COUNT(*) FILTER (WHERE esl.delivered_at IS NOT NULL)     AS delivered,
  COUNT(*) FILTER (WHERE esl.opened_at IS NOT NULL)        AS opened,
  COUNT(*) FILTER (WHERE esl.clicked_at IS NOT NULL)       AS clicked,
  COUNT(*) FILTER (WHERE esl.unsubscribed_at IS NOT NULL)  AS unsubscribed,
  COUNT(*) FILTER (WHERE esl.bounced_at IS NOT NULL)       AS bounced,
  COUNT(*) FILTER (WHERE esl.sent_at IS NOT NULL
                   AND esl.opened_at IS NULL)              AS unopened
FROM campaigns cam
JOIN campaign_contacts cc      ON cc.campaign_id = cam.id
LEFT JOIN messages m           ON m.campaign_contact_id = cc.id
LEFT JOIN email_send_log esl   ON esl.resend_message_id = m.resend_message_id
WHERE cam.name = :'campaign_name';

\echo
\echo '--- Microsite activities (invite_redeemed / product_viewed / page_viewed) ---'

SELECT
  c.email_address,
  a.event_type,
  a.occurred_at,
  a.source,
  a.payload
FROM campaigns cam
JOIN campaign_contacts cc      ON cc.campaign_id = cam.id
JOIN contacts c                ON c.id = cc.contact_id
LEFT JOIN activities a         ON a.contact_id = c.id
WHERE cam.name = :'campaign_name'
  AND a.source = 'microsite'
ORDER BY c.email_address, a.occurred_at;

\echo
\echo '--- UA Invite token coverage (partner_token on every CampaignContact) ---'

SELECT
  COUNT(*) FILTER (WHERE cc.microsite_partner_token IS NOT NULL) AS with_token,
  COUNT(*) FILTER (WHERE cc.microsite_partner_token IS NULL)     AS missing_token,
  COUNT(*)                                                        AS total
FROM campaigns cam
JOIN campaign_contacts cc      ON cc.campaign_id = cam.id
WHERE cam.name = :'campaign_name';
