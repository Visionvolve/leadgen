"""Domain-first company research service — pure Python, no n8n dependency.

Replaces the L1 (Perplexity sonar) + L2 (Perplexity + Anthropic synthesis)
two-step enrichment with a single, domain-first research pipeline:

1. Fetch & parse the company website (homepage + about/team/products pages)
2. Use extracted info to run targeted Perplexity web searches
3. Synthesize all findings into structured enrichment profile via Claude
4. Save results to the same enrichment tables used by _load_enrichment_data()

This produces data compatible with the existing enrichment data format so
downstream consumers (template seeding, AI system prompt) still work.

Progress events are emitted via an on_progress callback for real-time
display in chat tool cards.
"""

import ipaddress
import json
import logging
import re
import socket
import time
from datetime import datetime, timezone

import requests as http_requests
from bs4 import BeautifulSoup
from sqlalchemy import text

from ..models import db
from .anthropic_client import AnthropicClient
from .perplexity_client import PerplexityClient

try:
    from .llm_logger import log_llm_usage
except ImportError:
    log_llm_usage = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WEBSITE_TIMEOUT = 12  # seconds per page fetch
WEBSITE_MAX_CHARS = 6000  # truncate scraped text per page
WEBSITE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# Max pages to follow beyond homepage
MAX_SUBPAGES = 3
# Subpage link patterns (about, team, products, services)
SUBPAGE_PATTERNS = re.compile(
    r"/(about|team|people|leadership|products|services|solutions|what-we-do|our-work|company)",
    re.IGNORECASE,
)

PERPLEXITY_MODEL = "sonar-pro"
PERPLEXITY_MAX_TOKENS = 1200
PERPLEXITY_TEMPERATURE = 0.2

ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
ANTHROPIC_MAX_TOKENS = 4000
ANTHROPIC_TEMPERATURE = 0.3


# ---------------------------------------------------------------------------
# Progress event helper
# ---------------------------------------------------------------------------


def _make_event(
    step, tool_name, target, status, summary="", detail=None, duration_ms=0
):
    """Build a progress event dict."""
    return {
        "step": step,
        "tool_name": tool_name,
        "target": target,
        "status": status,
        "summary": summary,
        "detail": detail or {},
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Website fetching and parsing
# ---------------------------------------------------------------------------


def _fetch_page(url, timeout=WEBSITE_TIMEOUT):
    """Fetch a single URL and return the response, or None on failure."""
    try:
        resp = http_requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": WEBSITE_USER_AGENT},
            allow_redirects=True,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            return None
        return resp
    except Exception as exc:
        logger.debug("Failed to fetch %s: %s", url, exc)
        return None


def _parse_html(html_text):
    """Parse HTML and extract structured content.

    Returns dict with: title, meta_description, body_text, links (list of hrefs).
    """
    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception:
        return None

    # Title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Meta description
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"].strip()

    # OG description fallback
    if not meta_desc:
        og_tag = soup.find("meta", attrs={"property": "og:description"})
        if og_tag and og_tag.get("content"):
            meta_desc = og_tag["content"].strip()

    # Collect all internal links before stripping navigation
    links = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if href and not href.startswith(("mailto:", "tel:", "javascript:", "#")):
            links.append(href)

    # Remove non-content elements
    for tag in soup.find_all(
        ["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe"]
    ):
        tag.decompose()

    # Extract visible text
    body_text = soup.get_text(separator=" ", strip=True)
    body_text = re.sub(r"\s+", " ", body_text).strip()

    return {
        "title": title,
        "meta_description": meta_desc,
        "body_text": body_text[:WEBSITE_MAX_CHARS],
        "links": links,
    }


def _find_subpage_urls(base_url, links):
    """Find relevant subpage URLs (about, team, products) from link list.

    Returns up to MAX_SUBPAGES unique absolute URLs.
    """
    from urllib.parse import urljoin, urlparse

    base_parsed = urlparse(base_url)
    seen = set()
    results = []

    for href in links:
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)

        # Same domain only
        if parsed.netloc and parsed.netloc != base_parsed.netloc:
            continue

        # Match subpage patterns
        if SUBPAGE_PATTERNS.search(parsed.path):
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
            if normalized not in seen:
                seen.add(normalized)
                results.append(normalized)
                if len(results) >= MAX_SUBPAGES:
                    break

    return results


def fetch_website(domain, on_progress=None):
    """Fetch and parse company website: homepage + relevant subpages.

    Args:
        domain: Company domain (e.g., "unitedarts.cz")
        on_progress: Optional callback for progress events

    Returns:
        dict with:
            homepage: parsed homepage content dict
            subpages: list of parsed subpage content dicts
            all_text: combined text from all pages
            pages_fetched: number of pages successfully fetched
        Or None if homepage fetch failed.
    """
    if not domain:
        return None

    # Defence-in-depth: reject private/internal domains even if the caller
    # already validated.  Prevents SSRF to cloud metadata, localhost, etc.
    hostname = domain.split(":")[0].strip().rstrip("/")
    if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
        logger.warning("fetch_website blocked private domain: %s", domain)
        return None
    try:
        resolved = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(resolved)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            logger.warning(
                "fetch_website blocked domain %s (resolved to %s)", domain, resolved
            )
            return None
    except Exception:
        logger.warning("fetch_website could not resolve domain: %s", domain)
        return None

    base_url = f"https://{domain}/"
    start = time.time()

    if on_progress:
        on_progress(
            _make_event(
                "website_fetch",
                "Company Website Research",
                domain,
                "running",
                f"Visiting {domain}...",
            )
        )

    # Fetch homepage
    resp = _fetch_page(base_url)
    if resp is None:
        # Try HTTP fallback
        resp = _fetch_page(f"http://{domain}/")
    if resp is None:
        if on_progress:
            on_progress(
                _make_event(
                    "website_fetch",
                    "Company Website Research",
                    domain,
                    "error",
                    f"Could not reach {domain}",
                    duration_ms=int((time.time() - start) * 1000),
                )
            )
        return None

    homepage = _parse_html(resp.text)
    if homepage is None:
        return None

    # Find and fetch relevant subpages
    subpage_urls = _find_subpage_urls(base_url, homepage["links"])
    subpages = []
    for url in subpage_urls:
        sub_resp = _fetch_page(url, timeout=8)
        if sub_resp:
            parsed = _parse_html(sub_resp.text)
            if parsed and parsed["body_text"]:
                parsed["url"] = url
                subpages.append(parsed)

    # Combine all text
    all_parts = []
    if homepage["title"]:
        all_parts.append(f"Homepage title: {homepage['title']}")
    if homepage["meta_description"]:
        all_parts.append(f"Description: {homepage['meta_description']}")
    if homepage["body_text"]:
        all_parts.append(f"Homepage content: {homepage['body_text']}")

    for sp in subpages:
        page_label = sp.get("url", "subpage").split("/")[-1] or "subpage"
        if sp["title"]:
            all_parts.append(f"{page_label} title: {sp['title']}")
        if sp["body_text"]:
            all_parts.append(f"{page_label} content: {sp['body_text'][:3000]}")

    all_text = "\n\n".join(all_parts)

    duration_ms = int((time.time() - start) * 1000)
    pages_fetched = 1 + len(subpages)

    if on_progress:
        summary = f"Fetched {pages_fetched} pages from {domain}"
        if homepage["title"]:
            summary += f" — {homepage['title']}"
        on_progress(
            _make_event(
                "website_fetch",
                "Company Website Research",
                domain,
                "completed",
                summary,
                detail={
                    "pages_fetched": pages_fetched,
                    "title": homepage["title"],
                    "meta_description": homepage["meta_description"],
                    "subpages": [sp.get("url", "") for sp in subpages],
                },
                duration_ms=duration_ms,
            )
        )

    return {
        "homepage": homepage,
        "subpages": subpages,
        "all_text": all_text,
        "pages_fetched": pages_fetched,
    }


# ---------------------------------------------------------------------------
# Web search via Perplexity
# ---------------------------------------------------------------------------


_SEARCH_SYSTEM = """You are a business intelligence researcher. Given a company name, \
domain, and extracted website content, gather accurate supplementary information.

## RULES
- Only include information specifically about THIS company (verify domain match)
- Current date is provided — "recent" means last 12 months
- If you cannot verify a fact, say "unverified" — NEVER guess
- Return ONLY valid JSON. No markdown. No code fences. Start with {{

## OUTPUT FORMAT
{{
  "company_name": "Official company name",
  "summary": "2-3 sentence description of what the company does",
  "b2b": true/false/null,
  "industry": "software_saas|it|professional_services|financial_services|healthcare|pharma_biotech|manufacturing|automotive|aerospace_defense|retail|hospitality|media|energy|telecom|transport|construction|real_estate|agriculture|education|public_sector|creative_services|other",
  "business_type": "distributor|hybrid|manufacturer|platform|product_company|saas|service_company",
  "hq": "City, Country",
  "founded": "YYYY or null",
  "ownership": "Public|Private|Family-owned|PE-backed|VC-backed|Government|Cooperative|Unknown",
  "employees": "number or 'unverified'",
  "employees_source": "source of headcount",
  "revenue_eur_m": "number or 'unverified'",
  "revenue_year": "YYYY",
  "revenue_source": "source of revenue figure",
  "competitors": "Top 3-5 named competitors or 'Unknown'",
  "key_products": "Main products/services",
  "customer_segments": "Target customer types",
  "tech_stack": "Known technologies used",
  "recent_news": "Business events from last 12 months (max 5) or 'None found'",
  "funding": "Funding/investment with amounts and dates or 'None found'",
  "leadership_team": "Key executives (CEO, CTO, etc.) or 'Unknown'",
  "leadership_changes": "C-level hires/departures or 'None found'",
  "expansion": "New markets, offices, contracts or 'None found'",
  "digital_initiatives": "ERP, CRM, cloud, AI implementations or 'None found'",
  "hiring_signals": "Hiring trends, growth areas or 'None found'",
  "revenue_trend": "growing|stable|declining|restructuring with evidence or 'Unknown'",
  "growth_signals": "Concrete growth evidence or 'None found'",
  "ma_activity": "M&A activity with dates or 'None found'",
  "certifications": "ISO, SOC, industry certs or 'None found'",
  "confidence": 0.0 to 1.0
}}"""


_SEARCH_USER_TEMPLATE = """Research this company and return supplementary business intelligence.

Company: {company_name}
Website: {domain}
Current date: {current_date}

## WEBSITE CONTENT (already extracted — use as ground truth):
{website_excerpt}

## INSTRUCTIONS
1. Use the website content above as the primary source of truth
2. Search for additional context: news, funding, competitors, team
3. Cross-reference any claims from the website against external sources
4. Fill in gaps the website doesn't cover (financials, competitors, news)
5. Do NOT contradict verified information from the website"""


def run_web_search(domain, company_name, website_text, on_progress=None):
    """Run a Perplexity web search to supplement website data.

    Args:
        domain: Company domain
        company_name: Company name (from website title or provided)
        website_text: Text extracted from company website
        on_progress: Optional progress callback

    Returns:
        tuple of (search_results_dict, cost_usd, usage_dict)
    """
    start = time.time()

    if on_progress:
        on_progress(
            _make_event(
                "web_search",
                "Web Intelligence Search",
                domain,
                "running",
                f"Searching for business intelligence on {company_name}...",
            )
        )

    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Truncate website text for the prompt context
    website_excerpt = (
        website_text[:4000] if website_text else "No website content available"
    )

    user_prompt = _SEARCH_USER_TEMPLATE.format(
        company_name=company_name,
        domain=domain,
        current_date=current_date,
        website_excerpt=website_excerpt,
    )

    client = PerplexityClient()
    try:
        response = client.query(
            system_prompt=_SEARCH_SYSTEM,
            user_prompt=user_prompt,
            model=PERPLEXITY_MODEL,
            max_tokens=PERPLEXITY_MAX_TOKENS,
            temperature=PERPLEXITY_TEMPERATURE,
            search_recency_filter="year",
        )
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        logger.error("Web search failed for %s: %s", domain, exc)
        if on_progress:
            on_progress(
                _make_event(
                    "web_search",
                    "Web Intelligence Search",
                    domain,
                    "error",
                    f"Search failed: {exc}",
                    duration_ms=duration_ms,
                )
            )
        return {}, 0.0, {}

    # Parse response
    raw = response.content
    results = _parse_json_response(raw)

    duration_ms = int((time.time() - start) * 1000)
    usage = {
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "model": PERPLEXITY_MODEL,
        "provider": "perplexity",
    }

    if on_progress:
        summary_parts = []
        if results.get("industry"):
            summary_parts.append(f"Industry: {results['industry']}")
        if results.get("employees") and results["employees"] != "unverified":
            summary_parts.append(f"~{results['employees']} employees")
        if results.get("revenue_trend") and results["revenue_trend"] != "Unknown":
            summary_parts.append(f"Revenue: {results['revenue_trend']}")
        summary = ", ".join(summary_parts) if summary_parts else "Search completed"

        on_progress(
            _make_event(
                "web_search",
                "Web Intelligence Search",
                domain,
                "completed",
                summary,
                detail={"fields_found": len([v for v in results.values() if v])},
                duration_ms=duration_ms,
            )
        )

    return results, response.cost_usd, usage


# ---------------------------------------------------------------------------
# AI Synthesis via Claude
# ---------------------------------------------------------------------------


_SYNTHESIS_SYSTEM = """You are a B2B sales intelligence analyst. Given raw research data \
about a company (from their website and web search), synthesize it into actionable \
intelligence for sales outreach.

## RULES
- Base your analysis on FACTS from the research — do not speculate
- Use professional, respectful language about the company and its people
- Focus on business opportunities and pain points relevant to AI/technology services
- Be specific — reference actual products, people, and events from the research
- Return ONLY valid JSON. No markdown. No code fences. Start with {{

## OUTPUT FORMAT
{{
  "executive_brief": "3-5 sentence company overview with key business insights",
  "ai_opportunities": "Specific AI/technology opportunities based on their business model and tech stack",
  "pain_hypothesis": "Likely business pains based on their industry, size, and current tech",
  "quick_wins": [{{"title": "Win title", "description": "What and why", "effort": "low|medium|high"}}],
  "industry_pain_points": "Industry-wide challenges that affect this company",
  "cross_functional_pain": "Pain points that span multiple departments",
  "adoption_barriers": "Likely barriers to adopting new technology",
  "pitch_framing": "Recommended approach for initial outreach",
  "competitor_ai_moves": "What competitors are doing with AI/technology",
  "key_products": "Their main products/services (from research)",
  "customer_segments": "Their target customers (from research)",
  "competitors": "Their main competitors (from research)",
  "tech_stack": "Known technology stack",
  "certifications": "Relevant certifications and standards"
}}"""


_SYNTHESIS_USER_TEMPLATE = """Synthesize the following research into actionable B2B sales intelligence.

## COMPANY
Name: {company_name}
Domain: {domain}

## WEBSITE CONTENT
{website_excerpt}

## WEB SEARCH RESULTS
{search_results}

## INSTRUCTIONS
1. Write an executive brief that captures who they are and what makes them interesting
2. Identify specific AI/technology opportunities based on their actual business
3. Develop a pain hypothesis grounded in their industry and operational reality
4. Suggest 2-3 quick wins (concrete, not generic)
5. Frame the optimal pitch approach based on their profile"""


def run_synthesis(domain, company_name, website_text, search_results, on_progress=None):
    """Run Claude synthesis of research findings.

    Args:
        domain: Company domain
        company_name: Company name
        website_text: Extracted website content
        search_results: Dict from web search step
        on_progress: Optional progress callback

    Returns:
        tuple of (synthesis_dict, cost_usd, usage_dict)
    """
    start = time.time()

    if on_progress:
        on_progress(
            _make_event(
                "ai_synthesis",
                "AI Analysis & Synthesis",
                domain,
                "running",
                f"Analyzing research findings for {company_name}...",
            )
        )

    # Format search results for the prompt
    search_text = (
        json.dumps(search_results, indent=2, default=str)
        if search_results
        else "No search results available"
    )
    website_excerpt = (
        website_text[:5000] if website_text else "No website content available"
    )

    user_prompt = _SYNTHESIS_USER_TEMPLATE.format(
        company_name=company_name,
        domain=domain,
        website_excerpt=website_excerpt,
        search_results=search_text,
    )

    client = AnthropicClient()
    try:
        response = client.query(
            system_prompt=_SYNTHESIS_SYSTEM,
            user_prompt=user_prompt,
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            temperature=ANTHROPIC_TEMPERATURE,
        )
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        logger.error("Synthesis failed for %s: %s", domain, exc)
        if on_progress:
            on_progress(
                _make_event(
                    "ai_synthesis",
                    "AI Analysis & Synthesis",
                    domain,
                    "error",
                    f"Synthesis failed: {exc}",
                    duration_ms=duration_ms,
                )
            )
        return {}, 0.0, {}

    raw = response.content
    synthesis = _parse_json_response(raw)

    duration_ms = int((time.time() - start) * 1000)
    usage = {
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "model": ANTHROPIC_MODEL,
        "provider": "anthropic",
    }

    if on_progress:
        summary_parts = []
        if synthesis.get("executive_brief"):
            # Take first sentence of executive brief
            brief = synthesis["executive_brief"]
            first_sentence = brief.split(".")[0] + "." if "." in brief else brief[:100]
            summary_parts.append(first_sentence)
        if synthesis.get("quick_wins"):
            qw_count = (
                len(synthesis["quick_wins"])
                if isinstance(synthesis["quick_wins"], list)
                else 0
            )
            if qw_count:
                summary_parts.append(f"{qw_count} quick wins identified")
        summary = " ".join(summary_parts) if summary_parts else "Analysis complete"

        on_progress(
            _make_event(
                "ai_synthesis",
                "AI Analysis & Synthesis",
                domain,
                "completed",
                summary,
                detail={
                    "has_pain_hypothesis": bool(synthesis.get("pain_hypothesis")),
                    "has_ai_opportunities": bool(synthesis.get("ai_opportunities")),
                    "quick_win_count": len(synthesis.get("quick_wins", []))
                    if isinstance(synthesis.get("quick_wins"), list)
                    else 0,
                },
                duration_ms=duration_ms,
            )
        )

    return synthesis, response.cost_usd, usage


# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------


def _parse_json_response(raw_text):
    """Parse JSON from LLM response, handling code fences."""
    text = raw_text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        else:
            text = text[3:]
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # Try to find JSON object in the text
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except (json.JSONDecodeError, ValueError):
                pass
    logger.warning("Failed to parse JSON from LLM response: %s...", text[:200])
    return {}


# ---------------------------------------------------------------------------
# Database save helpers
# ---------------------------------------------------------------------------


def _to_text(val):
    """Coerce a value to string for DB storage."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return ", ".join(str(v) for v in val)
    if isinstance(val, dict):
        return json.dumps(val)
    return str(val)


def _save_to_company(company_id, search_results, website_data):
    """Update the companies table with research findings."""
    fields = {}

    # Company name (prefer search results, fall back to website title)
    name = search_results.get("company_name")
    if not name and website_data and website_data.get("homepage"):
        title = website_data["homepage"].get("title", "")
        # Clean up title (remove " - tagline" suffixes)
        if " - " in title:
            name = title.split(" - ")[0].strip()
        elif " | " in title:
            name = title.split(" | ")[0].strip()
        else:
            name = title

    if name:
        fields["name"] = name

    # Summary
    if search_results.get("summary"):
        fields["summary"] = search_results["summary"]

    # Industry
    industry = search_results.get("industry")
    if industry and industry != "other":
        fields["industry"] = industry

    # HQ
    hq = search_results.get("hq")
    if hq and "," in hq:
        parts = [p.strip() for p in hq.split(",")]
        fields["hq_city"] = parts[0]
        fields["hq_country"] = parts[-1]

    # Business model
    b2b = search_results.get("b2b")
    if b2b is True:
        fields["business_model"] = "b2b"
    elif b2b is False:
        fields["business_model"] = "b2c"

    # Business type
    if search_results.get("business_type"):
        fields["business_type"] = search_results["business_type"]

    # Ownership
    if search_results.get("ownership") and search_results["ownership"] != "Unknown":
        fields["ownership_type"] = search_results["ownership"].lower().replace("-", "_")

    # Employees
    emp = search_results.get("employees")
    if emp and emp != "unverified":
        try:
            emp_num = int(str(emp).replace(",", "").replace("+", ""))
            fields["verified_employees"] = emp_num
            # Derive company_size bucket
            if emp_num < 10:
                fields["company_size"] = "micro"
            elif emp_num < 50:
                fields["company_size"] = "small"
            elif emp_num < 250:
                fields["company_size"] = "medium"
            elif emp_num < 1000:
                fields["company_size"] = "large"
            else:
                fields["company_size"] = "enterprise"
        except (ValueError, TypeError):
            pass

    # Revenue
    rev = search_results.get("revenue_eur_m")
    if rev and rev != "unverified":
        try:
            rev_num = float(str(rev).replace(",", ""))
            fields["verified_revenue_eur_m"] = rev_num
        except (ValueError, TypeError):
            pass

    # Confidence
    conf = search_results.get("confidence")
    if conf is not None:
        try:
            conf_float = float(conf)
            # Map to pre_score (0-100)
            fields["triage_score"] = int(conf_float * 100)
        except (ValueError, TypeError):
            pass

    if not fields:
        return

    # Build SET clause
    set_parts = []
    params = {"cid": str(company_id)}
    for key, val in fields.items():
        set_parts.append(f"{key} = :{key}")
        params[key] = val

    set_clause = ", ".join(set_parts)
    db.session.execute(
        text(f"UPDATE companies SET {set_clause} WHERE id = :cid"),
        params,
    )


def _save_l1_enrichment(company_id, search_results, cost_usd, confidence):
    """Upsert company_enrichment_l1 with research results."""
    params = {
        "cid": str(company_id),
        "triage_notes": _to_text(search_results.get("summary", "")),
        "pre_score": int(confidence * 100) if confidence else 50,
        "research_query": f"Domain-first research: {search_results.get('company_name', '')}",
        "raw_response": json.dumps(search_results, default=str),
        "confidence": confidence or 0.5,
        "quality_score": 85,  # Domain-first research is high quality
        "qc_flags": json.dumps([]),
        "enriched_at": datetime.now(timezone.utc),
        "cost": round(cost_usd, 4),
    }

    cols = (
        "triage_notes",
        "pre_score",
        "research_query",
        "raw_response",
        "confidence",
        "quality_score",
        "qc_flags",
    )
    col_list = ", ".join(cols)
    val_list = ", ".join(f":{c}" for c in cols)
    update_list = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)

    try:
        db.session.execute(
            text(f"""
                INSERT INTO company_enrichment_l1 (
                    company_id, {col_list}, enriched_at, enrichment_cost_usd
                ) VALUES (
                    :cid, {val_list}, :enriched_at, :cost
                )
                ON CONFLICT (company_id) DO UPDATE SET
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
                    INSERT OR REPLACE INTO company_enrichment_l1 (
                        company_id, {col_list}, enriched_at, enrichment_cost_usd
                    ) VALUES (
                        :cid, {val_list}, :enriched_at, :cost
                    )
                """),
                params,
            )
        else:
            db.session.execute(
                text(f"""
                    INSERT INTO company_enrichment_l1 (
                        company_id, {col_list}, enriched_at, enrichment_cost_usd
                    ) VALUES (
                        :cid, {val_list}, :enriched_at, :cost
                    )
                    ON CONFLICT (company_id) DO UPDATE SET
                        {update_list},
                        enriched_at = EXCLUDED.enriched_at,
                        enrichment_cost_usd = EXCLUDED.enrichment_cost_usd
                """),
                params,
            )


def _upsert_module(table_name, columns, params):
    """Generic upsert helper for enrichment tables."""
    col_list = ", ".join(columns)
    val_list = ", ".join(f":{c}" for c in columns)
    update_list = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns)
    try:
        db.session.execute(
            text(f"""
                INSERT INTO {table_name} (company_id, {col_list}, enriched_at, enrichment_cost_usd)
                VALUES (:cid, {val_list}, :enriched_at, :cost)
                ON CONFLICT (company_id) DO UPDATE SET
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
                    INSERT OR REPLACE INTO {table_name} (company_id, {col_list}, enriched_at, enrichment_cost_usd)
                    VALUES (:cid, {val_list}, :enriched_at, :cost)
                """),
                params,
            )
        else:
            db.session.execute(
                text(f"""
                    INSERT INTO {table_name} (company_id, {col_list}, enriched_at, enrichment_cost_usd)
                    VALUES (:cid, {val_list}, :enriched_at, :cost)
                    ON CONFLICT (company_id) DO UPDATE SET
                        {update_list},
                        enriched_at = EXCLUDED.enriched_at,
                        enrichment_cost_usd = EXCLUDED.enrichment_cost_usd
                """),
                params,
            )


def _save_l2_and_modules(company_id, search_results, synthesis, total_cost):
    """Save research results across all enrichment module tables.

    Writes to:
    - company_enrichment_l2 (backward compat)
    - company_enrichment_profile
    - company_enrichment_signals
    - company_enrichment_market
    - company_enrichment_opportunity
    """
    now = datetime.now(timezone.utc)
    sr = search_results or {}
    syn = synthesis or {}

    quick_wins = syn.get("quick_wins")
    if quick_wins and not isinstance(quick_wins, str):
        quick_wins = json.dumps(quick_wins)

    # --- company_enrichment_l2 (backward compat) ---
    l2_cols = (
        "company_intel",
        "recent_news",
        "ai_opportunities",
        "pain_hypothesis",
        "relevant_case_study",
        "digital_initiatives",
        "leadership_changes",
        "hiring_signals",
        "key_products",
        "customer_segments",
        "competitors",
        "tech_stack",
        "funding_history",
        "eu_grants",
        "leadership_team",
        "ai_hiring",
        "tech_partnerships",
        "certifications",
        "quick_wins",
        "industry_pain_points",
        "cross_functional_pain",
        "adoption_barriers",
        "competitor_ai_moves",
        "expansion",
        "workflow_ai_evidence",
        "revenue_trend",
        "growth_signals",
        "regulatory_pressure",
        "employee_sentiment",
        "pitch_framing",
        "ma_activity",
        "tech_stack_categories",
        "fiscal_year_end",
        "digital_maturity_score",
        "it_spend_indicators",
    )

    l2_params = {
        "cid": str(company_id),
        "company_intel": _to_text(syn.get("executive_brief")),
        "recent_news": _to_text(sr.get("recent_news")),
        "ai_opportunities": _to_text(syn.get("ai_opportunities")),
        "pain_hypothesis": _to_text(syn.get("pain_hypothesis")),
        "relevant_case_study": None,
        "digital_initiatives": _to_text(sr.get("digital_initiatives")),
        "leadership_changes": _to_text(sr.get("leadership_changes")),
        "hiring_signals": _to_text(sr.get("hiring_signals")),
        "key_products": _to_text(syn.get("key_products") or sr.get("key_products")),
        "customer_segments": _to_text(
            syn.get("customer_segments") or sr.get("customer_segments")
        ),
        "competitors": _to_text(syn.get("competitors") or sr.get("competitors")),
        "tech_stack": _to_text(syn.get("tech_stack") or sr.get("tech_stack")),
        "funding_history": _to_text(sr.get("funding")),
        "eu_grants": None,
        "leadership_team": _to_text(sr.get("leadership_team")),
        "ai_hiring": None,
        "tech_partnerships": None,
        "certifications": _to_text(
            syn.get("certifications") or sr.get("certifications")
        ),
        "quick_wins": quick_wins,
        "industry_pain_points": _to_text(syn.get("industry_pain_points")),
        "cross_functional_pain": _to_text(syn.get("cross_functional_pain")),
        "adoption_barriers": _to_text(syn.get("adoption_barriers")),
        "competitor_ai_moves": _to_text(syn.get("competitor_ai_moves")),
        "expansion": _to_text(sr.get("expansion")),
        "workflow_ai_evidence": _to_text(sr.get("digital_initiatives")),
        "revenue_trend": _to_text(sr.get("revenue_trend")),
        "growth_signals": _to_text(sr.get("growth_signals")),
        "regulatory_pressure": None,
        "employee_sentiment": None,
        "pitch_framing": _to_text(syn.get("pitch_framing")),
        "ma_activity": _to_text(sr.get("ma_activity")),
        "tech_stack_categories": None,
        "fiscal_year_end": None,
        "digital_maturity_score": None,
        "it_spend_indicators": None,
        "enriched_at": now,
        "cost": round(total_cost, 4),
    }

    col_list = ", ".join(l2_cols)
    val_list = ", ".join(f":{c}" for c in l2_cols)
    update_list = ", ".join(f"{c} = EXCLUDED.{c}" for c in l2_cols)

    try:
        db.session.execute(
            text(f"""
                INSERT INTO company_enrichment_l2 (
                    company_id, {col_list}, enriched_at, enrichment_cost_usd
                ) VALUES (
                    :cid, {val_list}, :enriched_at, :cost
                )
                ON CONFLICT (company_id) DO UPDATE SET
                    {update_list},
                    enriched_at = EXCLUDED.enriched_at,
                    enrichment_cost_usd = EXCLUDED.enrichment_cost_usd
            """),
            l2_params,
        )
    except Exception:
        db.session.rollback()
        dialect = db.engine.dialect.name
        if dialect == "sqlite":
            db.session.execute(
                text(f"""
                    INSERT OR REPLACE INTO company_enrichment_l2 (
                        company_id, {col_list}, enriched_at, enrichment_cost_usd
                    ) VALUES (
                        :cid, {val_list}, :enriched_at, :cost
                    )
                """),
                l2_params,
            )
        else:
            db.session.execute(
                text(f"""
                    INSERT INTO company_enrichment_l2 (
                        company_id, {col_list}, enriched_at, enrichment_cost_usd
                    ) VALUES (
                        :cid, {val_list}, :enriched_at, :cost
                    )
                    ON CONFLICT (company_id) DO UPDATE SET
                        {update_list},
                        enriched_at = EXCLUDED.enriched_at,
                        enrichment_cost_usd = EXCLUDED.enrichment_cost_usd
                """),
                l2_params,
            )

    # --- company_enrichment_profile ---
    _upsert_module(
        "company_enrichment_profile",
        (
            "company_intel",
            "key_products",
            "customer_segments",
            "competitors",
            "tech_stack",
            "leadership_team",
            "certifications",
            "expansion",
        ),
        {
            "cid": str(company_id),
            "company_intel": _to_text(syn.get("executive_brief")),
            "key_products": _to_text(syn.get("key_products") or sr.get("key_products")),
            "customer_segments": _to_text(
                syn.get("customer_segments") or sr.get("customer_segments")
            ),
            "competitors": _to_text(syn.get("competitors") or sr.get("competitors")),
            "tech_stack": _to_text(syn.get("tech_stack") or sr.get("tech_stack")),
            "leadership_team": _to_text(sr.get("leadership_team")),
            "certifications": _to_text(
                syn.get("certifications") or sr.get("certifications")
            ),
            "expansion": _to_text(sr.get("expansion")),
            "enriched_at": now,
            "cost": round(total_cost * 0.30, 4),
        },
    )

    # --- company_enrichment_signals ---
    _upsert_module(
        "company_enrichment_signals",
        (
            "digital_initiatives",
            "leadership_changes",
            "hiring_signals",
            "ai_hiring",
            "tech_partnerships",
            "competitor_ai_moves",
            "news_confidence",
            "workflow_ai_evidence",
            "regulatory_pressure",
            "employee_sentiment",
            "tech_stack_categories",
            "fiscal_year_end",
            "digital_maturity_score",
            "it_spend_indicators",
        ),
        {
            "cid": str(company_id),
            "digital_initiatives": _to_text(sr.get("digital_initiatives")),
            "leadership_changes": _to_text(sr.get("leadership_changes")),
            "hiring_signals": _to_text(sr.get("hiring_signals")),
            "ai_hiring": None,
            "tech_partnerships": None,
            "competitor_ai_moves": _to_text(syn.get("competitor_ai_moves")),
            "news_confidence": "high" if sr.get("confidence", 0) > 0.7 else "medium",
            "workflow_ai_evidence": _to_text(sr.get("digital_initiatives")),
            "regulatory_pressure": None,
            "employee_sentiment": None,
            "tech_stack_categories": None,
            "fiscal_year_end": None,
            "digital_maturity_score": None,
            "it_spend_indicators": None,
            "enriched_at": now,
            "cost": round(total_cost * 0.20, 4),
        },
    )

    # --- company_enrichment_market ---
    _upsert_module(
        "company_enrichment_market",
        (
            "recent_news",
            "funding_history",
            "eu_grants",
            "media_sentiment",
            "press_releases",
            "thought_leadership",
            "expansion",
            "workflow_ai_evidence",
            "revenue_trend",
            "growth_signals",
            "ma_activity",
        ),
        {
            "cid": str(company_id),
            "recent_news": _to_text(sr.get("recent_news")),
            "funding_history": _to_text(sr.get("funding")),
            "eu_grants": None,
            "media_sentiment": None,
            "press_releases": None,
            "thought_leadership": None,
            "expansion": _to_text(sr.get("expansion")),
            "workflow_ai_evidence": _to_text(sr.get("digital_initiatives")),
            "revenue_trend": _to_text(sr.get("revenue_trend")),
            "growth_signals": _to_text(sr.get("growth_signals")),
            "ma_activity": _to_text(sr.get("ma_activity")),
            "enriched_at": now,
            "cost": round(total_cost * 0.20, 4),
        },
    )

    # --- company_enrichment_opportunity ---
    _upsert_module(
        "company_enrichment_opportunity",
        (
            "pain_hypothesis",
            "relevant_case_study",
            "ai_opportunities",
            "quick_wins",
            "industry_pain_points",
            "cross_functional_pain",
            "adoption_barriers",
            "pitch_framing",
            "competitor_ai_moves",
        ),
        {
            "cid": str(company_id),
            "pain_hypothesis": _to_text(syn.get("pain_hypothesis")),
            "relevant_case_study": None,
            "ai_opportunities": _to_text(syn.get("ai_opportunities")),
            "quick_wins": quick_wins,
            "industry_pain_points": _to_text(syn.get("industry_pain_points")),
            "cross_functional_pain": _to_text(syn.get("cross_functional_pain")),
            "adoption_barriers": _to_text(syn.get("adoption_barriers")),
            "pitch_framing": _to_text(syn.get("pitch_framing")),
            "competitor_ai_moves": _to_text(syn.get("competitor_ai_moves")),
            "enriched_at": now,
            "cost": round(total_cost * 0.30, 4),
        },
    )


def _save_research_asset(
    tenant_id, company_id, total_cost, search_results, synthesis, confidence
):
    """Save a research_asset record (raw data for auditability)."""
    try:
        db.session.execute(
            text("""
                INSERT INTO research_assets (
                    tenant_id, company_id, asset_type, model,
                    cost_usd, raw_data, confidence_score, quality_score
                ) VALUES (
                    :tid, :cid, 'domain_first_research', :model,
                    :cost, :raw, :conf, :quality
                )
            """),
            {
                "tid": str(tenant_id),
                "cid": str(company_id),
                "model": f"{PERPLEXITY_MODEL}+{ANTHROPIC_MODEL}",
                "cost": round(total_cost, 4),
                "raw": json.dumps(
                    {"search": search_results, "synthesis": synthesis},
                    default=str,
                ),
                "conf": confidence or 0.5,
                "quality": 85,
            },
        )
    except Exception as exc:
        logger.debug("Could not save research_asset: %s", exc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


class ResearchService:
    """Pure Python company research — no n8n dependency.

    Domain-first research pipeline:
    1. Fetch & parse company website (homepage + subpages)
    2. Run targeted web search with website context
    3. Synthesize findings into structured enrichment profile
    4. Save to all enrichment tables
    """

    def research_company(
        self,
        company_id,
        tenant_id,
        domain,
        on_progress=None,
    ):
        """Execute the full domain-first research pipeline.

        Args:
            company_id: UUID string of the company
            tenant_id: UUID string of the tenant
            domain: Company domain to research (e.g., "unitedarts.cz")
            on_progress: callback(event_dict) for streaming progress to chat

        Returns:
            dict with:
                success: bool
                company_name: discovered company name
                enrichment_cost_usd: total cost
                steps_completed: list of completed step names
                error: error message if failed
        """
        total_cost = 0.0
        steps_completed = []
        company_name = domain.split(".")[0].capitalize()  # Fallback

        # Step 1: Fetch & parse website
        website_data = fetch_website(domain, on_progress=on_progress)
        if website_data:
            steps_completed.append("website_fetch")
            # Extract company name from website
            homepage = website_data.get("homepage", {})
            title = homepage.get("title", "")
            if title:
                # Clean up title
                for sep in [" - ", " | ", " — ", " – "]:
                    if sep in title:
                        company_name = title.split(sep)[0].strip()
                        break
                else:
                    if len(title) < 60:
                        company_name = title
        else:
            logger.warning(
                "Website fetch failed for %s — continuing with web search only", domain
            )

        website_text = website_data["all_text"] if website_data else ""

        # Step 2: Web search (with website context)
        if on_progress:
            on_progress(
                _make_event(
                    "website_parse",
                    "Content Extraction",
                    domain,
                    "completed",
                    f"Extracted {len(website_text)} chars from {website_data['pages_fetched'] if website_data else 0} pages"
                    if website_data
                    else "No website content — relying on web search",
                    duration_ms=0,
                )
            )

        search_results, search_cost, search_usage = run_web_search(
            domain,
            company_name,
            website_text,
            on_progress=on_progress,
        )
        total_cost += search_cost
        if search_results:
            steps_completed.append("web_search")
            # Update company name from search if found
            if search_results.get("company_name"):
                company_name = search_results["company_name"]

        # Step 3: AI synthesis
        synthesis, synthesis_cost, synthesis_usage = run_synthesis(
            domain,
            company_name,
            website_text,
            search_results,
            on_progress=on_progress,
        )
        total_cost += synthesis_cost
        if synthesis:
            steps_completed.append("ai_synthesis")

        # Step 4: Save to database
        start_save = time.time()
        try:
            # Update company table
            _save_to_company(company_id, search_results, website_data)

            # Set company status
            if synthesis:
                db.session.execute(
                    text("UPDATE companies SET status = :s WHERE id = :cid"),
                    {"s": "enriched_l2", "cid": str(company_id)},
                )
            elif search_results:
                db.session.execute(
                    text("UPDATE companies SET status = :s WHERE id = :cid"),
                    {"s": "triage_passed", "cid": str(company_id)},
                )

            # Determine confidence
            confidence = search_results.get("confidence", 0.5)
            if isinstance(confidence, str):
                try:
                    confidence = float(confidence)
                except ValueError:
                    confidence = 0.5

            # Save L1 enrichment
            _save_l1_enrichment(company_id, search_results, search_cost, confidence)

            # Save L2 and module tables
            _save_l2_and_modules(company_id, search_results, synthesis, total_cost)

            # Save research asset
            _save_research_asset(
                tenant_id,
                company_id,
                total_cost,
                search_results,
                synthesis,
                confidence,
            )

            # Log LLM usage
            if log_llm_usage and search_usage:
                log_llm_usage(
                    tenant_id=tenant_id,
                    operation="domain_research_search",
                    model=search_usage.get("model", PERPLEXITY_MODEL),
                    input_tokens=search_usage.get("input_tokens", 0),
                    output_tokens=search_usage.get("output_tokens", 0),
                    provider="perplexity",
                    metadata={
                        "company_id": str(company_id),
                        "company_name": company_name,
                        "domain": domain,
                    },
                )
            if log_llm_usage and synthesis_usage:
                log_llm_usage(
                    tenant_id=tenant_id,
                    operation="domain_research_synthesis",
                    model=synthesis_usage.get("model", ANTHROPIC_MODEL),
                    input_tokens=synthesis_usage.get("input_tokens", 0),
                    output_tokens=synthesis_usage.get("output_tokens", 0),
                    provider="anthropic",
                    metadata={
                        "company_id": str(company_id),
                        "company_name": company_name,
                        "domain": domain,
                    },
                )

            db.session.commit()
            steps_completed.append("database_save")

        except Exception as exc:
            logger.exception("Failed to save research results for %s", domain)
            db.session.rollback()
            return {
                "success": False,
                "company_name": company_name,
                "enrichment_cost_usd": total_cost,
                "steps_completed": steps_completed,
                "error": str(exc),
            }

        save_ms = int((time.time() - start_save) * 1000)

        if on_progress:
            on_progress(
                _make_event(
                    "database_save",
                    "Save Results",
                    domain,
                    "completed",
                    f"Research complete — {len(steps_completed)} steps, ${total_cost:.4f} cost",
                    detail={
                        "company_name": company_name,
                        "steps": steps_completed,
                        "total_cost_usd": total_cost,
                    },
                    duration_ms=save_ms,
                )
            )

        return {
            "success": True,
            "company_name": company_name,
            "enrichment_cost_usd": total_cost,
            "steps_completed": steps_completed,
        }
