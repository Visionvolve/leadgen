"""Strategic Signals Enrichment via Perplexity sonar API.

Researches buying signals, hiring patterns, AI adoption, and growth
indicators for a company. Writes results to the
company_enrichment_signals table.
"""

import json
import logging
import time

from flask import current_app
from sqlalchemy import text

from ..models import db
from .perplexity_client import PerplexityClient
from .stage_registry import get_model_for_stage

try:
    from .llm_logger import log_llm_usage
except ImportError:
    log_llm_usage = None

logger = logging.getLogger(__name__)

PERPLEXITY_MAX_TOKENS = 800
PERPLEXITY_TEMPERATURE = 0.1

SYSTEM_PROMPT = """\
You are a B2B strategic intelligence analyst. Given a company name and context,
research its current strategic signals — buying indicators, hiring patterns,
technology adoption, and growth trajectory. Return ONLY a JSON object with the
fields listed below, no commentary.

Required JSON fields:
- digital_initiatives (string): Current digital transformation projects or IT modernization efforts.
- leadership_changes (string): Recent C-suite or VP-level hires, departures, or restructuring.
- hiring_signals (string): Overall hiring trends — growing, stable, or shrinking. Notable open roles.
- ai_hiring (string): AI/ML-specific hiring — data scientists, ML engineers, AI product roles.
- tech_partnerships (string): Recently announced tech partnerships or vendor selections.
- competitor_ai_moves (string): How key competitors are adopting AI (creates urgency).
- ai_adoption_level (string): One of: "none", "exploring", "piloting", "scaling", "embedded".
- news_confidence (string): One of: "high", "medium", "low" — confidence in the above data.
- growth_indicators (string): Revenue growth, funding rounds, new markets, acquisitions.
- job_posting_count (integer or null): Approximate number of open positions.
- hiring_departments (list of strings): Departments with most open roles (e.g. ["Engineering", "Sales"]).
- workflow_ai_evidence (string): Evidence of AI in internal workflows (chatbots, automation, copilots).
- regulatory_pressure (string): Regulatory or compliance pressures driving technology adoption.
- employee_sentiment (string): Glassdoor/LinkedIn sentiment — morale, culture signals.
- tech_stack_categories (string): Broad tech categories in use (e.g. "cloud-native, AWS, Salesforce").
- digital_maturity_score (string): One of: "1-nascent", "2-developing", "3-established", "4-advanced", "5-leading".
- it_spend_indicators (string): Evidence of IT budget size or direction (growing/flat/shrinking).

If information is unavailable for a field, set it to null (not empty string).
"""


def enrich_signals(
    entity_id, tenant_id=None, previous_data=None, boost=False, user_id=None
):
    """Run strategic signals enrichment for a single company.

    Args:
        entity_id: UUID string of the company
        tenant_id: UUID string of the tenant (optional)
        previous_data: Dict of existing enrichment data for re-enrichment
        boost: Use higher-quality model if True
        user_id: UUID string of the requesting user (optional)

    Returns:
        dict with enrichment_cost_usd key
    """
    start_time = time.time()

    # 1. Load company context
    row = db.session.execute(
        text("""
            SELECT c.id, c.tenant_id, c.name, c.domain,
                   c.industry, c.company_size, c.hq_country
            FROM companies c
            WHERE c.id = :id
        """),
        {"id": str(entity_id)},
    ).fetchone()

    if not row:
        return {"enrichment_cost_usd": 0, "error": "company_not_found"}

    company_id = str(row[0])
    tenant_id = tenant_id or str(row[1])
    company_name = row[2]
    domain = row[3]
    industry = row[4]
    company_size = row[5]
    hq_country = row[6]

    # 2. Build prompt
    context_lines = [f"Company: {company_name}"]
    if domain:
        context_lines.append(f"Domain: {domain}")
    if industry:
        context_lines.append(f"Industry: {industry}")
    if company_size:
        context_lines.append(f"Size: {company_size}")
    if hq_country:
        context_lines.append(f"HQ Country: {hq_country}")

    if previous_data:
        prev_lines = []
        for k, v in previous_data.items():
            if v is not None and v != "":
                prev_lines.append(f"- {k}: {v}")
        if prev_lines:
            context_lines.append(
                "\nPrevious data (validate and extend):\n" + "\n".join(prev_lines)
            )

    user_prompt = "\n".join(context_lines)

    # 3. Call Perplexity
    api_key = current_app.config.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        raise ValueError("PERPLEXITY_API_KEY not configured")

    model = get_model_for_stage("signals", boost=boost)
    client = PerplexityClient(api_key=api_key)

    try:
        pplx_response = client.query(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=model,
            max_tokens=PERPLEXITY_MAX_TOKENS,
            temperature=PERPLEXITY_TEMPERATURE,
        )
        raw_response = pplx_response.content
        usage = {
            "input_tokens": pplx_response.input_tokens,
            "output_tokens": pplx_response.output_tokens,
        }
        cost_usd = pplx_response.cost_usd
    except Exception as e:
        logger.error(
            "Perplexity API error for signals enrichment %s: %s", company_id, e
        )
        return {"enrichment_cost_usd": 0, "error": f"api_error: {e}"}

    # 4. Parse response
    parsed = _parse_json(raw_response)
    if parsed is None:
        logger.warning("Failed to parse signals response for company %s", company_id)
        return {"enrichment_cost_usd": 0, "error": "parse_error"}

    # 5. Compute quality score
    from .quality_scoring import assess_block_quality, parse_confidence

    block_flags = []
    if not parsed.get("hiring_signals") and not parsed.get("job_posting_count"):
        block_flags.append("no_hiring_data")
    if not parsed.get("ai_hiring") and not parsed.get("ai_adoption_level"):
        block_flags.append("no_ai_signals")

    quality = assess_block_quality(
        data=parsed,
        block_code="signals",
        confidence=parse_confidence(parsed.get("confidence")),
        extra_flags=block_flags,
    )

    # 6. Upsert to company_enrichment_signals
    _upsert_signals(company_id, parsed, cost_usd, quality)

    # 7. Log LLM usage
    duration_ms = int((time.time() - start_time) * 1000)
    if log_llm_usage:
        log_llm_usage(
            tenant_id=tenant_id,
            operation="signals_enrichment",
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            provider="perplexity",
            duration_ms=duration_ms,
            metadata={
                "company_id": company_id,
                "company_name": company_name,
                "boost": boost,
            },
        )

    db.session.commit()

    return {
        "enrichment_cost_usd": cost_usd,
        "quality_score": quality.quality_score,
        "qc_flags": quality.qc_flags,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json(content):
    """Parse JSON from Perplexity response, stripping markdown fences."""
    import re

    if not content:
        return None

    text_content = content.strip()

    if text_content.startswith("```"):
        lines = text_content.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text_content = "\n".join(lines).strip()

    try:
        return json.loads(text_content)
    except (json.JSONDecodeError, ValueError):
        match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text_content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except (json.JSONDecodeError, ValueError):
                pass
        return None


def _safe_int(val):
    """Convert value to int, returning None on failure."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_json(val):
    """Convert value to JSON string for JSONB columns."""
    if val is None:
        return "[]"
    if isinstance(val, list):
        return json.dumps(val)
    if isinstance(val, str):
        return val
    return json.dumps(val)


def _upsert_signals(company_id, parsed, cost_usd, quality=None):
    """Upsert enrichment results into company_enrichment_signals."""
    params = {
        "company_id": str(company_id),
        "digital_initiatives": parsed.get("digital_initiatives"),
        "leadership_changes": parsed.get("leadership_changes"),
        "hiring_signals": parsed.get("hiring_signals"),
        "ai_hiring": parsed.get("ai_hiring"),
        "tech_partnerships": parsed.get("tech_partnerships"),
        "competitor_ai_moves": parsed.get("competitor_ai_moves"),
        "ai_adoption_level": parsed.get("ai_adoption_level"),
        "news_confidence": parsed.get("news_confidence"),
        "growth_indicators": parsed.get("growth_indicators"),
        "job_posting_count": _safe_int(parsed.get("job_posting_count")),
        "hiring_departments": _safe_json(parsed.get("hiring_departments")),
        "workflow_ai_evidence": parsed.get("workflow_ai_evidence"),
        "regulatory_pressure": parsed.get("regulatory_pressure"),
        "employee_sentiment": parsed.get("employee_sentiment"),
        "tech_stack_categories": parsed.get("tech_stack_categories"),
        "digital_maturity_score": parsed.get("digital_maturity_score"),
        "it_spend_indicators": parsed.get("it_spend_indicators"),
        "cost": cost_usd,
        "quality_score": quality.quality_score if quality else None,
        "confidence": float(quality.confidence)
        if quality and quality.confidence is not None
        else None,
        "qc_flags": json.dumps(quality.qc_flags) if quality else "[]",
    }

    dialect = db.engine.dialect.name
    if dialect == "sqlite":
        db.session.execute(
            text("""
                INSERT OR REPLACE INTO company_enrichment_signals (
                    company_id, digital_initiatives, leadership_changes,
                    hiring_signals, ai_hiring, tech_partnerships,
                    competitor_ai_moves, ai_adoption_level, news_confidence,
                    growth_indicators, job_posting_count, hiring_departments,
                    workflow_ai_evidence, regulatory_pressure, employee_sentiment,
                    tech_stack_categories, digital_maturity_score, it_spend_indicators,
                    quality_score, confidence, qc_flags,
                    enriched_at, enrichment_cost_usd,
                    created_at, updated_at
                ) VALUES (
                    :company_id, :digital_initiatives, :leadership_changes,
                    :hiring_signals, :ai_hiring, :tech_partnerships,
                    :competitor_ai_moves, :ai_adoption_level, :news_confidence,
                    :growth_indicators, :job_posting_count, :hiring_departments,
                    :workflow_ai_evidence, :regulatory_pressure, :employee_sentiment,
                    :tech_stack_categories, :digital_maturity_score, :it_spend_indicators,
                    :quality_score, :confidence, :qc_flags,
                    CURRENT_TIMESTAMP, :cost,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """),
            params,
        )
    else:
        db.session.execute(
            text("""
                INSERT INTO company_enrichment_signals (
                    company_id, digital_initiatives, leadership_changes,
                    hiring_signals, ai_hiring, tech_partnerships,
                    competitor_ai_moves, ai_adoption_level, news_confidence,
                    growth_indicators, job_posting_count, hiring_departments,
                    workflow_ai_evidence, regulatory_pressure, employee_sentiment,
                    tech_stack_categories, digital_maturity_score, it_spend_indicators,
                    quality_score, confidence, qc_flags,
                    enriched_at, enrichment_cost_usd
                ) VALUES (
                    :company_id, :digital_initiatives, :leadership_changes,
                    :hiring_signals, :ai_hiring, :tech_partnerships,
                    :competitor_ai_moves, :ai_adoption_level, :news_confidence,
                    :growth_indicators, :job_posting_count, CAST(:hiring_departments AS jsonb),
                    :workflow_ai_evidence, :regulatory_pressure, :employee_sentiment,
                    :tech_stack_categories, :digital_maturity_score, :it_spend_indicators,
                    :quality_score, :confidence, CAST(:qc_flags AS jsonb),
                    CURRENT_TIMESTAMP, :cost
                )
                ON CONFLICT (company_id) DO UPDATE SET
                    digital_initiatives = EXCLUDED.digital_initiatives,
                    leadership_changes = EXCLUDED.leadership_changes,
                    hiring_signals = EXCLUDED.hiring_signals,
                    ai_hiring = EXCLUDED.ai_hiring,
                    tech_partnerships = EXCLUDED.tech_partnerships,
                    competitor_ai_moves = EXCLUDED.competitor_ai_moves,
                    ai_adoption_level = EXCLUDED.ai_adoption_level,
                    news_confidence = EXCLUDED.news_confidence,
                    growth_indicators = EXCLUDED.growth_indicators,
                    job_posting_count = EXCLUDED.job_posting_count,
                    hiring_departments = EXCLUDED.hiring_departments,
                    workflow_ai_evidence = EXCLUDED.workflow_ai_evidence,
                    regulatory_pressure = EXCLUDED.regulatory_pressure,
                    employee_sentiment = EXCLUDED.employee_sentiment,
                    tech_stack_categories = EXCLUDED.tech_stack_categories,
                    digital_maturity_score = EXCLUDED.digital_maturity_score,
                    it_spend_indicators = EXCLUDED.it_spend_indicators,
                    quality_score = EXCLUDED.quality_score,
                    confidence = EXCLUDED.confidence,
                    qc_flags = EXCLUDED.qc_flags,
                    enriched_at = EXCLUDED.enriched_at,
                    enrichment_cost_usd = EXCLUDED.enrichment_cost_usd,
                    updated_at = now()
            """),
            params,
        )
