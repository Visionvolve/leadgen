-- 069_email_send_log_template_language.sql
--
-- Multilingual mailing foundation (BL-1110, milestone v25 phase 9).
--
-- Records which language variant of a templated email was rendered for
-- a given send attempt and whether the registry had to fall back to the
-- default language. This lets operators audit how often the EN/CS split
-- works and which contacts received the fallback (CS) when their
-- ``contact.language`` was set to an unsupported code.
--
-- - ``template_language``: ISO-639-1 code of the language actually
--   rendered (``cs`` for the production-tested Czech variant, ``en``
--   for English, etc.). NULL for non-templated sends.
-- - ``template_language_fallback``: TRUE iff the requested language
--   variant was not registered and the registry rendered the default
--   (``cs``) instead. NULL for non-templated sends.
--
-- Safe to re-run: uses ``IF NOT EXISTS``.

ALTER TABLE email_send_log
    ADD COLUMN IF NOT EXISTS template_language varchar(8);

ALTER TABLE email_send_log
    ADD COLUMN IF NOT EXISTS template_language_fallback boolean;

COMMENT ON COLUMN email_send_log.template_language IS
    'Language code of the template variant actually rendered (e.g. cs, en). '
    'NULL for non-templated campaigns. Set at send time from the template '
    'registry resolution result.';

COMMENT ON COLUMN email_send_log.template_language_fallback IS
    'TRUE iff the contact''s requested language variant was not registered '
    'and the registry fell back to the default language (cs). NULL for '
    'non-templated campaigns.';
