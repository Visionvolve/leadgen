"""L1 Company Profile Enrichment via Perplexity sonar API.

Replaces the n8n L1 webhook with native Python for better control,
testability, and cost visibility. After enrichment, companies get
status='triage_passed' (clean) or 'needs_review' (QC flags).
"""

import json
import logging
import re
import time

import requests as http_requests
from bs4 import BeautifulSoup
from flask import current_app
from sqlalchemy import text

from ..models import db
from .enum_mapper import map_enum_value
from .perplexity_client import PerplexityClient
from .stage_registry import get_model_for_stage

try:
    from langsmith import traceable
except ImportError:  # pragma: no cover

    def traceable(**kwargs):
        def decorator(fn):
            return fn

        return decorator


# Import llm_logger functions — uses existing pricing if perplexity entries
# are present, otherwise falls back to wildcard pricing
try:
    from .llm_logger import compute_cost, log_llm_usage
except ImportError:
    compute_cost = None
    log_llm_usage = None

logger = logging.getLogger(__name__)

PERPLEXITY_MODEL = "sonar"
PERPLEXITY_MAX_TOKENS = 600
PERPLEXITY_TEMPERATURE = 0.1

# Free-mail domains to skip during domain resolution
FREE_MAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "aol.com",
    "icloud.com",
    "mail.com",
    "protonmail.com",
    "proton.me",
    "zoho.com",
    "yandex.com",
    "gmx.com",
    "gmx.de",
    "web.de",
    "fastmail.com",
    "tutanota.com",
}

WEBSITE_SCRAPE_TIMEOUT = 10  # seconds
WEBSITE_MAX_CHARS = 4000  # truncate scraped text to this length
WEBSITE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def scrape_website(domain):
    """Fetch and extract text content from a company's homepage.

    Args:
        domain: Company domain (e.g. "unitedarts.cz")

    Returns:
        str with extracted text content, or None if scraping failed.
    """
    if not domain:
        return None

    url = f"https://{domain}/"
    try:
        resp = http_requests.get(
            url,
            timeout=WEBSITE_SCRAPE_TIMEOUT,
            headers={"User-Agent": WEBSITE_USER_AGENT},
            allow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.debug("Website scrape failed for %s: %s", domain, e)
        return None

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        logger.debug("Non-HTML content type for %s: %s", domain, content_type)
        return None

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.debug("HTML parse failed for %s: %s", domain, e)
        return None

    # Extract page title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Extract meta description
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"].strip()

    # Remove script, style, nav, footer, header elements
    for tag in soup.find_all(
        ["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe"]
    ):
        tag.decompose()

    # Extract visible text
    body_text = soup.get_text(separator=" ", strip=True)
    # Collapse multiple whitespace
    body_text = re.sub(r"\s+", " ", body_text).strip()

    # Assemble output
    parts = []
    if title:
        parts.append(f"Page title: {title}")
    if meta_desc:
        parts.append(f"Meta description: {meta_desc}")
    if body_text:
        parts.append(f"Page content: {body_text}")

    if not parts:
        return None

    result = "\n".join(parts)

    # Truncate to max chars
    if len(result) > WEBSITE_MAX_CHARS:
        result = result[:WEBSITE_MAX_CHARS] + "..."

    return result


SYSTEM_PROMPT = """You are a B2B sales qualification research assistant. Your task is to gather accurate, verifiable company information.

Source priority (highest to lowest):
1. Official company filings (annual reports, registry entries)
2. Company website (about page, careers, press releases)
3. Third-party business databases (Crunchbase, LinkedIn, Bloomberg)
4. News articles and press coverage

Rules:
- Revenue/employee ratio above EUR 500K per employee should be flagged
- If you cannot verify a data point, use "unverified" — NEVER guess
- For revenue, prefer the most recent fiscal year available
- For employees, prefer LinkedIn headcount or official filings
- Return ONLY valid JSON, no markdown formatting"""

USER_PROMPT_TEMPLATE = """Research the following company and return a JSON object with exactly these fields:

Company: {company_name}
{domain_line}
{contacts_section}
{claims_section}

Return this exact JSON structure (use ONLY the listed enum values — no free text for constrained fields):
{{
  "company_name": "Official company name as found in research",
  "summary": "2-3 sentence description of what the company does",
  "b2b": true/false or null if unclear,
  "hq": "City, Country",
  "markets": ["list", "of", "markets"],
  "founded": "YYYY or null",
  "ownership": "Public|Private|Family-owned|PE-backed (name)|VC-backed|Government|Cooperative|Unknown",
  "industry": "EXACTLY ONE OF: software_saas|it|professional_services|financial_services|healthcare|pharma_biotech|manufacturing|automotive|aerospace_defense|retail|hospitality|media|energy|telecom|transport|construction|real_estate|agriculture|education|public_sector|creative_services|other",
  "business_type": "EXACTLY ONE OF: distributor|hybrid|manufacturer|platform|product_company|saas|service_company (product_company = builds/sells own product; saas = cloud software; service_company = consulting/agency/outsourcing; manufacturer = physical production; distributor = resale/wholesale; platform = marketplace/exchange; hybrid = multiple models)",
  "revenue_eur_m": "Annual revenue in EUR millions (number) or 'unverified'",
  "revenue_year": "YYYY of the revenue figure",
  "revenue_source": "Where the revenue figure comes from",
  "employees": "Headcount (number) or 'unverified'",
  "employees_source": "Where the headcount comes from",
  "competitors": "Top 3-5 named competitors. Or 'Unknown'",
  "confidence": 0.0 to 1.0,
  "flags": ["list of any concerns or data quality issues"]
}}"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


@traceable(name="enrich_company_profile", run_type="chain")
def enrich_l1(company_id, tenant_id=None, previous_data=None, boost=False):
    """Run L1 enrichment for a single company.

    Args:
        company_id: UUID string of the company
        tenant_id: UUID string of the tenant (optional, read from company if not given)
        previous_data: dict of prior enrichment fields for re-enrichment context
        boost: if True, use higher-quality (more expensive) Perplexity model

    Returns:
        dict with enrichment_cost_usd and qc_flags
    """
    start_time = time.time()

    # 1. Read company from PG
    row = db.session.execute(
        text("""
            SELECT c.id, c.tenant_id, c.name, c.domain, c.industry,
                   c.company_size, c.verified_revenue_eur_m, c.is_self
            FROM companies c
            WHERE c.id = :id
        """),
        {"id": str(company_id)},
    ).fetchone()

    if not row:
        return {"enrichment_cost_usd": 0, "qc_flags": ["company_not_found"]}

    company_id = str(row[0])
    tenant_id = tenant_id or str(row[1])
    company_name = row[2]
    domain = row[3]
    existing_industry = row[4]
    existing_size = row[5]
    existing_revenue = float(row[6]) if row[6] else None
    is_self = row[7]

    # Skip tenant's own company — never enrich self
    if is_self:
        logger.info("Skipping self-company %s — is_self=True", company_name)
        return {"enrichment_cost_usd": 0, "qc_flags": ["skipped_self_company"]}

    # 2. Resolve domain and gather contact context
    contact_linkedin_urls = _get_contact_linkedin_urls(company_id, limit=3)
    if not domain:
        domain = _resolve_domain(company_id)

    # 2b. Auto-load previous enrichment if not provided
    if previous_data is None:
        previous_data = _load_previous_enrichment(company_id)

    # 2c. Scrape company website for context (best-effort)
    website_content = None
    if domain:
        website_content = scrape_website(domain)
        if website_content:
            logger.info("Scraped %d chars from %s", len(website_content), domain)
        else:
            logger.debug("No website content obtained for %s", domain)

    # 2d. Resolve enrichment language from tenant settings
    enrichment_lang = None
    try:
        from ..models import Tenant

        tenant_obj = db.session.get(Tenant, tenant_id)
        if tenant_obj:
            from .language import get_enrichment_language

            enrichment_lang = get_enrichment_language(tenant_obj)
    except Exception:
        pass  # Fall back to English

    # 3. Call Perplexity
    model = get_model_for_stage("l1", boost=boost)
    try:
        pplx_response = _call_perplexity(
            company_name,
            domain,
            existing_industry,
            existing_size,
            existing_revenue,
            contact_linkedin_urls,
            previous_data=previous_data,
            model=model,
            website_content=website_content,
            enrichment_language=enrichment_lang,
        )
        raw_response = pplx_response.content
        usage = {
            "input_tokens": pplx_response.input_tokens,
            "output_tokens": pplx_response.output_tokens,
        }
    except Exception as e:
        logger.error("Perplexity API error for company %s: %s", company_id, e)
        _set_company_status(company_id, "enrichment_failed", error_message=str(e)[:500])
        return {"enrichment_cost_usd": 0, "qc_flags": ["api_error"]}

    # 4. Parse response
    research = _parse_research_json(raw_response)
    if research is None:
        logger.warning("Failed to parse Perplexity response for company %s", company_id)
        _set_company_status(
            company_id,
            "enrichment_failed",
            error_message="Failed to parse research response",
        )
        return {"enrichment_cost_usd": 0, "qc_flags": ["parse_error"]}

    # 5. Map fields
    mapped = _map_fields(research)

    # 6. QC validation
    qc_flags = _validate_research(research, company_name)

    # 7. Compute cost (use client's cost tracking)
    duration_ms = int((time.time() - start_time) * 1000)
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cost_float = pplx_response.cost_usd

    # 8. Determine status
    if qc_flags:
        status = "needs_review"
        error_message = json.dumps(qc_flags)
        quality_score = max(0, 100 - len(qc_flags) * 15)
    else:
        status = "triage_passed"
        error_message = None
        quality_score = 100

    confidence_score = _parse_confidence(research.get("confidence"))

    # 9. UPDATE company
    _update_company(company_id, status, mapped, cost_float, error_message)

    # 9b. UPSERT company_enrichment_l1
    _upsert_enrichment_l1(
        company_id,
        mapped,
        research,
        cost_float,
        confidence_score,
        quality_score,
        qc_flags,
    )

    # 10. INSERT research_asset (raw SQL — table may not exist in tests)
    _insert_research_asset(
        tenant_id,
        company_id,
        model,
        cost_float,
        research,
        confidence_score,
        quality_score,
    )

    # 11. Log LLM usage
    if log_llm_usage:
        log_llm_usage(
            tenant_id=tenant_id,
            operation="l1_enrichment",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider="perplexity",
            duration_ms=duration_ms,
            metadata={
                "company_id": company_id,
                "company_name": company_name,
                "boost": boost,
            },
        )

    db.session.commit()

    return {"enrichment_cost_usd": cost_float, "qc_flags": qc_flags}


# ---------------------------------------------------------------------------
# Domain resolution
# ---------------------------------------------------------------------------


def _resolve_domain(company_id):
    """Try to resolve a company domain from contact email addresses.

    Returns domain string or None.
    """
    rows = db.session.execute(
        text("""
            SELECT DISTINCT email_address
            FROM contacts
            WHERE company_id = :id AND email_address LIKE '%%@%%'
        """),
        {"id": str(company_id)},
    ).fetchall()

    for row in rows:
        email = row[0]
        if not email or "@" not in email:
            continue
        d = email.split("@", 1)[1].strip().lower()
        if d and d not in FREE_MAIL_DOMAINS:
            # Update company domain
            db.session.execute(
                text("UPDATE companies SET domain = :d WHERE id = :id"),
                {"d": d, "id": str(company_id)},
            )
            return d

    return None


def _get_contact_linkedin_urls(company_id, limit=3):
    """Fetch LinkedIn profile URLs for contacts linked to this company.

    Returns list of (name, linkedin_url) tuples (up to limit).
    """
    rows = db.session.execute(
        text("""
            SELECT first_name, last_name, job_title, linkedin_url
            FROM contacts
            WHERE company_id = :id AND linkedin_url IS NOT NULL AND linkedin_url != ''
            LIMIT :lim
        """),
        {"id": str(company_id), "lim": limit},
    ).fetchall()

    results = []
    for row in rows:
        name_parts = [row[0] or "", row[1] or ""]
        name = " ".join(p for p in name_parts if p).strip() or "Unknown"
        title = row[2] or ""
        url = row[3]
        results.append((name, title, url))
    return results


# ---------------------------------------------------------------------------
# Previous enrichment loader
# ---------------------------------------------------------------------------


def _load_previous_enrichment(company_id):
    """Load prior L1 enrichment data for re-enrichment context.

    Reads from company_enrichment_l1 table. Returns dict of prior research
    fields + QC flags, or None if no prior enrichment exists.
    """
    try:
        row = db.session.execute(
            text("""
                SELECT raw_response, qc_flags, confidence, quality_score
                FROM company_enrichment_l1
                WHERE company_id = :id
            """),
            {"id": str(company_id)},
        ).fetchone()
    except Exception as e:
        logger.debug("Could not load previous enrichment for %s: %s", company_id, e)
        return None

    if not row:
        return None

    raw_response = row[0]
    qc_flags = row[1]
    confidence = row[2]
    quality_score = row[3]

    # Parse raw_response JSON
    prev = {}
    if raw_response:
        try:
            prev = json.loads(raw_response) if isinstance(raw_response, str) else {}
        except (json.JSONDecodeError, ValueError):
            prev = {}

    # Add QC context so the LLM can address previous issues
    if qc_flags:
        try:
            flags_list = json.loads(qc_flags) if isinstance(qc_flags, str) else qc_flags
            if flags_list:
                prev["previous_qc_flags"] = ", ".join(str(f) for f in flags_list)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    if confidence is not None:
        prev["previous_confidence"] = float(confidence)
    if quality_score is not None:
        prev["previous_quality_score"] = int(quality_score)

    return prev if prev else None


# ---------------------------------------------------------------------------
# Perplexity API call
# ---------------------------------------------------------------------------


def _call_perplexity(
    company_name,
    domain,
    existing_industry,
    existing_size,
    existing_revenue,
    contact_linkedin_urls=None,
    previous_data=None,
    model=None,
    website_content=None,
    enrichment_language=None,
):
    """Call Perplexity sonar API for company research.

    Args:
        model: Perplexity model name (default: PERPLEXITY_MODEL constant)
        enrichment_language: Two-letter language code for output language
        website_content: Scraped text from the company's website (optional)

    Returns:
        PerplexityResponse with .content, .input_tokens, .output_tokens, .cost_usd
    """
    api_key = current_app.config.get("PERPLEXITY_API_KEY", "")
    base_url = current_app.config.get(
        "PERPLEXITY_BASE_URL", "https://api.perplexity.ai"
    )

    if not api_key:
        raise ValueError("PERPLEXITY_API_KEY not configured")

    model = model or PERPLEXITY_MODEL

    # Build user prompt
    domain_line = f"Domain: {domain}" if domain else "Domain: unknown"

    # Contact LinkedIn context
    contacts_section = ""
    if contact_linkedin_urls:
        lines = []
        for name, title, url in contact_linkedin_urls:
            label = f"{name} ({title})" if title else name
            lines.append(f"- {label}: {url}")
        contacts_section = "Known employees at this company:\n" + "\n".join(lines)

    claims = []
    if existing_industry:
        claims.append(f"Claimed industry: {existing_industry}")
    if existing_size:
        claims.append(f"Claimed size: {existing_size}")
    if existing_revenue:
        claims.append(f"Claimed revenue: EUR {existing_revenue}M")

    claims_section = (
        "Existing claims to verify:\n" + "\n".join(f"- {c}" for c in claims)
        if claims
        else ""
    )

    # Build website content section
    website_section = ""
    if website_content:
        website_section = (
            f"\n\nThe following content was extracted from the company's website ({domain}):\n"
            "---\n"
            f"{website_content}\n"
            "---\n"
            "Use this as primary context about the company. Supplement with external research."
        )

    # Build previous data section for re-enrichment
    previous_section = ""
    if previous_data:
        prev_lines = []
        for k, v in previous_data.items():
            if v is not None and v != "":
                prev_lines.append(f"- {k}: {v}")
        if prev_lines:
            previous_section = (
                "\n\nPrevious enrichment data (validate, correct errors, and extend "
                "with new findings — do not discard valid data):\n"
                + "\n".join(prev_lines)
            )

    user_prompt = (
        USER_PROMPT_TEMPLATE.format(
            company_name=company_name,
            domain_line=domain_line,
            contacts_section=contacts_section,
            claims_section=claims_section,
        )
        + website_section
        + previous_section
    )

    client = PerplexityClient(
        api_key=api_key,
        base_url=base_url,
        default_model=model,
    )

    # Inject language instruction into system prompt
    effective_system_prompt = SYSTEM_PROMPT
    if enrichment_language and enrichment_language != "en":
        from ..display import LANGUAGE_NAMES

        lang_name = LANGUAGE_NAMES.get(enrichment_language, enrichment_language)
        effective_system_prompt += (
            f"\n\nIMPORTANT: Conduct research and write all output "
            f"in {lang_name}. Field names and enum values must remain "
            f"in English, but descriptive text (summary, markets, hq, etc.) "
            f"should be in {lang_name}."
        )

    return client.query(
        system_prompt=effective_system_prompt,
        user_prompt=user_prompt,
        model=model,
        max_tokens=PERPLEXITY_MAX_TOKENS,
        temperature=PERPLEXITY_TEMPERATURE,
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_research_json(content):
    """Parse the JSON response from Perplexity, stripping markdown fences if present.

    Returns dict or None on failure.
    """
    if not content:
        return None

    text_content = content.strip()

    # Strip markdown code fences
    if text_content.startswith("```"):
        lines = text_content.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove last line if it's closing fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text_content = "\n".join(lines).strip()

    try:
        return json.loads(text_content)
    except (json.JSONDecodeError, ValueError):
        # Try to find JSON object in the text
        match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text_content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except (json.JSONDecodeError, ValueError):
                pass
        return None


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


def _map_fields(research):
    """Map Perplexity research JSON fields to company column values.

    Returns dict of column_name -> value.
    """
    mapped = {}

    # summary
    if research.get("summary"):
        mapped["summary"] = str(research["summary"])[:2000]

    # hq → hq_city, hq_country, geo_region
    hq = research.get("hq")
    if hq and isinstance(hq, str) and "," in hq:
        parts = hq.rsplit(",", 1)
        mapped["hq_city"] = parts[0].strip()
        mapped["hq_country"] = parts[1].strip()
        mapped["geo_region"] = _derive_geo_region(parts[1].strip())
    elif hq and isinstance(hq, str):
        mapped["hq_country"] = hq.strip()
        mapped["geo_region"] = _derive_geo_region(hq.strip())

    # ownership_type
    ownership = research.get("ownership")
    if ownership:
        mapped["ownership_type"] = _map_ownership(ownership)

    # industry + industry_category
    industry = research.get("industry")
    if industry:
        mapped_industry = _map_industry(industry)
        mapped["industry"] = mapped_industry
        if mapped_industry:
            from api.services.field_schema import industry_to_category

            cat = industry_to_category(mapped_industry)
            if cat:
                mapped["industry_category"] = cat

    # business_type (Perplexity field is still "business_model" in prompt → maps to DB business_type)
    bm = research.get("business_model") or research.get("business_type")
    if bm:
        mapped["business_type"] = _map_business_type(bm)

    # revenue
    revenue = _parse_revenue(research.get("revenue_eur_m"))
    if revenue is not None:
        mapped["verified_revenue_eur_m"] = revenue
        mapped["revenue_range"] = _revenue_to_bucket(revenue)

    # employees
    employees = _parse_employees(research.get("employees"))
    if employees is not None:
        mapped["verified_employees"] = employees
        mapped["company_size"] = _employees_to_bucket(employees)

    # b2b → business_model
    b2b = research.get("b2b")
    if b2b is True:
        mapped["business_model"] = "b2b"
    elif b2b is False:
        mapped["business_model"] = "b2c"

    return mapped


# ---------------------------------------------------------------------------
# Helper functions (ported from n8n JS triage code)
# ---------------------------------------------------------------------------


def _parse_revenue(raw):
    """Parse revenue value from various formats.

    Handles: "42", "42M", "1.5 billion", "unverified", None → float or None
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)

    s = str(raw).strip().lower()
    if not s or s in ("unverified", "unknown", "n/a", "null", "none"):
        return None

    # Remove currency symbols and "eur"
    s = re.sub(r"[€$£]", "", s)
    s = re.sub(r"\beur\b", "", s, flags=re.IGNORECASE).strip()

    # Handle "billion"
    if "billion" in s:
        num = re.search(r"[\d,.]+", s)
        if num:
            return float(num.group().replace(",", "")) * 1000
        return None

    # Handle "million" or "m"
    if "million" in s or s.endswith("m"):
        s = re.sub(r"million|m$", "", s).strip()

    # Extract number
    num = re.search(r"[\d,.]+", s)
    if num:
        try:
            return float(num.group().replace(",", ""))
        except ValueError:
            return None

    return None


def _parse_employees(raw):
    """Parse employee count from various formats.

    Handles: "500", "200-300", "1,234", "unverified" → int or None
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)

    s = str(raw).strip().lower()
    if not s or s in ("unverified", "unknown", "n/a", "null", "none"):
        return None

    # Handle ranges like "200-300" — take midpoint
    range_match = re.match(r"([\d,]+)\s*[-–]\s*([\d,]+)", s)
    if range_match:
        low = int(range_match.group(1).replace(",", ""))
        high = int(range_match.group(2).replace(",", ""))
        return (low + high) // 2

    # Handle "~500", "approx 500", "about 500"
    s = re.sub(r"^[~≈]|^(approx\.?|about|around|roughly)\s*", "", s).strip()

    # Handle "1,000+" or "500+"
    s = re.sub(r"\+$", "", s).strip()

    # Extract number
    num = re.search(r"[\d,]+", s)
    if num:
        try:
            return int(num.group().replace(",", ""))
        except ValueError:
            return None

    return None


def _derive_geo_region(country_str):
    """Map country name to geo_region enum value.

    Delegates to the fuzzy enum mapper which handles synonyms,
    case normalization, and produces valid DB enum values.
    """
    return map_enum_value("geo_region", country_str)


def _map_ownership(raw):
    """Map ownership description to enum value.

    Resolution order:
    1. Fuzzy enum mapper (exact match + synonym lookup)
    2. Keyword substring matching for complex phrases like "PE-backed (EQT)"
    3. None if no match
    """
    if not raw:
        return None

    # Try enum mapper first (handles clean values)
    mapped = map_enum_value("ownership_type", raw)
    if mapped:
        return mapped

    # Keyword substring matching fallback for complex descriptions
    s = str(raw).strip().lower()
    if "family" in s:
        return "family_owned"
    if "pe" in s or "private equity" in s:
        return "pe_backed"
    if "vc" in s or "venture" in s:
        return "vc_backed"
    if "public" in s or "listed" in s:
        return "public"
    if "government" in s or "state" in s:
        return "state_owned"
    if "cooperative" in s or "coop" in s:
        return "other"
    if "bootstrap" in s or "private" in s:
        return "bootstrapped"

    return None


def _map_industry(raw):
    """Map industry description to an industry_enum value.

    Resolution order:
    1. Fuzzy enum mapper (exact match + synonym lookup)
    2. Keyword substring matching for complex phrases
    3. Fallback to "other"
    """
    if not raw:
        return None

    # Try enum mapper first (handles exact values + common synonyms)
    mapped = map_enum_value("industry", raw)
    if mapped:
        return mapped

    # Keyword substring matching for complex descriptions
    s = str(raw).strip().lower()
    keywords = {
        "creative_services": [
            "arts",
            "event",
            "culture",
            "performing",
            "music",
            "film",
            "design",
            "creative",
            "pr ",
            "public relation",
        ],
        "pharma_biotech": [
            "pharma",
            "biotech",
            "life science",
            "drug",
            "clinical trial",
        ],
        "aerospace_defense": [
            "aerospace",
            "defense",
            "defence",
            "military",
            "space",
            "satellite",
            "avionics",
        ],
        "automotive": [
            "automotive",
            "car ",
            "vehicle",
            "motor",
            "auto parts",
            "ev charging",
        ],
        "software_saas": ["software", "saas", "cloud", "app", "digital platform"],
        "it": ["it ", "information tech", "cyber", "data center", "hosting", "tech"],
        "professional_services": [
            "consult",
            "advisory",
            "legal",
            "accounting",
            "audit",
            "staffing",
            "recruitment",
        ],
        "financial_services": [
            "financ",
            "bank",
            "insur",
            "invest",
            "fintech",
            "payment",
        ],
        "healthcare": ["health", "medical", "hospital", "clinic", "dental", "care"],
        "real_estate": [
            "real estate",
            "property",
            "reit",
            "commercial space",
            "office space",
        ],
        "manufacturing": [
            "manufactur",
            "industrial",
            "machinery",
            "production",
            "factory",
            "automation",
        ],
        "retail": [
            "retail",
            "e-commerce",
            "ecommerce",
            "shop",
            "consumer goods",
            "fashion",
        ],
        "hospitality": [
            "hotel",
            "restaurant",
            "hospitality",
            "tourism",
            "travel",
            "food service",
            "catering",
        ],
        "media": [
            "media",
            "entertainment",
            "broadcast",
            "publishing",
            "gaming",
            "advertising",
        ],
        "energy": [
            "energy",
            "oil",
            "gas",
            "solar",
            "wind",
            "renewable",
            "power",
            "utility",
            "waste-to-energy",
        ],
        "agriculture": [
            "agricult",
            "farming",
            "agri",
            "food production",
            "crop",
            "livestock",
            "agtech",
        ],
        "telecom": ["telecom", "mobile", "wireless", "network operator"],
        "transport": [
            "transport",
            "logistics",
            "shipping",
            "freight",
            "aviation",
            "rail",
            "maritime",
        ],
        "construction": ["construct", "building", "architect", "civil engineer"],
        "education": [
            "education",
            "university",
            "school",
            "training",
            "e-learning",
            "edtech",
        ],
        "public_sector": [
            "government",
            "public sector",
            "ngo",
            "non-profit",
            "municipal",
        ],
    }
    for enum_val, kws in keywords.items():
        for kw in kws:
            if kw in s:
                return enum_val

    return "other"


def _map_business_type(raw):
    """Map business model/type description to business_type enum value.

    Resolution order:
    1. Fuzzy enum mapper (exact match + synonym lookup)
    2. Keyword substring matching for complex phrases
    3. Fallback to "other"
    """
    if not raw:
        return None

    # Try enum mapper first
    mapped = map_enum_value("business_type", raw)
    if mapped:
        return mapped

    # Keyword substring matching fallback
    s = str(raw).strip().lower()
    type_map = {
        "saas": "saas",
        "software": "saas",
        "manufactur": "manufacturer",
        "service": "service_provider",
        "consult": "service_provider",
        "distribut": "distributor",
        "wholesale": "distributor",
        "platform": "platform",
        "marketplace": "platform",
    }
    for key, value in type_map.items():
        if key in s:
            return value

    return "other"


def _revenue_to_bucket(rev_m):
    """Map revenue in EUR millions to a bucket."""
    from api.services.field_schema import revenue_to_range

    return revenue_to_range(rev_m)


def _employees_to_bucket(emp):
    """Map employee count to a size bucket."""
    from api.services.field_schema import employees_to_size

    return employees_to_size(emp)


def _parse_confidence(raw):
    """Parse confidence score from various formats → float 0-1 or None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if 0 <= float(raw) <= 1 else None

    s = str(raw).strip().lower()
    if s in ("low", "very low"):
        return 0.3
    if s in ("medium", "moderate"):
        return 0.6
    if s in ("high", "very high"):
        return 0.9

    try:
        v = float(s)
        return v if 0 <= v <= 1 else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# QC validation
# ---------------------------------------------------------------------------

QC_DEFAULTS = {
    "name_similarity_min": 0.6,
    "min_critical_fields": 4,
    "confidence_min": 0.4,
    "summary_min_length": 30,
    "max_revenue_m": 50000,
    "max_revenue_per_employee": 500_000,
    "max_employees": 500_000,
}


def _validate_research(research, original_name, qc_config=None):
    """Run QC checks on parsed research. Returns list of flag strings.

    Args:
        research: Parsed research dict from Perplexity
        original_name: Company name from DB for name matching
        qc_config: Optional dict of threshold overrides (keys from QC_DEFAULTS)
    """
    cfg = dict(QC_DEFAULTS)
    if qc_config:
        cfg.update(qc_config)

    flags = []

    # Name mismatch
    research_name = research.get("company_name", "")
    if research_name and original_name:
        similarity = _name_similarity(original_name, research_name)
        if similarity < cfg["name_similarity_min"]:
            flags.append("name_mismatch")

    # Missing critical fields
    critical_fields = ["summary", "hq", "industry", "employees", "revenue_eur_m"]
    populated = sum(
        1
        for f in critical_fields
        if research.get(f)
        and str(research.get(f)).lower()
        not in ("unverified", "unknown", "null", "none", "n/a")
    )
    if populated < cfg["min_critical_fields"]:
        flags.append("incomplete_research")

    # Revenue sanity
    revenue = _parse_revenue(research.get("revenue_eur_m"))
    employees = _parse_employees(research.get("employees"))
    if revenue is not None:
        if revenue > cfg["max_revenue_m"]:
            flags.append("revenue_implausible")
        elif employees and employees > 0 and revenue > 0:
            ratio = (revenue * 1_000_000) / employees
            if ratio > cfg["max_revenue_per_employee"]:
                flags.append("revenue_implausible")

    # Employee sanity
    if employees is not None:
        if employees > cfg["max_employees"] or employees < 0:
            flags.append("employees_implausible")

    # Low confidence
    confidence = _parse_confidence(research.get("confidence"))
    if confidence is not None and confidence < cfg["confidence_min"]:
        flags.append("low_confidence")

    # B2B unclear
    b2b = research.get("b2b")
    if b2b is None:
        flags.append("b2b_unclear")

    # Summary too short
    summary = research.get("summary", "")
    if isinstance(summary, str) and len(summary.strip()) < cfg["summary_min_length"]:
        flags.append("summary_too_short")

    # Merge Perplexity's own flags — look for high-severity indicators
    pplx_flags = research.get("flags", [])
    if isinstance(pplx_flags, list):
        for pf in pplx_flags:
            pf_lower = str(pf).lower()
            if any(
                kw in pf_lower
                for kw in (
                    "not found",
                    "no matching",
                    "non-existent",
                    "defunct",
                    "discrepancy",
                    "mismatch",
                    "conflicting",
                )
            ):
                flags.append("source_warning")
                break  # One flag is enough

    return flags


def _name_similarity(name_a, name_b):
    """Simple bigram (Dice coefficient) similarity between two names."""
    if not name_a or not name_b:
        return 0.0

    a = name_a.strip().lower()
    b = name_b.strip().lower()

    if a == b:
        return 1.0

    # Strip common suffixes
    for suffix in (
        " inc",
        " inc.",
        " incorporated",
        " llc",
        " ltd",
        " ltd.",
        " limited",
        " gmbh",
        " ag",
        " sa",
        " se",
        " plc",
        " corp",
        " corp.",
        " corporation",
        " company",
        " co.",
        " s.r.o.",
        " a.s.",
        " a/s",
        " oy",
        " ab",
        " sp. z o.o.",
        " spol. s r.o.",
        " s.a.",
        " s.p.a.",
        " b.v.",
        " n.v.",
        " pty",
        " pty.",
    ):
        a = a.removesuffix(suffix)
        b = b.removesuffix(suffix)

    a = a.strip()
    b = b.strip()

    if a == b:
        return 1.0

    if not a or not b:
        return 0.0

    a_bigrams = set(a[i : i + 2] for i in range(len(a) - 1))
    b_bigrams = set(b[i : i + 2] for i in range(len(b) - 1))

    if not a_bigrams or not b_bigrams:
        return 0.0

    intersection = a_bigrams & b_bigrams
    return 2 * len(intersection) / (len(a_bigrams) + len(b_bigrams))


# ---------------------------------------------------------------------------
# DB writes
# ---------------------------------------------------------------------------


def _insert_research_asset(
    tenant_id, company_id, model, cost_float, research, confidence_score, quality_score
):
    """Insert research_asset row via raw SQL (avoids model import)."""
    try:
        research_json = json.dumps(research) if isinstance(research, dict) else "{}"
        db.session.execute(
            text("""
                INSERT INTO research_assets (
                    tenant_id, entity_type, entity_id, name, tool_name,
                    cost_usd, research_data, confidence_score, quality_score
                ) VALUES (
                    :tenant_id, 'company', :entity_id, 'l1_perplexity_research',
                    :tool_name, :cost_usd, :research_data,
                    :confidence_score, :quality_score
                )
            """),
            {
                "tenant_id": str(tenant_id),
                "entity_id": str(company_id),
                "tool_name": f"perplexity/{model}",
                "cost_usd": cost_float,
                "research_data": research_json,
                "confidence_score": confidence_score,
                "quality_score": quality_score,
            },
        )
    except Exception as e:
        # Table may not exist yet (e.g. during tests before migration)
        logger.warning("Failed to insert research_asset: %s", e)


def _set_company_status(company_id, status, error_message=None):
    """Update company status and optionally set error_message."""
    params = {"id": str(company_id), "status": status}
    if error_message:
        db.session.execute(
            text(
                "UPDATE companies SET status = :status, error_message = :err, updated_at = CURRENT_TIMESTAMP WHERE id = :id"
            ),
            {**params, "err": error_message},
        )
    else:
        db.session.execute(
            text(
                "UPDATE companies SET status = :status, updated_at = CURRENT_TIMESTAMP WHERE id = :id"
            ),
            params,
        )
    db.session.commit()


def _update_company(company_id, status, mapped, cost, error_message):
    """Update company with enrichment results."""
    set_clauses = [
        "status = :status",
        "enrichment_cost_usd = enrichment_cost_usd + :cost",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    params = {"id": str(company_id), "status": status, "cost": cost}

    if error_message:
        set_clauses.append("error_message = :err")
        params["err"] = error_message
    else:
        set_clauses.append("error_message = NULL")

    # Add mapped fields
    for col, val in mapped.items():
        param_key = f"m_{col}"
        set_clauses.append(f"{col} = :{param_key}")
        params[param_key] = val

    sql = f"UPDATE companies SET {', '.join(set_clauses)} WHERE id = :id"
    db.session.execute(text(sql), params)


def _upsert_enrichment_l1(
    company_id, mapped, research, cost_float, confidence_score, quality_score, qc_flags
):
    """Upsert enrichment detail into company_enrichment_l1 table."""
    try:
        # Build the raw_response JSON
        raw_json = json.dumps(research) if isinstance(research, dict) else "{}"
        qc_json = json.dumps(qc_flags) if isinstance(qc_flags, list) else "[]"

        # triage_notes: use summary as proxy (L1 doesn't produce a separate field)
        triage_notes = mapped.get("triage_notes") or mapped.get("summary", "")[:500]
        # pre_score: use triage_score if available in mapped
        pre_score = mapped.get("pre_score") or mapped.get("triage_score")

        # Use dialect-appropriate upsert
        dialect = db.engine.dialect.name
        if dialect == "sqlite":
            db.session.execute(
                text("""
                    INSERT OR REPLACE INTO company_enrichment_l1 (
                        company_id, triage_notes, pre_score, research_query,
                        raw_response, confidence, quality_score, qc_flags,
                        enriched_at, enrichment_cost_usd, created_at, updated_at
                    ) VALUES (
                        :company_id, :triage_notes, :pre_score, :research_query,
                        :raw_response, :confidence, :quality_score, :qc_flags,
                        CURRENT_TIMESTAMP, :cost, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                """),
                {
                    "company_id": str(company_id),
                    "triage_notes": triage_notes,
                    "pre_score": pre_score,
                    "research_query": None,  # Could store the prompt if needed
                    "raw_response": raw_json,
                    "confidence": confidence_score,
                    "quality_score": quality_score,
                    "qc_flags": qc_json,
                    "cost": cost_float,
                },
            )
        else:
            db.session.execute(
                text("""
                    INSERT INTO company_enrichment_l1 (
                        company_id, triage_notes, pre_score, research_query,
                        raw_response, confidence, quality_score, qc_flags,
                        enriched_at, enrichment_cost_usd
                    ) VALUES (
                        :company_id, :triage_notes, :pre_score, :research_query,
                        CAST(:raw_response AS jsonb), :confidence, :quality_score, CAST(:qc_flags AS jsonb),
                        CURRENT_TIMESTAMP, :cost
                    )
                    ON CONFLICT (company_id) DO UPDATE SET
                        triage_notes = EXCLUDED.triage_notes,
                        pre_score = EXCLUDED.pre_score,
                        research_query = EXCLUDED.research_query,
                        raw_response = EXCLUDED.raw_response,
                        confidence = EXCLUDED.confidence,
                        quality_score = EXCLUDED.quality_score,
                        qc_flags = EXCLUDED.qc_flags,
                        enriched_at = CURRENT_TIMESTAMP,
                        enrichment_cost_usd = company_enrichment_l1.enrichment_cost_usd + EXCLUDED.enrichment_cost_usd,
                        updated_at = CURRENT_TIMESTAMP
                """),
                {
                    "company_id": str(company_id),
                    "triage_notes": triage_notes,
                    "pre_score": pre_score,
                    "research_query": None,
                    "raw_response": raw_json,
                    "confidence": confidence_score,
                    "quality_score": quality_score,
                    "qc_flags": qc_json,
                    "cost": cost_float,
                },
            )
    except Exception as e:
        db.session.rollback()
        logger.warning(
            "Failed to upsert company_enrichment_l1 for %s: %s", company_id, e
        )
