"""Social & online presence enrichment via Perplexity.

Researches a contact's social media presence, speaking engagements,
publications, and online activity using a single Perplexity sonar call.
Writes results to the contact_enrichment table.
"""

import json
import logging
import re
import time as _time
from datetime import datetime, timezone

from sqlalchemy import text

from ..models import db
from .perplexity_client import PerplexityClient
from .stage_registry import get_model_for_stage

try:
    from langsmith import traceable
except ImportError:  # pragma: no cover

    def traceable(**kwargs):
        def decorator(fn):
            return fn

        return decorator


try:
    from .llm_logger import log_llm_usage
except ImportError:
    log_llm_usage = None

logger = logging.getLogger(__name__)

PERPLEXITY_MAX_TOKENS = 600
PERPLEXITY_TEMPERATURE = 0.2

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SOCIAL_SYSTEM_PROMPT = """\
You are researching a B2B contact's social media and online presence \
for personalized outreach intelligence.

## SEARCH DISAMBIGUATION - CRITICAL
The person's name may be common. You MUST verify results match:
1. The company name AND domain provided
2. The job title or seniority level provided

Do NOT include information about similarly-named individuals at other companies.

## RESEARCH FOCUS
1. LINKEDIN: Profile URL, activity level, posting frequency, topics
2. TWITTER/X: Handle, activity, topics discussed
3. GITHUB: Username, public repos, contributions
4. SPEAKING: Conference talks, webinars, panels, podcasts
5. PUBLICATIONS: Blog posts, articles, whitepapers, research papers

## OUTPUT FORMAT
Return ONLY a JSON object. No markdown. No code fences. Start with {.

{
  "linkedin_url": "Full LinkedIn profile URL or null",
  "linkedin_activity": "Description of LinkedIn activity level and topics. Or 'None found'",
  "twitter_handle": "@handle or null",
  "twitter_activity": "Description of Twitter activity. Or 'None found'",
  "github_username": "username or null",
  "github_activity": "Description of GitHub activity. Or 'None found'",
  "speaking_engagements": "Conferences, webinars, panels, podcasts. Or 'None found'",
  "publications": "Articles, blog posts, whitepapers. Or 'None found'",
  "online_presence_summary": "Overall assessment of online visibility",
  "data_confidence": "high|medium|low"
}"""

SOCIAL_USER_TEMPLATE = """\
Research social media and online presence for this B2B contact:

Name: {full_name}
Job Title: {job_title}
Company: {company_name}
Company Domain: {domain}
LinkedIn URL: {linkedin_url}

Current date: {current_date}

Search approach:
1. "{full_name}" "{company_name}" site:linkedin.com
2. "{full_name}" "{company_name}" site:twitter.com OR site:x.com
3. "{full_name}" "{company_name}" site:github.com
4. "{full_name}" speaker OR conference OR webinar OR podcast
5. "{full_name}" article OR blog OR publication

Verify all results are about THIS person at {domain}."""


# ---------------------------------------------------------------------------
# Core enrichment
# ---------------------------------------------------------------------------


@traceable(name="enrich_social_online", run_type="chain")
def enrich_social(
    entity_id, tenant_id=None, previous_data=None, boost=False, user_id=None
):
    """Enrich a contact with social and online presence data.

    Args:
        entity_id: UUID string of the contact
        tenant_id: UUID string (optional, read from contact)
        previous_data: dict of prior enrichment (for re-enrichment)
        boost: if True, use higher-quality Perplexity model
        user_id: optional UUID string for LLM usage attribution

    Returns dict with enrichment_cost_usd (and optionally error).
    """
    total_cost = 0.0

    # 1. Load contact data
    contact_data = _load_contact(entity_id)
    if not contact_data:
        return {"error": "Contact not found", "enrichment_cost_usd": 0}

    # Resolve enrichment language from tenant settings
    enrichment_lang = None
    try:
        from ..models import Tenant

        eff_tenant_id = tenant_id or contact_data.get("tenant_id")
        if eff_tenant_id:
            tenant_obj = db.session.get(Tenant, eff_tenant_id)
            if tenant_obj:
                from .language import get_enrichment_language

                enrichment_lang = get_enrichment_language(tenant_obj)
    except Exception:
        pass

    pplx_model = get_model_for_stage("social", boost)

    try:
        research_data, cost = _research_social(
            contact_data,
            pplx_model,
            user_id=user_id,
            enrichment_language=enrichment_lang,
        )
        total_cost += cost
    except Exception as exc:
        logger.error("Social research failed for %s: %s", entity_id, exc)
        return {"error": str(exc), "enrichment_cost_usd": total_cost}

    # 2. Compute quality score for social block
    from .quality_scoring import assess_block_quality, parse_confidence

    # Map LLM response fields to quality scoring fields
    linkedin_activity = research_data.get("linkedin_activity")
    if linkedin_activity and linkedin_activity.lower() in ("none found", "null"):
        linkedin_activity = None
    online_summary = research_data.get("online_presence_summary")
    if online_summary and online_summary.lower() in ("none found", "null"):
        online_summary = None

    social_data = {
        "linkedin_profile_summary": linkedin_activity
        or research_data.get("linkedin_url"),
        "twitter_handle": research_data.get("twitter_handle"),
        "github_username": research_data.get("github_username"),
        "speaking_engagements": research_data.get("speaking_engagements"),
        "publications": research_data.get("publications"),
        "public_presence_level": research_data.get("public_presence_level")
        or research_data.get("data_confidence"),
        "thought_leadership": online_summary,
    }
    block_flags = []
    if not linkedin_activity and not research_data.get("linkedin_url"):
        block_flags.append("no_linkedin")

    quality = assess_block_quality(
        data=social_data,
        block_code="social",
        confidence=parse_confidence(research_data.get("confidence")),
        extra_flags=block_flags,
    )

    # 3. Upsert to contact_enrichment
    _upsert_social_enrichment(entity_id, research_data, total_cost, quality)

    # 4. Update linkedin_url on contacts table if found
    linkedin_url = research_data.get("linkedin_url")
    if linkedin_url and linkedin_url != "null":
        _update_contact_linkedin(entity_id, linkedin_url)

    db.session.commit()

    return {
        "enrichment_cost_usd": total_cost,
        "quality_score": quality.quality_score,
        "qc_flags": quality.qc_flags,
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_contact(contact_id):
    """Load contact + company data for social research."""
    row = db.session.execute(
        text("""
            SELECT ct.first_name, ct.last_name, ct.job_title,
                   ct.linkedin_url, ct.tenant_id,
                   c.name AS company_name, c.domain
            FROM contacts ct
            JOIN companies c ON ct.company_id = c.id
            WHERE ct.id = :cid
        """),
        {"cid": str(contact_id)},
    ).fetchone()

    if not row:
        return None

    return {
        "id": str(contact_id),
        "first_name": row[0] or "",
        "last_name": row[1] or "",
        "full_name": "{} {}".format(row[0] or "", row[1] or "").strip(),
        "job_title": row[2] or "",
        "linkedin_url": row[3] or "Not provided",
        "tenant_id": str(row[4]),
        "company_name": row[5] or "",
        "domain": row[6] or "",
    }


# ---------------------------------------------------------------------------
# Research call
# ---------------------------------------------------------------------------


def _research_social(contact_data, model, user_id=None, enrichment_language=None):
    """Call Perplexity for social media and online presence research."""
    user_prompt = SOCIAL_USER_TEMPLATE.format(
        full_name=contact_data["full_name"],
        job_title=contact_data["job_title"],
        company_name=contact_data["company_name"],
        domain=contact_data["domain"],
        linkedin_url=contact_data["linkedin_url"],
        current_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )

    effective_system_prompt = SOCIAL_SYSTEM_PROMPT
    if enrichment_language and enrichment_language != "en":
        from ..display import LANGUAGE_NAMES

        lang_name = LANGUAGE_NAMES.get(enrichment_language, enrichment_language)
        effective_system_prompt += (
            f"\n\nIMPORTANT: Conduct research and write all descriptive output "
            f"in {lang_name}. Field names and JSON keys must remain in English, "
            f"but descriptive text should be in {lang_name}."
        )

    client = PerplexityClient()
    start_time = _time.time()
    resp = client.query(
        system_prompt=effective_system_prompt,
        user_prompt=user_prompt,
        model=model,
        max_tokens=PERPLEXITY_MAX_TOKENS,
        temperature=PERPLEXITY_TEMPERATURE,
    )
    duration_ms = int((_time.time() - start_time) * 1000)

    if log_llm_usage:
        try:
            log_llm_usage(
                tenant_id=contact_data.get("tenant_id"),
                operation="social_enrichment",
                model=model,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                provider="perplexity",
                user_id=user_id,
                duration_ms=duration_ms,
                metadata={"contact_id": contact_data.get("id")},
            )
        except Exception as e:
            logger.warning("Failed to log social enrichment usage: %s", e)

    data = _parse_json(resp.content)
    return data, resp.cost_usd


# ---------------------------------------------------------------------------
# Database writes
# ---------------------------------------------------------------------------


def _upsert_social_enrichment(contact_id, data, cost, quality=None):
    """Upsert social enrichment fields into contact_enrichment table."""
    now_str = datetime.now(timezone.utc).isoformat()

    _COLUMNS = (
        "linkedin_profile_summary",
        "twitter_handle",
        "speaking_engagements",
        "publications",
        "github_username",
        "public_presence_level",
        "thought_leadership",
    )

    # Map LLM response fields to DB columns:
    # - linkedin_activity -> linkedin_profile_summary
    # - online_presence_summary -> thought_leadership (general online presence narrative)
    # - public_presence_level is not in prompt but can be inferred; use data_confidence as proxy
    linkedin_summary = data.get("linkedin_activity")
    if linkedin_summary and linkedin_summary.lower() in ("none found", "null"):
        linkedin_summary = None

    online_summary = data.get("online_presence_summary")
    if online_summary and online_summary.lower() in ("none found", "null"):
        online_summary = None

    # Build a combined linkedin profile summary from URL + activity description
    linkedin_parts = []
    if data.get("linkedin_url") and data["linkedin_url"] not in ("null", None):
        linkedin_parts.append(f"URL: {data['linkedin_url']}")
    if linkedin_summary:
        linkedin_parts.append(linkedin_summary)
    full_linkedin_summary = "\n".join(linkedin_parts) if linkedin_parts else None

    # Derive public_presence_level from data_confidence or explicit field
    presence_level = data.get("public_presence_level")
    if not presence_level:
        # Heuristic: if we found linkedin + twitter + github, high; linkedin only, medium; nothing, low
        found_count = sum(
            1
            for k in ("linkedin_url", "twitter_handle", "github_username")
            if data.get(k) and data[k] not in ("null", None, "None found")
        )
        if found_count >= 2:
            presence_level = "high"
        elif found_count == 1:
            presence_level = "medium"
        else:
            presence_level = "low"

    params = {
        "cid": str(contact_id),
        "linkedin_profile_summary": full_linkedin_summary,
        "twitter_handle": data.get("twitter_handle"),
        "speaking_engagements": data.get("speaking_engagements"),
        "publications": data.get("publications"),
        "github_username": data.get("github_username"),
        "public_presence_level": presence_level,
        "thought_leadership": online_summary,
        "enriched_at": now_str,
        "cost": cost,
    }

    col_list = ", ".join(_COLUMNS)
    val_list = ", ".join(f":{c}" for c in _COLUMNS)
    update_list = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLUMNS)

    try:
        db.session.execute(
            text(f"""
                INSERT INTO contact_enrichment
                    (contact_id, {col_list}, enriched_at, enrichment_cost_usd)
                VALUES (:cid, {val_list}, :enriched_at, :cost)
                ON CONFLICT (contact_id) DO UPDATE SET
                    {update_list},
                    enriched_at = EXCLUDED.enriched_at,
                    enrichment_cost_usd = EXCLUDED.enrichment_cost_usd
            """),
            params,
        )
    except Exception:
        db.session.rollback()
        db.session.execute(
            text(f"""
                INSERT OR REPLACE INTO contact_enrichment
                    (contact_id, {col_list}, enriched_at, enrichment_cost_usd)
                VALUES (:cid, {val_list}, :enriched_at, :cost)
            """),
            params,
        )

    # Update block_quality JSONB with social block score
    if quality:
        from .quality_scoring import update_block_quality

        update_block_quality(db.session, contact_id, "social", quality)


def _update_contact_linkedin(contact_id, linkedin_url):
    """Update linkedin_url on contacts table if currently empty."""
    try:
        db.session.execute(
            text("""
                UPDATE contacts SET linkedin_url = :url
                WHERE id = :cid AND (linkedin_url IS NULL OR linkedin_url = '')
            """),
            {"cid": str(contact_id), "url": linkedin_url},
        )
    except Exception as e:
        logger.warning("Failed to update contact linkedin_url: %s", e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json(raw_text):
    """Parse JSON from LLM response, handling markdown fences."""
    if not raw_text:
        return {}
    cleaned = re.sub(r"```(?:json)?\s*", "", raw_text)
    cleaned = cleaned.strip().rstrip("`")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    logger.warning("Failed to parse JSON from social response: %s...", raw_text[:200])
    return {}
