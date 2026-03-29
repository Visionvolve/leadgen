"""Person enrichment via Perplexity + Anthropic synthesis.

Migrates the n8n Person L2 workflow to native Python. Three-phase approach:
1. Research: Two Perplexity calls (Profile + Decision Signals) using sonar-pro
2. Validate & Score: Deterministic scoring (seniority, department, AI champion, authority)
3. Synthesis: Anthropic Claude creates personalization strategy

After enrichment, contacts get processed_enrich=True and scored fields updated.
"""

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import text

from ..models import db
from .anthropic_client import AnthropicClient
from .perplexity_client import PerplexityClient
from .stage_registry import get_model_for_stage

try:
    from .llm_logger import log_llm_usage
except ImportError:
    log_llm_usage = None

logger = logging.getLogger(__name__)

PERPLEXITY_MAX_TOKENS = 800
PERPLEXITY_TEMPERATURE = 0.2
ANTHROPIC_MAX_TOKENS = 800
ANTHROPIC_TEMPERATURE = 0.7
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"

# ---------------------------------------------------------------------------
# Prompts: Profile research
# ---------------------------------------------------------------------------

PROFILE_SYSTEM_PROMPT = """\
You are researching a B2B sales contact for personalized outreach. \
Your job is to verify the person's current role and gather professional context.

## SEARCH DISAMBIGUATION - CRITICAL
The person's name may be common. You MUST verify results match:
1. The company name AND domain provided
2. The job title or seniority level provided
3. The geographic region (if provided)

Do NOT include information about similarly-named individuals at other companies.

## RESEARCH FOCUS
1. ROLE VERIFICATION: Confirm current role at this specific company
2. CAREER TRAJECTORY: Previous roles, tenure patterns, promotions
3. THOUGHT LEADERSHIP: LinkedIn posts, articles, speaking engagements, podcasts
4. PROFESSIONAL BACKGROUND: Education, certifications, areas of expertise
5. PUBLIC PRESENCE: Recent interviews, quotes, conference appearances

## DATE RELEVANCE
Current date is provided by the user.
- Role verification: Must be current (within last 6 months)
- Career history: Full history is relevant
- Thought leadership: Prioritize last 24 months
- If role appears outdated, flag as "role_verification_needed"

## OUTPUT FORMAT
Return ONLY a JSON object. No markdown. No code fences. Start with {.

{
  "current_role_verified": true|false,
  "role_verification_source": "Source where current role was confirmed",
  "role_mismatch_flag": "If title doesn't match input, explain. Or null",
  "career_highlights": "Key career moves, companies, tenure patterns. Max 5.",
  "career_trajectory": "ascending|lateral|descending|early_career|unknown",
  "thought_leadership": "LinkedIn posts, articles, speaking. Or 'None found'",
  "thought_leadership_topics": ["topic1", "topic2"],
  "education": "Degrees, institutions. Or 'Unknown'",
  "certifications": "Professional certifications. Or 'None found'",
  "expertise_areas": ["area1", "area2"],
  "public_presence_level": "high|medium|low|none",
  "data_confidence": "high|medium|low"
}"""

PROFILE_USER_TEMPLATE = """\
Research professional background for this B2B contact:

Name: {full_name}
Job Title: {job_title}
Company: {company_name}
Company Domain: {domain}
LinkedIn URL: {linkedin_url}
Location: {city}, {country}

Current date: {current_date}

Search approach:
1. "{full_name}" "{company_name}" site:linkedin.com
2. "{full_name}" "{company_name}" "{job_title}"
3. "{full_name}" speaker OR podcast OR interview

Verify all results are about THIS person at {domain}."""

# ---------------------------------------------------------------------------
# Prompts: Decision signals research
# ---------------------------------------------------------------------------

SIGNALS_SYSTEM_PROMPT = """\
You are researching decision-making authority and AI/innovation interest \
for a B2B sales contact.

## SEARCH DISAMBIGUATION - CRITICAL
Verify all results match the person AND company provided.

## RESEARCH FOCUS
1. AI/INNOVATION INTEREST: Evidence of AI adoption, digital transformation involvement
2. DECISION AUTHORITY: Budget control signals, team size, project ownership
3. BUYING SIGNALS: Technology evaluations, vendor selection involvement
4. PAIN INDICATORS: Challenges mentioned in posts/interviews

## AI CHAMPION INDICATORS
Look for evidence of:
- Posts/comments about AI, automation, digital transformation
- Attendance at AI/tech conferences
- Leading innovation initiatives
- Evaluating or implementing new technologies
- Hiring for AI/data roles (if they're the hiring manager)

## AUTHORITY SIGNALS
Look for evidence of:
- Team size managed
- Budget responsibility mentioned
- Strategic project ownership
- Reports directly to C-suite
- Decision-making language ("we decided", "I chose", "my team implemented")

## OUTPUT FORMAT
Return ONLY a JSON object. No markdown. No code fences. Start with {.

{
  "ai_champion_evidence": "Specific evidence of AI/innovation interest. Or 'None found'",
  "ai_champion_score": 0-5,
  "authority_signals": "Evidence of decision-making power. Or 'None found'",
  "authority_level": "high|medium|low|unknown",
  "team_size_indication": "If mentioned. Or 'Unknown'",
  "budget_signals": "Evidence of budget control. Or 'None found'",
  "technology_interests": ["tech1", "tech2"],
  "pain_indicators": "Challenges or problems they've discussed. Or 'None found'",
  "buying_signals": "Vendor evaluation, RFP involvement. Or 'None found'",
  "recent_activity_level": "active|moderate|quiet|unknown",
  "data_confidence": "high|medium|low"
}"""

SIGNALS_USER_TEMPLATE = """\
Research decision-making signals for this B2B contact:

Name: {full_name}
Job Title: {job_title}
Company: {company_name}
Company Domain: {domain}
Industry: {industry}
Company Size: {employees} employees

Company Context:
- AI Opportunities: {ai_opportunities}
- Pain Hypothesis: {pain_hypothesis}
- Strategic Signals: {strategic_signals}

Current date: {current_date}

Look for evidence of AI/innovation interest and decision-making authority."""

# ---------------------------------------------------------------------------
# Prompts: Anthropic synthesis
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM_PROMPT = """\
You are a B2B sales intelligence specialist preparing personalization data \
for outreach.

## RULES
1. Every recommendation must connect to EVIDENCE from the research
2. Personalization must feel genuine, not creepy
3. Connect person's interests to their company's pain hypothesis
4. If data is thin, provide fewer but higher-quality recommendations

## PERSONALIZATION ANGLES
- **Thought Leader**: Reference their public content
- **Tech Enthusiast**: Lead with innovation
- **Business Results**: Lead with ROI
- **Rising Star**: Acknowledge career momentum

## OUTPUT FORMAT
Return ONLY valid JSON. Start with {.

{
  "personalization_angle": "Why this person matters and how to approach them",
  "connection_points": ["point1", "point2", "point3"],
  "pain_connection": "How their role connects to company's pain hypothesis",
  "conversation_starters": "2-3 questions that show you've done research",
  "objection_prediction": "Likely objection and how to address it"
}"""

SYNTHESIS_USER_TEMPLATE = """\
Create personalized outreach strategy for this contact:

## Contact
Name: {full_name}
Title: {job_title}
Company: {company_name}

## Scores
Contact Score: {contact_score}/100
ICP Fit: {icp_fit}
AI Champion Score: {ai_champion_score}/10
Authority Score: {authority_score}/10
Seniority: {seniority}
Department: {department}

## Research Findings
Career Trajectory: {career_trajectory}
Thought Leadership: {thought_leadership}
Expertise Areas: {expertise_areas}
AI Champion Evidence: {ai_champion_evidence}
Authority Signals: {authority_signals}
Pain Indicators: {pain_indicators}
Technology Interests: {technology_interests}

## Company Context
Pain Hypothesis: {pain_hypothesis}
AI Opportunities: {ai_opportunities}
Strategic Signals: {strategic_signals}
Tier: {tier}
Industry: {industry}

Create compelling, evidence-based personalization that connects their \
interests to the company's needs."""


# ---------------------------------------------------------------------------
# Core enrichment
# ---------------------------------------------------------------------------


def enrich_person(
    contact_id, tenant_id=None, previous_data=None, boost=False, user_id=None
):
    """Enrich a contact with person-level intelligence.

    Args:
        contact_id: UUID string of the contact
        tenant_id: UUID string (optional, read from contact)
        previous_data: dict of prior enrichment (for re-enrichment)
        boost: if True, use higher-quality Perplexity model
        user_id: optional UUID string for LLM usage attribution

    Returns dict with enrichment_cost_usd (and optionally error).
    """
    total_cost = 0.0

    # 1. Load contact + company data
    contact_data, company_data, l2_data = _load_contact_and_company(contact_id)
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
        pass  # Fall back to English

    pplx_model = get_model_for_stage("person", boost)

    try:
        # 2. Research: Profile
        profile_data, profile_cost = _research_profile(
            contact_data,
            company_data,
            pplx_model,
            user_id=user_id,
            enrichment_language=enrichment_lang,
        )
        total_cost += profile_cost
    except Exception as exc:
        logger.error("Person profile research failed for %s: %s", contact_id, exc)
        return {"error": str(exc), "enrichment_cost_usd": total_cost}

    try:
        # 3. Research: Decision signals
        signals_data, signals_cost = _research_signals(
            contact_data,
            company_data,
            l2_data,
            pplx_model,
            user_id=user_id,
            enrichment_language=enrichment_lang,
        )
        total_cost += signals_cost
    except Exception as exc:
        logger.error("Person signals research failed for %s: %s", contact_id, exc)
        return {"error": str(exc), "enrichment_cost_usd": total_cost}

    # 4. Validate & Score (deterministic)
    scores = _validate_and_score(
        contact_data,
        company_data,
        l2_data,
        profile_data,
        signals_data,
    )

    # 5. Synthesis (Anthropic)
    synthesis_data = {}
    synthesis_cost = 0.0
    try:
        synthesis_data, synthesis_cost = _synthesize(
            contact_data,
            company_data,
            l2_data,
            profile_data,
            signals_data,
            scores,
            user_id=user_id,
            enrichment_language=enrichment_lang,
        )
        total_cost += synthesis_cost
    except Exception as exc:
        logger.warning(
            "Person synthesis failed for %s: %s (saving research anyway)",
            contact_id,
            exc,
        )

    # 6. Build relationship summary
    relationship_summary = _build_relationship_summary(
        contact_data,
        company_data,
        scores,
        synthesis_data,
        profile_data,
    )
    linkedin_summary = _build_linkedin_summary(profile_data)

    # 7. Compute quality score for person block
    from .quality_scoring import assess_block_quality, parse_confidence

    person_data = {
        "person_summary": relationship_summary,
        "role_verified": scores.get("role_verified"),
        "career_trajectory": profile_data.get("career_trajectory"),
        "authority_score": scores.get("authority_score"),
        "seniority": scores.get("seniority"),
        "department": scores.get("department"),
        "contact_score": scores.get("contact_score"),
        "icp_fit": scores.get("icp_fit"),
    }
    block_flags = []
    if scores.get("role_mismatch_flag"):
        block_flags.append("role_mismatch")
    if scores.get("authority_score") is not None and scores["authority_score"] < 30:
        block_flags.append("low_authority")

    quality = assess_block_quality(
        data=person_data,
        block_code="person",
        confidence=parse_confidence(profile_data.get("data_confidence")),
        extra_flags=block_flags,
    )

    # 8. Upsert contact_enrichment (BL-153: pass all research data)
    _upsert_contact_enrichment(
        contact_id,
        relationship_summary,
        linkedin_summary,
        scores,
        profile_data,
        total_cost,
        signals_data=signals_data,
        synthesis_data=synthesis_data,
        quality=quality,
    )

    # 9. Update contact fields (pass signals_data for linkedin_activity_level)
    _update_contact(contact_id, scores, total_cost, signals_data=signals_data)

    db.session.commit()

    return {
        "enrichment_cost_usd": total_cost,
        "quality_score": quality.quality_score,
        "qc_flags": quality.qc_flags,
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_contact_and_company(contact_id):
    """Load contact + company + L2 enrichment data. Returns (contact, company, l2) or (None, None, None)."""
    row = db.session.execute(
        text("""
            SELECT ct.first_name, ct.last_name, ct.job_title, ct.email_address,
                   ct.linkedin_url, ct.location_city, ct.location_country,
                   ct.company_id, ct.tenant_id,
                   c.name AS company_name, c.domain, c.industry, c.tier,
                   c.verified_employees, c.hq_country, c.geo_region
            FROM contacts ct
            JOIN companies c ON ct.company_id = c.id
            WHERE ct.id = :cid
        """),
        {"cid": str(contact_id)},
    ).fetchone()

    if not row:
        return None, None, None

    contact_data = {
        "id": str(contact_id),
        "first_name": row[0] or "",
        "last_name": row[1] or "",
        "full_name": "{} {}".format(row[0] or "", row[1] or "").strip(),
        "job_title": row[2] or "",
        "email": row[3] or "",
        "linkedin_url": row[4] or "Not provided",
        "city": row[5] or "",
        "country": row[6] or "",
        "company_id": str(row[7]),
        "tenant_id": str(row[8]),
    }

    company_data = {
        "name": row[9] or "",
        "domain": row[10] or "",
        "industry": row[11] or "",
        "tier": row[12] or "",
        "employees": int(row[13]) if row[13] else 0,
        "country": row[14] or "",
        "geo_region": row[15] or "",
    }

    # Load L2 data from split tables (BL-183), with fallback to old table (BL-154)
    l2_data = {}
    company_cid = contact_data["company_id"]

    # Try split tables first (canonical source after migration 021/039)
    opp_row = db.session.execute(
        text("""
            SELECT pain_hypothesis, ai_opportunities
            FROM company_enrichment_opportunity
            WHERE company_id = :cid
        """),
        {"cid": company_cid},
    ).fetchone()

    prof_row = db.session.execute(
        text("""
            SELECT company_intel
            FROM company_enrichment_profile
            WHERE company_id = :cid
        """),
        {"cid": company_cid},
    ).fetchone()

    if opp_row or prof_row:
        l2_data = {
            "pain_hypothesis": (opp_row[0] if opp_row else None) or "Unknown",
            "ai_opportunities": (opp_row[1] if opp_row else None) or "Unknown",
            "company_intel": (prof_row[0] if prof_row else None) or "",
        }
    else:
        # Fallback to old company_enrichment_l2 table for pre-migration data
        l2_row = db.session.execute(
            text("""
                SELECT pain_hypothesis, ai_opportunities, company_intel
                FROM company_enrichment_l2
                WHERE company_id = :cid
            """),
            {"cid": company_cid},
        ).fetchone()

        if l2_row:
            l2_data = {
                "pain_hypothesis": l2_row[0] or "Unknown",
                "ai_opportunities": l2_row[1] or "Unknown",
                "company_intel": l2_row[2] or "",
            }

    return contact_data, company_data, l2_data


# ---------------------------------------------------------------------------
# Research calls
# ---------------------------------------------------------------------------


def _research_profile(
    contact_data, company_data, model, user_id=None, enrichment_language=None
):
    """Call Perplexity for professional profile research."""
    import time as _time

    user_prompt = PROFILE_USER_TEMPLATE.format(
        full_name=contact_data["full_name"],
        job_title=contact_data["job_title"],
        company_name=company_data["name"],
        domain=company_data["domain"],
        linkedin_url=contact_data["linkedin_url"],
        city=contact_data["city"],
        country=contact_data["country"],
        current_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )

    effective_system_prompt = PROFILE_SYSTEM_PROMPT
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
        search_recency_filter="month",
    )
    duration_ms = int((_time.time() - start_time) * 1000)

    # Log person profile research usage
    if log_llm_usage:
        try:
            log_llm_usage(
                tenant_id=contact_data.get("tenant_id"),
                operation="person_profile_research",
                model=model,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                provider="perplexity",
                user_id=user_id,
                duration_ms=duration_ms,
                metadata={
                    "contact_id": contact_data.get("id"),
                    "company_id": contact_data.get("company_id"),
                },
            )
        except Exception as e:
            logger.warning("Failed to log person profile research usage: %s", e)

    data = _parse_json(resp.content)
    return data, resp.cost_usd


def _research_signals(
    contact_data, company_data, l2_data, model, user_id=None, enrichment_language=None
):
    """Call Perplexity for decision-making signals."""
    import time as _time

    user_prompt = SIGNALS_USER_TEMPLATE.format(
        full_name=contact_data["full_name"],
        job_title=contact_data["job_title"],
        company_name=company_data["name"],
        domain=company_data["domain"],
        industry=company_data["industry"],
        employees=company_data["employees"],
        ai_opportunities=l2_data.get("ai_opportunities", "Unknown"),
        pain_hypothesis=l2_data.get("pain_hypothesis", "Unknown"),
        strategic_signals=l2_data.get("company_intel", "None"),
        current_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )

    effective_system_prompt = SIGNALS_SYSTEM_PROMPT
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
        max_tokens=600,
        temperature=PERPLEXITY_TEMPERATURE,
    )
    duration_ms = int((_time.time() - start_time) * 1000)

    # Log person signals research usage
    if log_llm_usage:
        try:
            log_llm_usage(
                tenant_id=contact_data.get("tenant_id"),
                operation="person_signals_research",
                model=model,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                provider="perplexity",
                user_id=user_id,
                duration_ms=duration_ms,
                metadata={
                    "contact_id": contact_data.get("id"),
                    "company_id": contact_data.get("company_id"),
                },
            )
        except Exception as e:
            logger.warning("Failed to log person signals research usage: %s", e)

    data = _parse_json(resp.content)
    return data, resp.cost_usd


# ---------------------------------------------------------------------------
# Validate & Score (deterministic)
# ---------------------------------------------------------------------------

_SENIORITY_PATTERNS = [
    (r"\b(ceo|cfo|cto|coo|cmo|cio|chief|founder|president)\b", "C-Level"),
    (r"\b(vp|vice\s*president|svp|evp)\b", "VP"),
    (r"\b(director|head\s+of)\b", "Director"),
    (r"\b(manager|lead|team\s*lead)\b", "Manager"),
]

_DEPARTMENT_PATTERNS = [
    (r"\b(ceo|coo|founder|president|managing\s*director)\b", "Executive"),
    (r"\b(cto|engineering|developer|software|architect)\b", "Engineering"),
    (r"\b(product|pm|ux)\b", "Product"),
    (r"\b(cmo|marketing|brand|growth)\b", "Marketing"),
    (r"\b(sales|account|business\s*development|revenue)\b", "Sales"),
    (r"\b(cfo|finance|financial|accounting)\b", "Finance"),
    (r"\b(operations|ops|logistics|supply\s*chain)\b", "Operations"),
    (r"\b(data|analytics|bi|intelligence)\b", "Operations"),
    (r"\b(ai|ml|machine\s*learning)\b", "Engineering"),
    (r"\b(hr|human\s*resources|people|talent)\b", "HR"),
    (r"\b(customer\s*success|cs|support)\b", "Customer Success"),
]


def _detect_seniority(title):
    t = (title or "").lower()
    for pattern, level in _SENIORITY_PATTERNS:
        if re.search(pattern, t):
            return level
    return "Individual Contributor"


def _detect_department(title):
    t = (title or "").lower()
    for pattern, dept in _DEPARTMENT_PATTERNS:
        if re.search(pattern, t):
            return dept
    return "Other"


def _validate_and_score(
    contact_data, company_data, l2_data, profile_data, signals_data
):
    """Run deterministic scoring on research results."""
    title = contact_data["job_title"]
    seniority = _detect_seniority(title)
    department = _detect_department(title)

    # Role verification flags
    flags = []
    role_verified = profile_data.get("current_role_verified", False)
    role_mismatch = profile_data.get("role_mismatch_flag")
    if not role_verified:
        flags.append("ROLE_NOT_VERIFIED")
    if role_mismatch:
        flags.append("ROLE_MISMATCH")

    # Department alignment with pain hypothesis
    pain_context = (
        l2_data.get("pain_hypothesis", "") + " " + l2_data.get("ai_opportunities", "")
    ).lower()

    dept_keywords = {
        "Operations": ["operations", "process", "workflow", "automation"],
        "Engineering": ["engineering", "technology", "development", "platform"],
        "Finance": ["finance", "cost", "budget", "reporting"],
        "Sales": ["sales", "revenue", "crm", "pipeline"],
        "Marketing": ["marketing", "content", "personalization"],
        "Executive": ["strategy", "transformation", "digital", "growth"],
    }

    keywords = dept_keywords.get(department, [])
    if keywords and any(kw in pain_context for kw in keywords):
        dept_alignment = "strong"
    elif department == "Executive":
        dept_alignment = "moderate"
    else:
        dept_alignment = "weak"

    # AI Champion Score (0-10)
    ai_champion_score = signals_data.get("ai_champion_score", 0)
    if not isinstance(ai_champion_score, (int, float)):
        ai_champion_score = 0
    ai_topics = ["ai", "machine learning", "automation", "digital transformation"]
    thought_topics = profile_data.get("thought_leadership_topics", [])
    if isinstance(thought_topics, list) and any(
        any(ai in t.lower() for ai in ai_topics)
        for t in thought_topics
        if isinstance(t, str)
    ):
        ai_champion_score += 2
    if department in ("Engineering", "Product"):
        ai_champion_score += 1
    ai_champion_score = min(10, int(ai_champion_score))

    # Authority Score (0-10)
    seniority_scores = {
        "C-Level": 10,
        "VP": 8,
        "Director": 6,
        "Manager": 4,
        "Individual Contributor": 2,
    }
    authority_score = seniority_scores.get(seniority, 2)
    authority_bonus = {"high": 3, "medium": 2, "low": 1}
    authority_level = signals_data.get("authority_level", "unknown")
    authority_score += authority_bonus.get(authority_level, 0)
    authority_score = min(10, authority_score)

    # Contact Score (0-100)
    contact_score = 0
    if role_verified:
        contact_score += 15
    if not role_mismatch:
        contact_score += 5
    seniority_points = {
        "C-Level": 25,
        "VP": 22,
        "Director": 18,
        "Manager": 12,
        "Individual Contributor": 5,
    }
    contact_score += seniority_points.get(seniority, 5)
    alignment_points = {"strong": 15, "moderate": 10, "weak": 5}
    contact_score += alignment_points.get(dept_alignment, 5)
    contact_score += round(ai_champion_score * 1.5)
    contact_score += round(authority_score * 1.5)
    contact_score = min(100, contact_score)

    # ICP Fit
    if contact_score >= 70 and dept_alignment != "weak" and role_verified:
        icp_fit = "Strong Fit"
    elif contact_score >= 50 and dept_alignment != "weak":
        icp_fit = "Moderate Fit"
    elif contact_score >= 30:
        icp_fit = "Weak Fit"
    else:
        icp_fit = "Unknown"

    return {
        "seniority": seniority,
        "department": department,
        "dept_alignment": dept_alignment,
        "ai_champion_score": ai_champion_score,
        "is_ai_champion": ai_champion_score >= 5,
        "authority_score": authority_score,
        "contact_score": contact_score,
        "icp_fit": icp_fit,
        "role_verified": role_verified,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


def _synthesize(
    contact_data,
    company_data,
    l2_data,
    profile_data,
    signals_data,
    scores,
    user_id=None,
    enrichment_language=None,
):
    """Call Anthropic for personalization synthesis."""
    import time as _time

    expertise = profile_data.get("expertise_areas", [])
    if isinstance(expertise, list):
        expertise = ", ".join(expertise)
    tech_interests = signals_data.get("technology_interests", [])
    if isinstance(tech_interests, list):
        tech_interests = ", ".join(tech_interests)

    user_prompt = SYNTHESIS_USER_TEMPLATE.format(
        full_name=contact_data["full_name"],
        job_title=contact_data["job_title"],
        company_name=company_data["name"],
        contact_score=scores["contact_score"],
        icp_fit=scores["icp_fit"],
        ai_champion_score=scores["ai_champion_score"],
        authority_score=scores["authority_score"],
        seniority=scores["seniority"],
        department=scores["department"],
        career_trajectory=profile_data.get("career_trajectory", "Unknown"),
        thought_leadership=profile_data.get("thought_leadership", "None found"),
        expertise_areas=expertise,
        ai_champion_evidence=signals_data.get("ai_champion_evidence", "None found"),
        authority_signals=signals_data.get("authority_signals", "None found"),
        pain_indicators=signals_data.get("pain_indicators", "None found"),
        technology_interests=tech_interests,
        pain_hypothesis=l2_data.get("pain_hypothesis", "Unknown"),
        ai_opportunities=l2_data.get("ai_opportunities", "Unknown"),
        strategic_signals=l2_data.get("company_intel", "None"),
        tier=company_data.get("tier", ""),
        industry=company_data.get("industry", ""),
    )

    effective_system_prompt = SYNTHESIS_SYSTEM_PROMPT
    if enrichment_language and enrichment_language != "en":
        from ..display import LANGUAGE_NAMES

        lang_name = LANGUAGE_NAMES.get(enrichment_language, enrichment_language)
        effective_system_prompt += (
            f"\n\nIMPORTANT: Write all analysis and output in {lang_name}. "
            f"Field names and JSON keys must remain in English, "
            f"but descriptive text should be in {lang_name}."
        )

    client = AnthropicClient()
    start_time = _time.time()
    resp = client.query(
        system_prompt=effective_system_prompt,
        user_prompt=user_prompt,
        model=ANTHROPIC_MODEL,
        max_tokens=ANTHROPIC_MAX_TOKENS,
        temperature=ANTHROPIC_TEMPERATURE,
    )
    duration_ms = int((_time.time() - start_time) * 1000)

    # Log person synthesis usage
    if log_llm_usage:
        try:
            log_llm_usage(
                tenant_id=contact_data.get("tenant_id"),
                operation="person_synthesis",
                model=ANTHROPIC_MODEL,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                provider="anthropic",
                user_id=user_id,
                duration_ms=duration_ms,
                metadata={
                    "contact_id": contact_data.get("id"),
                    "company_id": contact_data.get("company_id"),
                },
            )
        except Exception as e:
            logger.warning("Failed to log person synthesis usage: %s", e)

    data = _parse_json(resp.content)
    return data, resp.cost_usd


# ---------------------------------------------------------------------------
# Summary builders
# ---------------------------------------------------------------------------


def _build_relationship_summary(contact_data, company_data, scores, synthesis, profile):
    """Build markdown relationship summary."""
    lines = [
        "## {} @ {}".format(contact_data["full_name"], company_data["name"]),
        "",
        "**Role:** {} ({} | {})".format(
            contact_data["job_title"],
            scores["seniority"],
            scores["department"],
        ),
        "**Score:** {}/100 | ICP Fit: {}".format(
            scores["contact_score"], scores["icp_fit"]
        ),
        "**AI Champion:** {} ({}/10)".format(
            "Yes" if scores["is_ai_champion"] else "No",
            scores["ai_champion_score"],
        ),
        "",
    ]

    if synthesis:
        lines.extend(
            [
                "### Personalization Angle",
                synthesis.get("personalization_angle", "No angle generated"),
                "",
                "### Connection Points",
            ]
        )
        for p in synthesis.get("connection_points", []):
            lines.append("- {}".format(p))
        lines.extend(
            [
                "",
                "### Pain Connection",
                synthesis.get("pain_connection", "Not identified"),
                "",
                "### Conversation Starters",
                synthesis.get("conversation_starters", "None generated"),
            ]
        )

    return "\n".join(lines)


def _build_linkedin_summary(profile_data):
    """Build LinkedIn profile summary text."""
    lines = [
        "**Career:** {}".format(profile_data.get("career_highlights", "Unknown")),
        "**Trajectory:** {}".format(profile_data.get("career_trajectory", "Unknown")),
        "**Expertise:** {}".format(
            ", ".join(profile_data.get("expertise_areas", [])) or "Unknown",
        ),
        "**Education:** {}".format(profile_data.get("education", "Unknown")),
        "**Thought Leadership:** {}".format(
            profile_data.get("thought_leadership", "None found"),
        ),
        "**Public Presence:** {}".format(
            profile_data.get("public_presence_level", "Unknown"),
        ),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------


def _upsert_contact_enrichment(
    contact_id,
    person_summary,
    linkedin_summary,
    scores,
    profile_data,
    cost,
    signals_data=None,
    synthesis_data=None,
    quality=None,
):
    """Upsert into contact_enrichment table.

    Stores all granular fields from profile research, signals research,
    synthesis, and scoring (BL-153 fix: previously only 9 fields stored).
    """
    signals_data = signals_data or {}
    synthesis_data = synthesis_data or {}
    now_str = datetime.now(timezone.utc).isoformat()

    # Serialize list/dict fields to JSON strings for storage
    thought_topics = profile_data.get("thought_leadership_topics", [])
    if isinstance(thought_topics, list):
        thought_topics = json.dumps(thought_topics)
    expertise = profile_data.get("expertise_areas", [])
    if isinstance(expertise, list):
        expertise = json.dumps(expertise)
    tech_interests = signals_data.get("technology_interests", [])
    if isinstance(tech_interests, list):
        tech_interests = json.dumps(tech_interests)
    conn_points = synthesis_data.get("connection_points", [])
    if isinstance(conn_points, list):
        conn_points = json.dumps(conn_points)
    scoring_flags = scores.get("flags", [])
    if isinstance(scoring_flags, list):
        scoring_flags = json.dumps(scoring_flags)

    _COLUMNS = (
        "person_summary",
        "linkedin_profile_summary",
        "relationship_synthesis",
        "ai_champion",
        "ai_champion_score",
        "authority_score",
        "career_trajectory",
        # Profile research fields
        "role_verified",
        "role_mismatch_flag",
        "career_highlights",
        "thought_leadership",
        "thought_leadership_topics",
        "education",
        "certifications",
        "expertise_areas",
        "public_presence_level",
        "profile_data_confidence",
        # Signals research fields
        "ai_champion_evidence",
        "authority_signals",
        "authority_level",
        "team_size_indication",
        "budget_signals",
        "technology_interests",
        "pain_indicators",
        "buying_signals",
        "signals_data_confidence",
        # Synthesis fields
        "personalization_angle",
        "connection_points",
        "pain_connection",
        "conversation_starters",
        "objection_prediction",
        # Scoring fields
        "seniority",
        "department",
        "dept_alignment",
        "contact_score",
        "icp_fit",
        "scoring_flags",
        "quality_score",
        "confidence",
        "qc_flags",
        "block_quality",
    )

    params = {
        "cid": str(contact_id),
        "person_summary": person_summary,
        "linkedin_profile_summary": linkedin_summary,
        "relationship_synthesis": person_summary,
        "ai_champion": scores["is_ai_champion"],
        "ai_champion_score": scores["ai_champion_score"],
        "authority_score": scores["authority_score"],
        "career_trajectory": profile_data.get("career_trajectory", "unknown"),
        # Profile research
        "role_verified": profile_data.get("current_role_verified", False),
        "role_mismatch_flag": profile_data.get("role_mismatch_flag"),
        "career_highlights": profile_data.get("career_highlights"),
        "thought_leadership": profile_data.get("thought_leadership"),
        "thought_leadership_topics": thought_topics,
        "education": profile_data.get("education"),
        "certifications": profile_data.get("certifications"),
        "expertise_areas": expertise,
        "public_presence_level": profile_data.get("public_presence_level"),
        "profile_data_confidence": profile_data.get("data_confidence"),
        # Signals research
        "ai_champion_evidence": signals_data.get("ai_champion_evidence"),
        "authority_signals": signals_data.get("authority_signals"),
        "authority_level": signals_data.get("authority_level"),
        "team_size_indication": signals_data.get("team_size_indication"),
        "budget_signals": signals_data.get("budget_signals"),
        "technology_interests": tech_interests,
        "pain_indicators": signals_data.get("pain_indicators"),
        "buying_signals": signals_data.get("buying_signals"),
        "signals_data_confidence": signals_data.get("data_confidence"),
        # Synthesis
        "personalization_angle": synthesis_data.get("personalization_angle"),
        "connection_points": conn_points,
        "pain_connection": synthesis_data.get("pain_connection"),
        "conversation_starters": synthesis_data.get("conversation_starters"),
        "objection_prediction": synthesis_data.get("objection_prediction"),
        # Scoring
        "seniority": scores.get("seniority"),
        "department": scores.get("department"),
        "dept_alignment": scores.get("dept_alignment"),
        "contact_score": scores.get("contact_score"),
        "icp_fit": scores.get("icp_fit"),
        "scoring_flags": scoring_flags,
        # Quality scoring
        "quality_score": quality.quality_score if quality else None,
        "confidence": float(quality.confidence)
        if quality and quality.confidence is not None
        else None,
        "qc_flags": json.dumps(quality.qc_flags) if quality else "[]",
        "block_quality": json.dumps(
            {
                "person": {
                    "score": quality.quality_score,
                    "confidence": quality.confidence,
                    "flags": quality.qc_flags,
                    "field_coverage": quality.field_coverage,
                },
            }
        )
        if quality
        else "{}",
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


_SENIORITY_TO_DB = {
    "C-Level": "c_level",
    "VP": "vp",
    "Director": "director",
    "Manager": "manager",
    "Individual Contributor": "individual_contributor",
    "Founder": "founder",
    "Other": "other",
}

_DEPARTMENT_TO_DB = {
    "Executive": "executive",
    "Engineering": "engineering",
    "Product": "product",
    "Sales": "sales",
    "Marketing": "marketing",
    "Customer Success": "customer_success",
    "Finance": "finance",
    "HR": "hr",
    "Operations": "operations",
    "Other": "other",
}

_ICP_FIT_TO_DB = {
    "Strong Fit": "strong_fit",
    "Moderate Fit": "moderate_fit",
    "Weak Fit": "weak_fit",
    "Unknown": "unknown",
}


def _update_contact(contact_id, scores, total_cost, signals_data=None):
    """Update contact fields with enrichment results.

    Fix #11: Maps recent_activity_level from person signals to
    linkedin_activity_level on the contacts table.
    """
    # Map recent_activity_level to linkedin_activity_level
    linkedin_activity = "unknown"
    if signals_data:
        activity = signals_data.get("recent_activity_level", "unknown")
        if activity in ("active", "moderate", "quiet", "unknown"):
            linkedin_activity = activity

    # Normalize display values to DB enum values (explicit mapping preferred;
    # fallback normalizes string to snake_case for forward-compat with new values)
    def _enum_fallback(val: str, default: str) -> str:
        return val.lower().replace(" ", "_").replace("-", "_") if val else default

    seniority_db = _SENIORITY_TO_DB.get(
        scores["seniority"], _enum_fallback(scores["seniority"], "other")
    )
    department_db = _DEPARTMENT_TO_DB.get(
        scores["department"], _enum_fallback(scores["department"], "other")
    )
    icp_fit_db = _ICP_FIT_TO_DB.get(
        scores["icp_fit"], _enum_fallback(scores["icp_fit"], "unknown")
    )

    db.session.execute(
        text("""
            UPDATE contacts SET
                seniority_level = :seniority,
                department = :department,
                ai_champion = :ai_champion,
                ai_champion_score = :ai_champ_score,
                authority_score = :auth_score,
                contact_score = :contact_score,
                icp_fit = :icp_fit,
                linkedin_activity_level = :linkedin_activity,
                enrichment_cost_usd = :cost,
                processed_enrich = :processed
            WHERE id = :cid
        """),
        {
            "cid": str(contact_id),
            "seniority": seniority_db,
            "department": department_db,
            "ai_champion": scores["is_ai_champion"],
            "ai_champ_score": scores["ai_champion_score"],
            "auth_score": scores["authority_score"],
            "contact_score": scores["contact_score"],
            "icp_fit": icp_fit_db,
            "linkedin_activity": linkedin_activity,
            "cost": total_cost,
            "processed": True,
        },
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _parse_json(raw_text):
    """Parse JSON from LLM response, handling markdown fences."""
    if not raw_text:
        return {}
    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw_text)
    cleaned = cleaned.strip().rstrip("`")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    logger.warning("Failed to parse JSON from LLM response: %s...", raw_text[:200])
    return {}
