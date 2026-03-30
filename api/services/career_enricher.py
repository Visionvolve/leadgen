"""Career history enrichment via Perplexity.

Researches a contact's career history, previous companies, role progression,
industry experience, and total years of experience using a single Perplexity
sonar call. Writes results to the contact_enrichment table.
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

PERPLEXITY_MAX_TOKENS = 800
PERPLEXITY_TEMPERATURE = 0.2

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

CAREER_SYSTEM_PROMPT = """\
You are researching a B2B contact's career history for sales intelligence.

## SEARCH DISAMBIGUATION - CRITICAL
The person's name may be common. You MUST verify results match:
1. The company name AND domain provided
2. The job title or seniority level provided

Do NOT include career information about similarly-named individuals.

## RESEARCH FOCUS
1. CURRENT ROLE: Verify current position and tenure
2. PREVIOUS COMPANIES: Name, role held, approximate duration, industry
3. ROLE PROGRESSION: Promotions, lateral moves, career direction
4. TENURE PATTERNS: Average time at each company, job-hopper vs loyal
5. INDUSTRY EXPERIENCE: Which industries they have worked in and for how long
6. TOTAL EXPERIENCE: Approximate total years of professional experience
7. EDUCATION: Degrees, universities, MBA, PhD, etc.
8. CERTIFICATIONS: Professional certifications (PMP, AWS, Scrum, etc.)
9. EXPERTISE AREAS: Key skills and domain expertise

## OUTPUT FORMAT
Return ONLY a JSON object. No markdown. No code fences. Start with {.

{
  "career_trajectory": "ascending|lateral|descending|early_career|unknown",
  "career_summary": "Brief narrative of career path and progression",
  "previous_companies": [
    {"name": "Company", "role": "Title", "duration": "2y", "industry": "sector"}
  ],
  "industry_experience": [
    {"industry": "sector", "years": 5}
  ],
  "total_experience_years": 15,
  "tenure_pattern": "Description of tenure patterns (e.g., avg 3-4 years per role)",
  "career_highlights": "Notable achievements, promotions, career pivots",
  "education": "Degrees, institutions, graduation years. Or 'Unknown'",
  "certifications": "Professional certifications. Or 'None found'",
  "expertise_areas": ["area1", "area2", "area3"],
  "data_confidence": "high|medium|low"
}"""

CAREER_USER_TEMPLATE = """\
Research career history for this B2B contact:

Name: {full_name}
Current Title: {job_title}
Current Company: {company_name}
Company Domain: {domain}
LinkedIn URL: {linkedin_url}
Location: {city}, {country}

Current date: {current_date}

Search approach:
1. "{full_name}" "{company_name}" site:linkedin.com
2. "{full_name}" resume OR CV OR career OR experience
3. "{full_name}" "{job_title}" previous OR formerly OR ex-

Verify all results are about THIS person at {domain}."""


# ---------------------------------------------------------------------------
# Core enrichment
# ---------------------------------------------------------------------------


@traceable(name="enrich_career_history", run_type="chain")
def enrich_career(
    entity_id, tenant_id=None, previous_data=None, boost=False, user_id=None
):
    """Enrich a contact with career history data.

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

    pplx_model = get_model_for_stage("career", boost)

    try:
        research_data, cost = _research_career(
            contact_data,
            pplx_model,
            user_id=user_id,
            enrichment_language=enrichment_lang,
        )
        total_cost += cost
    except Exception as exc:
        logger.error("Career research failed for %s: %s", entity_id, exc)
        return {"error": str(exc), "enrichment_cost_usd": total_cost}

    # 2. Compute quality score for career block
    from .quality_scoring import assess_block_quality, parse_confidence

    career_data = {
        "career_highlights": research_data.get("career_highlights"),
        "previous_companies": research_data.get("previous_companies"),
        "education": research_data.get("education"),
        "certifications": research_data.get("certifications"),
        "expertise_areas": research_data.get("expertise_areas"),
    }
    block_flags = []
    prev = research_data.get("previous_companies")
    if (
        not prev or (isinstance(prev, list) and len(prev) == 0)
    ) and not research_data.get("career_highlights"):
        block_flags.append("no_career_history")

    quality = assess_block_quality(
        data=career_data,
        block_code="career",
        confidence=parse_confidence(research_data.get("confidence")),
        extra_flags=block_flags,
    )

    # 3. Upsert to contact_enrichment
    _upsert_career_enrichment(entity_id, research_data, total_cost, quality)

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
    """Load contact + company data for career research."""
    row = db.session.execute(
        text("""
            SELECT ct.first_name, ct.last_name, ct.job_title,
                   ct.linkedin_url, ct.location_city, ct.location_country,
                   ct.tenant_id,
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
        "city": row[4] or "",
        "country": row[5] or "",
        "tenant_id": str(row[6]),
        "company_name": row[7] or "",
        "domain": row[8] or "",
    }


# ---------------------------------------------------------------------------
# Research call
# ---------------------------------------------------------------------------


def _research_career(contact_data, model, user_id=None, enrichment_language=None):
    """Call Perplexity for career history research."""
    user_prompt = CAREER_USER_TEMPLATE.format(
        full_name=contact_data["full_name"],
        job_title=contact_data["job_title"],
        company_name=contact_data["company_name"],
        domain=contact_data["domain"],
        linkedin_url=contact_data["linkedin_url"],
        city=contact_data["city"],
        country=contact_data["country"],
        current_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )

    effective_system_prompt = CAREER_SYSTEM_PROMPT
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
                operation="career_enrichment",
                model=model,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                provider="perplexity",
                user_id=user_id,
                duration_ms=duration_ms,
                metadata={"contact_id": contact_data.get("id")},
            )
        except Exception as e:
            logger.warning("Failed to log career enrichment usage: %s", e)

    data = _parse_json(resp.content)
    return data, resp.cost_usd


# ---------------------------------------------------------------------------
# Database writes
# ---------------------------------------------------------------------------


def _upsert_career_enrichment(contact_id, data, cost, quality=None):
    """Upsert career enrichment fields into contact_enrichment table."""
    now_str = datetime.now(timezone.utc).isoformat()

    _COLUMNS = (
        "career_trajectory",
        "career_highlights",
        "previous_companies",
        "industry_experience",
        "total_experience_years",
        "education",
        "certifications",
        "expertise_areas",
    )

    # Serialize JSON fields
    prev_companies = data.get("previous_companies", [])
    if isinstance(prev_companies, list):
        prev_companies = json.dumps(prev_companies)
    industry_exp = data.get("industry_experience", [])
    if isinstance(industry_exp, list):
        industry_exp = json.dumps(industry_exp)
    expertise = data.get("expertise_areas", [])
    if isinstance(expertise, list):
        expertise = json.dumps(expertise)

    total_years = data.get("total_experience_years")
    if total_years is not None:
        try:
            total_years = int(total_years)
        except (ValueError, TypeError):
            total_years = None

    # Build career_highlights from career_summary + tenure_pattern if highlights missing
    career_highlights = data.get("career_highlights")
    if not career_highlights:
        parts = []
        if data.get("career_summary"):
            parts.append(data["career_summary"])
        if data.get("tenure_pattern"):
            parts.append(f"Tenure: {data['tenure_pattern']}")
        career_highlights = " | ".join(parts) if parts else None

    params = {
        "cid": str(contact_id),
        "career_trajectory": data.get("career_trajectory", "unknown"),
        "career_highlights": career_highlights,
        "previous_companies": prev_companies,
        "industry_experience": industry_exp,
        "total_experience_years": total_years,
        "education": data.get("education"),
        "certifications": data.get("certifications"),
        "expertise_areas": expertise,
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
        dialect = db.engine.dialect.name
        if dialect == "sqlite":
            db.session.execute(
                text(f"""
                    INSERT OR REPLACE INTO contact_enrichment
                        (contact_id, {col_list}, enriched_at, enrichment_cost_usd)
                    VALUES (:cid, {val_list}, :enriched_at, :cost)
                """),
                params,
            )
        else:
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

    # Update block_quality JSONB with career block score
    if quality:
        from .quality_scoring import update_block_quality

        update_block_quality(db.session, contact_id, "career", quality)


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
    logger.warning("Failed to parse JSON from career response: %s...", raw_text[:200])
    return {}
