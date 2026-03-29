"""Contact details enrichment via Perplexity.

Researches a contact's email, phone, LinkedIn URL, and profile photo
using a single Perplexity sonar call. Only fills in blank fields on the
contacts table -- existing values are never overwritten.
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
    from .llm_logger import log_llm_usage
except ImportError:
    log_llm_usage = None

logger = logging.getLogger(__name__)

PERPLEXITY_MAX_TOKENS = 400
PERPLEXITY_TEMPERATURE = 0.1

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

CONTACT_DETAILS_SYSTEM_PROMPT = """\
You are researching contact details for a B2B professional.

## SEARCH DISAMBIGUATION - CRITICAL
The person's name may be common. You MUST verify results match:
1. The company name AND domain provided
2. The job title provided

Do NOT return contact details for similarly-named individuals.

## RESEARCH FOCUS
1. EMAIL: Business email address (company domain preferred)
2. PHONE: Direct phone or mobile number
3. LINKEDIN: Profile URL (verify it matches this person)
4. PROFILE PHOTO: Professional headshot URL (LinkedIn or company page)

## DATA QUALITY RULES
- Email must use a valid format (user@domain.tld)
- Phone should include country code if available
- LinkedIn URL must be a full profile URL (linkedin.com/in/...)
- Photo URL must be a direct image link

## OUTPUT FORMAT
Return ONLY a JSON object. No markdown. No code fences. Start with {.

{
  "email_address": "user@company.com or null",
  "email_confidence": "high|medium|low",
  "phone_number": "+1234567890 or null",
  "phone_confidence": "high|medium|low",
  "linkedin_url": "https://linkedin.com/in/username or null",
  "profile_photo_url": "https://... or null",
  "data_confidence": "high|medium|low"
}"""

CONTACT_DETAILS_USER_TEMPLATE = """\
Find contact details for this B2B professional:

Name: {full_name}
Job Title: {job_title}
Company: {company_name}
Company Domain: {domain}
Known LinkedIn: {linkedin_url}
Known Email: {email}

Current date: {current_date}

Search approach:
1. "{full_name}" "@{domain}" email
2. "{full_name}" "{company_name}" contact OR email OR phone
3. "{full_name}" site:linkedin.com/in/

Verify all results are about THIS person at {domain}."""


# ---------------------------------------------------------------------------
# Core enrichment
# ---------------------------------------------------------------------------


def enrich_contact_details(
    entity_id, tenant_id=None, previous_data=None, boost=False, user_id=None
):
    """Enrich a contact with contact details (email, phone, etc.).

    Only fills in blank fields -- existing values are preserved.

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

    pplx_model = get_model_for_stage("contact_details", boost)

    try:
        research_data, cost = _research_contact_details(
            contact_data,
            pplx_model,
            user_id=user_id,
            enrichment_language=enrichment_lang,
        )
        total_cost += cost
    except Exception as exc:
        logger.error("Contact details research failed for %s: %s", entity_id, exc)
        return {"error": str(exc), "enrichment_cost_usd": total_cost}

    # 2. Compute quality score for contact_details block
    from .quality_scoring import assess_block_quality, parse_confidence

    details_data = {
        "email": research_data.get("email_address") or contact_data.get("email"),
        "phone": research_data.get("phone_number") or contact_data.get("phone"),
        "linkedin_url": research_data.get("linkedin_url")
        or contact_data.get("linkedin_url"),
        "profile_data_confidence": research_data.get("confidence"),
    }
    block_flags = []
    if details_data.get("email") and not contact_data.get("email_verified"):
        block_flags.append("email_unverified")

    quality = assess_block_quality(
        data=details_data,
        block_code="contact_details",
        confidence=parse_confidence(research_data.get("confidence")),
        extra_flags=block_flags,
    )

    # 3. Update contacts table (only blank fields)
    _update_contact_details(entity_id, contact_data, research_data)

    # 4. Update block_quality on contact_enrichment
    _update_block_quality(entity_id, "contact_details", quality)

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
    """Load current contact data to check which fields are already populated."""
    row = db.session.execute(
        text("""
            SELECT ct.first_name, ct.last_name, ct.job_title,
                   ct.email_address, ct.phone_number, ct.linkedin_url,
                   ct.profile_photo_url, ct.tenant_id,
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
        "email": row[3] or "",
        "phone": row[4] or "",
        "linkedin_url": row[5] or "",
        "profile_photo_url": row[6] or "",
        "tenant_id": str(row[7]),
        "company_name": row[8] or "",
        "domain": row[9] or "",
    }


# ---------------------------------------------------------------------------
# Research call
# ---------------------------------------------------------------------------


def _research_contact_details(
    contact_data, model, user_id=None, enrichment_language=None
):
    """Call Perplexity for contact details research."""
    user_prompt = CONTACT_DETAILS_USER_TEMPLATE.format(
        full_name=contact_data["full_name"],
        job_title=contact_data["job_title"],
        company_name=contact_data["company_name"],
        domain=contact_data["domain"],
        linkedin_url=contact_data["linkedin_url"] or "Not provided",
        email=contact_data["email"] or "Not provided",
        current_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )

    effective_system_prompt = CONTACT_DETAILS_SYSTEM_PROMPT
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
                operation="contact_details_enrichment",
                model=model,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                provider="perplexity",
                user_id=user_id,
                duration_ms=duration_ms,
                metadata={"contact_id": contact_data.get("id")},
            )
        except Exception as e:
            logger.warning("Failed to log contact details enrichment usage: %s", e)

    data = _parse_json(resp.content)
    return data, resp.cost_usd


# ---------------------------------------------------------------------------
# Database writes
# ---------------------------------------------------------------------------


def _update_block_quality(contact_id, block_name, quality):
    """Update block_quality JSONB field with a specific block's quality data."""
    block_entry = json.dumps(
        {
            "score": quality.quality_score,
            "confidence": quality.confidence,
            "flags": quality.qc_flags,
            "field_coverage": quality.field_coverage,
        }
    )
    dialect = db.engine.dialect.name
    if dialect == "sqlite":
        row = db.session.execute(
            text(
                "SELECT block_quality FROM contact_enrichment WHERE contact_id = :cid"
            ),
            {"cid": str(contact_id)},
        ).fetchone()
        existing = {}
        if row and row[0]:
            try:
                existing = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except (json.JSONDecodeError, TypeError):
                existing = {}
        existing[block_name] = json.loads(block_entry)
        db.session.execute(
            text(
                "UPDATE contact_enrichment SET block_quality = :bq WHERE contact_id = :cid"
            ),
            {"cid": str(contact_id), "bq": json.dumps(existing)},
        )
    else:
        db.session.execute(
            text("""
                UPDATE contact_enrichment
                SET block_quality = COALESCE(block_quality, '{}'::jsonb) || jsonb_build_object(:block, CAST(:entry AS jsonb))
                WHERE contact_id = :cid
            """),
            {"cid": str(contact_id), "block": block_name, "entry": block_entry},
        )


def _update_contact_details(contact_id, existing, research_data):
    """Update contacts table — only fill empty fields, never overwrite.

    Args:
        contact_id: UUID string
        existing: dict with current contact field values
        research_data: dict from Perplexity research
    """
    updates = {}
    params = {"cid": str(contact_id)}

    # Email — only if currently empty
    new_email = research_data.get("email_address")
    if new_email and new_email != "null" and not existing.get("email"):
        updates["email_address"] = ":email_address"
        params["email_address"] = new_email

    # Phone — only if currently empty
    new_phone = research_data.get("phone_number")
    if new_phone and new_phone != "null" and not existing.get("phone"):
        updates["phone_number"] = ":phone_number"
        params["phone_number"] = new_phone

    # LinkedIn — update if found and existing is empty or lower confidence
    new_linkedin = research_data.get("linkedin_url")
    if new_linkedin and new_linkedin != "null" and not existing.get("linkedin_url"):
        updates["linkedin_url"] = ":linkedin_url"
        params["linkedin_url"] = new_linkedin

    # Profile photo — update if found (always, since photo URLs change)
    new_photo = research_data.get("profile_photo_url")
    if new_photo and new_photo != "null":
        updates["profile_photo_url"] = ":profile_photo_url"
        params["profile_photo_url"] = new_photo

    if not updates:
        logger.info("No empty fields to fill for contact %s", contact_id)
        return

    set_clause = ", ".join(
        f"{col} = {placeholder}" for col, placeholder in updates.items()
    )

    try:
        db.session.execute(
            text(f"UPDATE contacts SET {set_clause} WHERE id = :cid"),
            params,
        )
    except Exception as e:
        logger.error("Failed to update contact details for %s: %s", contact_id, e)


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
    logger.warning(
        "Failed to parse JSON from contact details response: %s...", raw_text[:200]
    )
    return {}
