"""News & PR Enrichment via Perplexity sonar API.

Researches recent news, press releases, media coverage, and sentiment
for a company. Writes results to the company_news table.
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
You are a media intelligence analyst. Given a company name and context,
research its recent news coverage, press releases, and media presence.
Return ONLY a JSON object with the fields listed below, no commentary.

Required JSON fields:
- media_mentions (list of objects): Recent news articles mentioning the company.
  Each object: {"headline": string, "source": string, "date": string (YYYY-MM-DD or null),
                "summary": string (1-2 sentences), "sentiment": "positive"|"neutral"|"negative",
                "url": string or null}
  Return up to 10 most recent/relevant items. Empty list if none found.
- press_releases (list of objects): Company-issued press releases or announcements.
  Each object: {"headline": string, "date": string (YYYY-MM-DD or null),
                "summary": string (1-2 sentences), "url": string or null}
  Return up to 5 most recent items. Empty list if none found.
- sentiment_score (number or null): Overall media sentiment from -1.0 (very negative)
  to 1.0 (very positive). null if insufficient data.
- thought_leadership (string or null): Evidence of company thought leadership —
  blog posts, white papers, conference talks, industry reports.
- news_summary (string or null): 2-3 sentence summary of the company's recent
  media presence and key themes.

If no news is found, return empty lists and null for text fields.
"""


def enrich_news(
    entity_id, tenant_id=None, previous_data=None, boost=False, user_id=None
):
    """Run news & PR enrichment for a single company.

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
                   c.industry, c.hq_country
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
    hq_country = row[5]

    # 2. Build prompt
    context_lines = [f"Company: {company_name}"]
    if domain:
        context_lines.append(f"Domain: {domain}")
    if industry:
        context_lines.append(f"Industry: {industry}")
    if hq_country:
        context_lines.append(f"HQ Country: {hq_country}")

    # Add Czech/Slovak language search hints for companies in those countries
    czech_countries = {"Czech Republic", "Czechia", "CZ", "Slovakia", "SK"}
    if hq_country and any(c.lower() in hq_country.lower() for c in czech_countries):
        context_lines.append(
            "\nIMPORTANT: This company is based in a Czech/Slovak-speaking country. "
            "Search in BOTH English AND Czech/Slovak. Try these search terms:\n"
            f'- "{company_name}" novinky OR zprávy OR tisková zpráva\n'
            f'- "{company_name}" site:czechcrunch.cz OR site:lupa.cz OR site:e15.cz\n'
            f'- "{company_name}" firma OR společnost OR dotace OR investice\n'
            "Also search standard English news sources."
        )

    user_prompt = "\n".join(context_lines)

    # 3. Call Perplexity
    api_key = current_app.config.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        raise ValueError("PERPLEXITY_API_KEY not configured")

    model = get_model_for_stage("news", boost=boost)
    client = PerplexityClient(api_key=api_key)

    try:
        pplx_response = client.query(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=model,
            max_tokens=PERPLEXITY_MAX_TOKENS,
            temperature=PERPLEXITY_TEMPERATURE,
            search_recency_filter="month",
        )
        raw_response = pplx_response.content
        usage = {
            "input_tokens": pplx_response.input_tokens,
            "output_tokens": pplx_response.output_tokens,
        }
        cost_usd = pplx_response.cost_usd
    except Exception as e:
        logger.error("Perplexity API error for news enrichment %s: %s", company_id, e)
        return {"enrichment_cost_usd": 0, "error": f"api_error: {e}"}

    # 4. Parse response
    parsed = _parse_json(raw_response)
    if parsed is None:
        logger.warning("Failed to parse news response for company %s", company_id)
        return {"enrichment_cost_usd": 0, "error": "parse_error"}

    # 5. Compute quality score
    from .quality_scoring import assess_block_quality, parse_confidence

    block_flags = []
    media = parsed.get("media_mentions")
    if not media or (isinstance(media, list) and len(media) == 0):
        block_flags.append("no_media_coverage")
    if parsed.get("sentiment_score") is None and media and len(media) > 0:
        block_flags.append("sentiment_missing")

    quality = assess_block_quality(
        data=parsed,
        block_code="news",
        confidence=parse_confidence(parsed.get("confidence")),
        extra_flags=block_flags,
    )

    # 6. Upsert to company_news
    _upsert_news(company_id, parsed, cost_usd, quality)

    # 7. Log LLM usage
    duration_ms = int((time.time() - start_time) * 1000)
    if log_llm_usage:
        log_llm_usage(
            tenant_id=tenant_id,
            operation="news_enrichment",
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


def _safe_float(val):
    """Convert value to float, returning None on failure."""
    if val is None:
        return None
    try:
        f = float(val)
        return max(-1.0, min(1.0, f))  # clamp to [-1, 1]
    except (ValueError, TypeError):
        return None


def _safe_json_list(val):
    """Ensure value is a JSON-serializable list."""
    if val is None:
        return "[]"
    if isinstance(val, list):
        return json.dumps(val)
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return val
        except (json.JSONDecodeError, ValueError):
            pass
        return "[]"
    return "[]"


def _upsert_news(company_id, parsed, cost_usd, quality=None):
    """Upsert enrichment results into company_news."""
    import json as _json

    params = {
        "company_id": str(company_id),
        "media_mentions": _safe_json_list(parsed.get("media_mentions")),
        "press_releases": _safe_json_list(parsed.get("press_releases")),
        "sentiment_score": _safe_float(parsed.get("sentiment_score")),
        "thought_leadership": parsed.get("thought_leadership"),
        "news_summary": parsed.get("news_summary"),
        "cost": cost_usd,
        "quality_score": quality.quality_score if quality else None,
        "confidence": float(quality.confidence)
        if quality and quality.confidence is not None
        else None,
        "qc_flags": _json.dumps(quality.qc_flags) if quality else "[]",
    }

    dialect = db.engine.dialect.name
    if dialect == "sqlite":
        db.session.execute(
            text("""
                INSERT OR REPLACE INTO company_news (
                    company_id, media_mentions, press_releases,
                    sentiment_score, thought_leadership, news_summary,
                    quality_score, confidence, qc_flags,
                    enriched_at, enrichment_cost_usd,
                    created_at, updated_at
                ) VALUES (
                    :company_id, :media_mentions, :press_releases,
                    :sentiment_score, :thought_leadership, :news_summary,
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
                INSERT INTO company_news (
                    company_id, media_mentions, press_releases,
                    sentiment_score, thought_leadership, news_summary,
                    quality_score, confidence, qc_flags,
                    enriched_at, enrichment_cost_usd
                ) VALUES (
                    :company_id, CAST(:media_mentions AS jsonb),
                    CAST(:press_releases AS jsonb),
                    :sentiment_score, :thought_leadership, :news_summary,
                    :quality_score, :confidence, CAST(:qc_flags AS jsonb),
                    CURRENT_TIMESTAMP, :cost
                )
                ON CONFLICT (company_id) DO UPDATE SET
                    media_mentions = EXCLUDED.media_mentions,
                    press_releases = EXCLUDED.press_releases,
                    sentiment_score = EXCLUDED.sentiment_score,
                    thought_leadership = EXCLUDED.thought_leadership,
                    news_summary = EXCLUDED.news_summary,
                    quality_score = EXCLUDED.quality_score,
                    confidence = EXCLUDED.confidence,
                    qc_flags = EXCLUDED.qc_flags,
                    enriched_at = EXCLUDED.enriched_at,
                    enrichment_cost_usd = EXCLUDED.enrichment_cost_usd,
                    updated_at = now()
            """),
            params,
        )
