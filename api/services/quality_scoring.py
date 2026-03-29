"""Block-level quality scoring for enrichment data.

Provides a standardized quality assessment that all enrichers call
after processing. Extends the L1 pattern to all blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BlockQualityResult:
    """Standardized quality output for any enrichment block."""

    quality_score: int  # 0-100 composite score
    confidence: Optional[float]  # 0.0-1.0 LLM self-reported
    qc_flags: list[str]  # Issue codes
    field_coverage: float  # 0.0-1.0 ratio of populated fields


# Per-block expected field definitions
BLOCK_FIELD_SPECS: dict[str, list[str]] = {
    "l2_profile": [
        "company_intel",
        "key_products",
        "customer_segments",
        "competitors",
        "tech_stack",
        "leadership_team",
    ],
    "l2_opportunity": [
        "pain_hypothesis",
        "ai_opportunities",
        "quick_wins",
        "industry_pain_points",
    ],
    "signals": [
        "digital_initiatives",
        "leadership_changes",
        "hiring_signals",
        "ai_hiring",
        "tech_partnerships",
        "ai_adoption_level",
        "growth_indicators",
        "job_posting_count",
        "digital_maturity_score",
        "it_spend_indicators",
    ],
    "news": [
        "media_mentions",
        "press_releases",
        "sentiment_score",
        "thought_leadership",
        "news_summary",
    ],
    "registry": [
        "official_name",
        "legal_form",
        "registration_status",
        "registration_id",
        "registered_address",
        "nace_codes",
        "directors",
        "insolvency_flag",
    ],
    "person": [
        "person_summary",
        "role_verified",
        "career_trajectory",
        "authority_score",
        "seniority",
        "department",
        "contact_score",
        "icp_fit",
    ],
    "social": [
        "linkedin_profile_summary",
        "twitter_handle",
        "github_username",
        "speaking_engagements",
        "publications",
        "public_presence_level",
        "thought_leadership",
    ],
    "career": [
        "career_highlights",
        "previous_companies",
        "education",
        "certifications",
        "expertise_areas",
    ],
    "contact_details": [
        "email",
        "phone",
        "linkedin_url",
        "profile_data_confidence",
    ],
}

# Values treated as "not populated"
EMPTY_VALUES = {"unverified", "unknown", "null", "none", "n/a", ""}


def compute_field_coverage(data: dict, block_code: str) -> float:
    """Compute field coverage ratio for a block.

    Args:
        data: Dict of field_name -> value (from DB row or parsed response)
        block_code: Key into BLOCK_FIELD_SPECS

    Returns:
        Float 0.0-1.0 representing populated/total ratio.
    """
    fields = BLOCK_FIELD_SPECS.get(block_code, [])
    if not fields:
        return 0.0

    populated = 0
    for f in fields:
        val = data.get(f)
        if val is None:
            continue
        if isinstance(val, str) and val.strip().lower() in EMPTY_VALUES:
            continue
        if isinstance(val, (list, dict)) and len(val) == 0:
            continue
        populated += 1

    return populated / len(fields)


def compute_quality_score(
    field_coverage: float,
    confidence: Optional[float],
    qc_flags: list[str],
) -> int:
    """Compute composite quality score (0-100).

    Formula: 60% field_coverage + 30% confidence + 10% flag penalty
    """
    fc_component = field_coverage * 100  # 0-100
    conf_component = (confidence if confidence is not None else 0.5) * 100
    flag_penalty = max(0, 100 - len(qc_flags) * 20)

    score = round(0.60 * fc_component + 0.30 * conf_component + 0.10 * flag_penalty)
    return max(0, min(100, score))


def assess_block_quality(
    data: dict,
    block_code: str,
    confidence: Optional[float] = None,
    extra_flags: Optional[list[str]] = None,
) -> BlockQualityResult:
    """Full quality assessment for an enrichment block.

    Call this at the end of each enricher, passing the enriched data dict,
    the block code, the LLM-reported confidence, and any block-specific
    QC flags detected during validation.

    Returns a BlockQualityResult ready to persist.
    """
    fc = compute_field_coverage(data, block_code)
    flags = list(extra_flags or [])

    # Universal flags
    if fc < 0.4:
        flags.append("incomplete_research")
    if confidence is not None and confidence < 0.4:
        flags.append("low_confidence")

    # De-duplicate preserving order
    flags = list(dict.fromkeys(flags))

    score = compute_quality_score(fc, confidence, flags)

    return BlockQualityResult(
        quality_score=score,
        confidence=confidence,
        qc_flags=flags,
        field_coverage=fc,
    )


def parse_confidence(value) -> Optional[float]:
    """Parse a confidence value from LLM response.

    Handles string, int, float. Returns float 0.0-1.0 or None.
    """
    if value is None:
        return None
    try:
        conf = float(value)
        # If value looks like a percentage (> 1.0), convert to 0-1 range
        # Only do this for values that are plausibly percentages (> 1.0)
        if conf > 1.0:
            conf = conf / 100.0
        # Clamp to valid range
        return max(0.0, min(1.0, conf))
    except (ValueError, TypeError):
        return None
