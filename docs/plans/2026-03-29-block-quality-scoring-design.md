# Per-Block Enrichment Quality Scoring

> Design document for extending quality scoring from L1-only to all 11 enrichment blocks.

**Date:** 2026-03-29
**Status:** Draft
**Author:** Claude (design), Michal (review)

---

## 1. Problem Statement

Today, only L1 (Company Profile) enrichment has quality scoring. The `company_enrichment_l1` table stores `quality_score` (0-100), `confidence` (0.0-1.0), and `qc_flags` (JSONB array of issue codes). The remaining 10 enrichment blocks — Deep Research, Strategic Signals, Legal & Registry, News & PR, Role & Employment, Social & Online, Career History, Contact Details, Triage, and Quality Check — have no quality assessment at all.

This means:

- **No visibility into data reliability** — a company with sparse L2 research looks the same as one with rich, verified intelligence.
- **No automated quality gates** — the Triage gate and terminal QC stage cannot make decisions based on upstream data quality.
- **No re-enrichment prioritization** — there is no signal for which entities would benefit most from re-enrichment with a boosted model.
- **No aggregate data health view** — namespace admins cannot see overall enrichment quality across their pipeline.

## 2. Design Goals

1. **Extend L1 pattern to all blocks** — every enrichment table gets `quality_score`, `confidence`, and `qc_flags` columns using the same semantics as L1.
2. **Inline scoring** — quality assessment happens inside each enricher's existing LLM call (no extra API calls, no extra cost).
3. **Block-specific field definitions** — each block defines its own "expected fields" list for field coverage calculation.
4. **Unified API** — a single endpoint returns per-block quality for a company or contact, enabling the frontend to show quality badges on every stage card.
5. **Backfill-safe** — existing enrichment data can be scored retroactively with a migration script (field-coverage only; LLM confidence requires re-enrichment).
6. **LangGraph-aware** — quality scores flow through the enrichment subgraph state, enabling quality-aware routing (e.g., skip re-enrichment if quality is already high).

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Enricher Service                       │
│                                                             │
│  1. Call Perplexity/LLM with quality self-assessment prompt │
│  2. Parse response + extract confidence                     │
│  3. Run field coverage check (deterministic)                │
│  4. Run QC flag validation (deterministic + LLM-reported)   │
│  5. Compute composite quality_score                         │
│  6. UPSERT enrichment row WITH quality columns              │
│                                                             │
│  Returns: { enrichment_cost_usd, qc_flags, quality_score }  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    PostgreSQL Tables                         │
│                                                             │
│  company_enrichment_l1      ✓ already has quality columns   │
│  company_enrichment_profile + quality_score, confidence,    │
│  company_enrichment_signals   qc_flags (new columns)        │
│  company_enrichment_market                                  │
│  company_enrichment_opportunity                             │
│  company_news                                               │
│  company_legal_profile      (has credibility_score already) │
│  contact_enrichment                                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              API: GET /api/companies/:id/quality             │
│              API: GET /api/contacts/:id/quality              │
│                                                             │
│  Returns per-block quality breakdown:                        │
│  { "l1": { score: 85, confidence: 0.8, flags: [...] },     │
│    "signals": { score: 72, confidence: 0.7, flags: [...] }, │
│    ... }                                                     │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│            Frontend: Quality Badges on StageCard             │
│                                                             │
│  - Color-coded dot (green/amber/red) per block              │
│  - Tooltip with score, confidence, and flag details          │
│  - Aggregate quality bar in CompletionPanel                  │
└─────────────────────────────────────────────────────────────┘
```

## 4. Quality Scoring Model

### 4.1 Composite Formula

Every block produces a `quality_score` (integer 0-100) computed as:

```
quality_score = round(
    0.60 * field_coverage       # 0-100: non-null expected fields / total expected fields
  + 0.30 * confidence * 100     # 0-100: LLM self-reported confidence scaled
  + 0.10 * flag_penalty_score   # 0-100: 100 minus penalty from QC flags
)
```

Where:
- **`field_coverage`** = `(count of non-null, non-empty expected fields) / (total expected fields) * 100`
- **`confidence`** = LLM self-reported confidence (0.0-1.0), parsed via `_parse_confidence()` from L1. Falls back to 0.5 if not reported.
- **`flag_penalty_score`** = `max(0, 100 - len(qc_flags) * 20)` — each QC flag deducts 20 points from the flag component.

This weights field completeness highest (60%), LLM judgment second (30%), and penalizes flagged issues (10%).

### 4.2 Quality Tiers

| Score Range | Tier | Color | Meaning |
|-------------|------|-------|---------|
| 80-100 | High | Green (`#06d6a0`) | Rich, verified data — ready for outreach |
| 50-79 | Medium | Amber (`#e09f3e`) | Usable but incomplete — re-enrichment recommended |
| 0-49 | Low | Red (`#ef476f`) | Sparse or flagged — manual review or re-enrichment needed |

### 4.3 Per-Block Expected Fields

Each block defines which fields count toward `field_coverage`. Only non-null, non-empty values (excluding `"unverified"`, `"unknown"`, `"null"`, `"none"`, `"n/a"`) count as populated.

#### Company Profile (L1) — `company_enrichment_l1`
Already scored. No changes needed. Expected fields from `_validate_research`:
`summary`, `hq`, `industry`, `employees`, `revenue_eur_m`, `b2b`, `business_type`, `ownership`, `markets`, `competitors`

#### Deep Research (L2) — `company_enrichment_profile` + `company_enrichment_opportunity`
Expected fields (profile): `company_intel`, `key_products`, `customer_segments`, `competitors`, `tech_stack`, `leadership_team`
Expected fields (opportunity): `pain_hypothesis`, `ai_opportunities`, `quick_wins`, `industry_pain_points`
Total: 10 fields across both tables.

#### Strategic Signals — `company_enrichment_signals`
Expected fields: `digital_initiatives`, `leadership_changes`, `hiring_signals`, `ai_hiring`, `tech_partnerships`, `ai_adoption_level`, `growth_indicators`, `job_posting_count`, `digital_maturity_score`, `it_spend_indicators`
Total: 10 fields.

#### Legal & Registry — `company_legal_profile`
Expected fields: `official_name`, `legal_form`, `registration_status`, `registration_id`, `registered_address`, `nace_codes`, `directors`, `insolvency_flag`
Total: 8 fields.
Note: This block already has `credibility_score` and `match_confidence`. The new `quality_score` supplements these — `credibility_score` measures the company's legal credibility, while `quality_score` measures the enrichment data quality itself.

#### News & PR — `company_news`
Expected fields: `media_mentions` (non-empty array), `press_releases` (non-empty array), `sentiment_score`, `thought_leadership`, `news_summary`
Total: 5 fields.

#### Role & Employment (Person) — `contact_enrichment`
Expected fields: `person_summary`, `role_verified`, `career_trajectory`, `authority_score`, `seniority`, `department`, `contact_score`, `icp_fit`
Total: 8 fields.

#### Social & Online — `contact_enrichment`
Expected fields: `linkedin_profile_summary`, `twitter_handle`, `github_username`, `speaking_engagements`, `publications`, `public_presence_level`, `thought_leadership`
Total: 7 fields.

#### Career History — `contact_enrichment`
Expected fields: `career_highlights`, `previous_companies` (non-empty array), `education`, `certifications`, `expertise_areas` (non-empty array)
Total: 5 fields.

#### Contact Details — `contact_enrichment`
Expected fields: checked via the `contacts` table directly — `email`, `phone`, `linkedin_url`, plus `contact_enrichment.profile_data_confidence`
Total: 4 fields.

### 4.4 QC Flag Taxonomy

Flags are strings stored in the `qc_flags` JSONB array. Blocks share a common taxonomy, with block-specific flags as needed.

#### Universal Flags (any block)
| Flag | Trigger | Severity |
|------|---------|----------|
| `low_confidence` | LLM confidence < 0.4 | Medium |
| `incomplete_research` | field_coverage < 40% | High |
| `stale_data` | `enriched_at` older than 90 days | Low |
| `api_error` | Enricher encountered an error during processing | High |
| `parse_error` | LLM response could not be parsed as JSON | High |

#### L1-Specific Flags (existing, unchanged)
| Flag | Trigger |
|------|---------|
| `name_mismatch` | Research company name similarity < 0.6 |
| `revenue_implausible` | Revenue > 50B EUR or revenue/employee > 500K |
| `employees_implausible` | Headcount < 0 or > 500K |
| `b2b_unclear` | B2B field is null |
| `summary_too_short` | Summary < 30 characters |

#### Signals-Specific Flags
| Flag | Trigger |
|------|---------|
| `no_hiring_data` | `hiring_signals` and `job_posting_count` both null |
| `no_ai_signals` | `ai_hiring`, `ai_adoption_level`, `workflow_ai_evidence` all null |
| `generic_signals` | LLM self-reports low specificity (via confidence < 0.5 on signals) |

#### News-Specific Flags
| Flag | Trigger |
|------|---------|
| `no_media_coverage` | `media_mentions` is empty array |
| `stale_news` | Most recent media mention > 6 months old |
| `sentiment_missing` | `sentiment_score` is null despite media mentions existing |

#### Registry-Specific Flags
| Flag | Trigger |
|------|---------|
| `dissolved_entity` | `registration_status` contains "dissolved" or similar |
| `insolvency_detected` | `insolvency_flag` is true |
| `low_match_confidence` | `match_confidence` < 0.6 |

#### Contact-Specific Flags (shared across person/social/career/contact_details)
| Flag | Trigger |
|------|---------|
| `role_mismatch` | `role_mismatch_flag` is set |
| `no_linkedin` | `linkedin_profile_summary` is null and contact has no `linkedin_url` |
| `no_career_history` | `previous_companies` is empty and `career_highlights` is null |
| `low_authority` | `authority_score` < 30 |
| `email_unverified` | Contact has email but no verification status |

## 5. DB Schema Changes

### 5.1 Migration: Add Quality Columns

Migration `053_block_quality_scores.sql`:

```sql
-- Add quality scoring columns to enrichment tables that don't have them.
-- L1 already has these columns — skip it.

-- Deep Research: profile table
ALTER TABLE company_enrichment_profile
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- Deep Research: opportunity table
ALTER TABLE company_enrichment_opportunity
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- Strategic Signals
ALTER TABLE company_enrichment_signals
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- Market (L2 sub-table)
ALTER TABLE company_enrichment_market
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- News & PR
ALTER TABLE company_news
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- Legal & Registry (already has credibility_score and match_confidence;
-- adding quality_score and qc_flags for the enrichment quality layer)
ALTER TABLE company_legal_profile
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;
-- Note: company_legal_profile already has match_confidence (numeric(3,2))
-- which serves as the confidence proxy for registry data.

-- Contact Enrichment (single table for all contact blocks)
ALTER TABLE contact_enrichment
  ADD COLUMN IF NOT EXISTS quality_score smallint,
  ADD COLUMN IF NOT EXISTS confidence numeric(3,2),
  ADD COLUMN IF NOT EXISTS qc_flags jsonb DEFAULT '[]'::jsonb;

-- Index for quality-based queries (find low-quality enrichments for re-enrichment)
CREATE INDEX IF NOT EXISTS idx_company_enrichment_profile_quality
  ON company_enrichment_profile (quality_score) WHERE quality_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_company_enrichment_signals_quality
  ON company_enrichment_signals (quality_score) WHERE quality_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_company_news_quality
  ON company_news (quality_score) WHERE quality_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_company_legal_profile_quality
  ON company_legal_profile (quality_score) WHERE quality_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contact_enrichment_quality
  ON contact_enrichment (quality_score) WHERE quality_score IS NOT NULL;
```

### 5.2 SQLAlchemy Model Changes

Add columns to each model class in `api/models.py`:

```python
# CompanyEnrichmentProfile, CompanyEnrichmentOpportunity,
# CompanyEnrichmentSignals, CompanyEnrichmentMarket, CompanyNews
quality_score = db.Column(db.SmallInteger)
confidence = db.Column(db.Numeric(3, 2))
qc_flags = db.Column(JSONB, server_default=db.text("'[]'::jsonb"))

# ContactEnrichment
quality_score = db.Column(db.SmallInteger)
confidence = db.Column(db.Numeric(3, 2))
qc_flags = db.Column(JSONB, server_default=db.text("'[]'::jsonb"))

# CompanyLegalProfile — only quality_score and qc_flags
# (match_confidence already exists as the confidence proxy)
quality_score = db.Column(db.SmallInteger)
qc_flags = db.Column(JSONB, server_default=db.text("'[]'::jsonb"))
```

## 6. Backend Changes

### 6.1 Shared Quality Module: `api/services/quality_scoring.py`

A new module containing the shared quality logic, used by all enrichers.

```python
"""Block-level quality scoring for enrichment data.

Provides a standardized quality assessment that all enrichers call
after processing. Extends the L1 pattern to all blocks.
"""

from dataclasses import dataclass, field


@dataclass
class BlockQualityResult:
    """Standardized quality output for any enrichment block."""
    quality_score: int          # 0-100 composite score
    confidence: float | None    # 0.0-1.0 LLM self-reported
    qc_flags: list[str]         # Issue codes
    field_coverage: float       # 0.0-1.0 ratio of populated fields


# Per-block expected field definitions
BLOCK_FIELD_SPECS: dict[str, list[str]] = {
    "l2_profile": [
        "company_intel", "key_products", "customer_segments",
        "competitors", "tech_stack", "leadership_team",
    ],
    "l2_opportunity": [
        "pain_hypothesis", "ai_opportunities", "quick_wins",
        "industry_pain_points",
    ],
    "signals": [
        "digital_initiatives", "leadership_changes", "hiring_signals",
        "ai_hiring", "tech_partnerships", "ai_adoption_level",
        "growth_indicators", "job_posting_count",
        "digital_maturity_score", "it_spend_indicators",
    ],
    "news": [
        "media_mentions", "press_releases", "sentiment_score",
        "thought_leadership", "news_summary",
    ],
    "registry": [
        "official_name", "legal_form", "registration_status",
        "registration_id", "registered_address", "nace_codes",
        "directors", "insolvency_flag",
    ],
    "person": [
        "person_summary", "role_verified", "career_trajectory",
        "authority_score", "seniority", "department",
        "contact_score", "icp_fit",
    ],
    "social": [
        "linkedin_profile_summary", "twitter_handle", "github_username",
        "speaking_engagements", "publications",
        "public_presence_level", "thought_leadership",
    ],
    "career": [
        "career_highlights", "previous_companies", "education",
        "certifications", "expertise_areas",
    ],
    "contact_details": [
        "email", "phone", "linkedin_url",
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
    confidence: float | None,
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
    confidence: float | None = None,
    extra_flags: list[str] | None = None,
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

    # De-duplicate
    flags = list(dict.fromkeys(flags))

    score = compute_quality_score(fc, confidence, flags)

    return BlockQualityResult(
        quality_score=score,
        confidence=confidence,
        qc_flags=flags,
        field_coverage=fc,
    )
```

### 6.2 Enricher Modifications

Each enricher gets two changes:

**A. Add confidence to the LLM prompt.** Append to the system prompt:

```
Also include a "confidence" field (0.0 to 1.0) indicating your overall confidence
in the accuracy and completeness of the data above.
```

Most enrichers already ask for structured JSON output. Adding one more field is trivial and adds zero cost (1 extra output token).

**B. Call `assess_block_quality()` before UPSERT.** Example for signals enricher:

```python
from .quality_scoring import assess_block_quality

# After parsing response and before UPSERT:
block_flags = []
if not parsed.get("hiring_signals") and not parsed.get("job_posting_count"):
    block_flags.append("no_hiring_data")
if not parsed.get("ai_hiring") and not parsed.get("ai_adoption_level"):
    block_flags.append("no_ai_signals")

quality = assess_block_quality(
    data=parsed,
    block_code="signals",
    confidence=_parse_confidence(parsed.get("confidence")),
    extra_flags=block_flags,
)

# Include in UPSERT:
# quality_score = quality.quality_score
# confidence = quality.confidence
# qc_flags = json.dumps(quality.qc_flags)
```

**C. Update return value.** Each enricher already returns `{"enrichment_cost_usd": ...}`. Extend to:

```python
return {
    "enrichment_cost_usd": cost_float,
    "qc_flags": quality.qc_flags,
    "quality_score": quality.quality_score,
}
```

### 6.3 L1 Enricher — Minimal Changes

L1 already has quality scoring via `_validate_research()` and manual `quality_score` calculation. To align with the shared module:

1. Keep `_validate_research()` as-is (its flag logic is L1-specific and well-tested).
2. Replace the manual `quality_score = max(0, 100 - len(qc_flags) * 15)` with `compute_quality_score(fc, confidence, qc_flags)` for consistency.
3. This is a **low-priority** alignment change — L1 works fine as-is.

### 6.4 Registry Enricher — Special Case

The registry enrichers (`ares.py`, `brreg.py`, `prh.py`, `recherche.py`) call external government APIs, not LLMs. They have no LLM confidence. For these:

- `confidence` = `match_confidence` (already computed by the registry matching logic)
- `field_coverage` = standard field coverage calculation against the `registry` field spec
- Block-specific flags: `dissolved_entity`, `insolvency_detected`, `low_match_confidence`
- The existing `credibility_score` remains separate (it measures the company, not the data).

### 6.5 Contact Enrichment — Per-Block Scoring in Shared Table

The `contact_enrichment` table stores data for four blocks (person, social, career, contact_details), but has only one set of quality columns. Design options:

**Chosen approach: last-write-wins with block-level JSONB.**

Add a `block_quality` JSONB column to `contact_enrichment`:

```sql
ALTER TABLE contact_enrichment
  ADD COLUMN IF NOT EXISTS block_quality jsonb DEFAULT '{}'::jsonb;
```

Structure:
```json
{
  "person": { "score": 82, "confidence": 0.8, "flags": [], "field_coverage": 0.75 },
  "social": { "score": 65, "confidence": 0.7, "flags": ["no_linkedin"], "field_coverage": 0.57 },
  "career": { "score": 90, "confidence": 0.9, "flags": [], "field_coverage": 1.0 },
  "contact_details": { "score": 50, "confidence": null, "flags": ["email_unverified"], "field_coverage": 0.5 }
}
```

The top-level `quality_score`, `confidence`, `qc_flags` columns hold the **aggregate** (average of block scores, union of flags). The `block_quality` JSONB holds per-block detail.

Each contact enricher updates its block in `block_quality` and recomputes the aggregate.

### 6.6 New API Endpoint

**`GET /api/companies/<company_id>/quality`**

Returns per-block quality scores for all enrichment data on a company.

```json
{
  "company_id": "uuid",
  "blocks": {
    "l1": {
      "quality_score": 85,
      "confidence": 0.8,
      "qc_flags": [],
      "field_coverage": 0.9,
      "enriched_at": "2026-03-15T10:30:00Z"
    },
    "l2": {
      "quality_score": 72,
      "confidence": 0.7,
      "qc_flags": ["incomplete_research"],
      "field_coverage": 0.6,
      "enriched_at": "2026-03-16T14:00:00Z"
    },
    "signals": null,
    "registry": { ... },
    "news": { ... }
  },
  "aggregate": {
    "quality_score": 78,
    "blocks_enriched": 4,
    "blocks_total": 5,
    "lowest_block": "l2",
    "flags_total": 1
  }
}
```

`null` means the block has not been enriched yet.

**`GET /api/contacts/<contact_id>/quality`**

Same pattern for contact blocks:

```json
{
  "contact_id": "uuid",
  "blocks": {
    "person": { "quality_score": 82, ... },
    "social": { "quality_score": 65, ... },
    "career": null,
    "contact_details": { "quality_score": 50, ... }
  },
  "aggregate": {
    "quality_score": 66,
    "blocks_enriched": 3,
    "blocks_total": 4,
    "lowest_block": "contact_details",
    "flags_total": 2
  }
}
```

**Implementation:** Single SQL query per entity type, JOINing across enrichment tables and extracting quality columns. Avoid N+1 — one round-trip.

```python
@company_bp.route("/api/companies/<company_id>/quality")
@require_auth
def get_company_quality(company_id):
    """Return per-block enrichment quality scores for a company."""
    row = db.session.execute(text("""
        SELECT
            l1.quality_score, l1.confidence, l1.qc_flags, l1.enriched_at,
            ep.quality_score, ep.confidence, ep.qc_flags, ep.enriched_at,
            eo.quality_score, eo.confidence, eo.qc_flags, eo.enriched_at,
            es.quality_score, es.confidence, es.qc_flags, es.enriched_at,
            cn.quality_score, cn.confidence, cn.qc_flags, cn.enriched_at,
            cl.quality_score, cl.match_confidence, cl.qc_flags, cl.enriched_at
        FROM companies c
        LEFT JOIN company_enrichment_l1 l1 ON l1.company_id = c.id
        LEFT JOIN company_enrichment_profile ep ON ep.company_id = c.id
        LEFT JOIN company_enrichment_opportunity eo ON eo.company_id = c.id
        LEFT JOIN company_enrichment_signals es ON es.company_id = c.id
        LEFT JOIN company_news cn ON cn.company_id = c.id
        LEFT JOIN company_legal_profile cl ON cl.company_id = c.id
        WHERE c.id = :company_id AND c.tenant_id = :tenant_id
    """), {"company_id": company_id, "tenant_id": g.tenant_id}).fetchone()
    # ... format and return
```

## 7. LangGraph Integration

### 7.1 State Extension

Add an `enrichment_quality` field to `AgentState`:

```python
class AgentState(TypedDict):
    # ... existing fields ...
    enrichment_quality: Optional[dict[str, Any]]
    # Structure: { "l1": { "score": 85, ... }, "signals": { "score": 72, ... } }
```

### 7.2 Quality Accumulation in Enrichment Subgraph

After each enrichment tool executes, the tool result includes quality data. The enrichment agent node accumulates this in state:

```python
# In enrichment_tools_node, after successful tool execution:
if "quality_score" in result:
    block_code = _tool_to_block(tool_name)  # e.g., "enrich_company_signals" -> "signals"
    current_quality = dict(state.get("enrichment_quality", {}) or {})
    current_quality[block_code] = {
        "score": result["quality_score"],
        "flags": result.get("qc_flags", []),
    }
    # Return as part of state update
```

### 7.3 Quality-Aware Routing (Future)

With quality in the graph state, the enrichment agent can make smart decisions:

- **Skip re-enrichment** if an existing block has `quality_score >= 80` and `enriched_at` < 30 days ago.
- **Recommend boost** if a block has `quality_score < 50` — suggest re-enrichment with a higher-quality model.
- **Prioritize blocks** — enrich the lowest-quality blocks first when budget is constrained.

This is not implemented in v1 but the state structure supports it.

### 7.4 Tool Registry Updates

Each enrichment tool in `api/services/tool_registry.py` already returns a result dict. Extend the return value to include quality data:

```python
# Existing pattern:
return {"status": "success", "enrichment_cost_usd": 0.05, ...}

# Extended:
return {
    "status": "success",
    "enrichment_cost_usd": 0.05,
    "quality_score": 72,
    "qc_flags": ["no_hiring_data"],
    ...
}
```

## 8. Frontend Changes

### 8.1 Quality Badge on StageCard

Add a small quality indicator to each `StageCard` in the `completed` state. The badge appears in the top-right corner of the card.

**New component: `QualityBadge.tsx`**

```tsx
interface QualityBadgeProps {
  score: number | null    // 0-100 or null (not enriched)
  flags: string[]
}

function QualityBadge({ score, flags }: QualityBadgeProps) {
  if (score === null) return null

  const color = score >= 80 ? '#06d6a0'
              : score >= 50 ? '#e09f3e'
              : '#ef476f'

  return (
    <div className="quality-badge" title={`Quality: ${score}/100${flags.length ? ` — ${flags.join(', ')}` : ''}`}>
      <span className="quality-dot" style={{ background: color }} />
      <span className="quality-score">{score}</span>
    </div>
  )
}
```

### 8.2 StageCard Integration

In `StageCard.tsx`, when `mode === 'completed'` and the stage has been enriched:

```tsx
// Add to StageCardProps:
quality?: { score: number; confidence: number | null; flags: string[] } | null

// Render in completed mode header:
{mode === 'completed' && quality && (
  <QualityBadge score={quality.score} flags={quality.flags} />
)}
```

### 8.3 Quality Data Fetching

**New hook: `useEnrichQuality.ts`**

After an enrichment pipeline completes (`dagMode === 'completed'`), fetch quality data for all enriched entities. Since the pipeline may have enriched many companies, fetch aggregate quality across the tag:

```tsx
// GET /api/enrichment/quality-summary?tag=<tag_name>
// Returns aggregate quality per block across all companies in the tag
```

Alternatively, the `CompletionPanel` can show a quality summary table:

| Block | Avg Score | High (80+) | Medium (50-79) | Low (<50) |
|-------|-----------|------------|-----------------|-----------|
| L1 | 82 | 145 | 12 | 3 |
| Signals | 71 | 98 | 47 | 15 |
| ... | ... | ... | ... | ... |

### 8.4 Company Detail Page

On the company detail page (if it exists), show per-block quality in the enrichment tab. Each enrichment section gets a quality pill showing the score and expandable flag details.

## 9. Migration Plan

### Phase 1: Schema (non-breaking)
1. Run migration `053_block_quality_scores.sql` — adds nullable columns, zero risk.
2. Update SQLAlchemy models in `api/models.py`.
3. All existing data keeps `quality_score = NULL` (treated as "not scored").

### Phase 2: Backend Scoring Logic
1. Create `api/services/quality_scoring.py` with shared module.
2. Update each enricher to call `assess_block_quality()` and persist results.
3. New enrichments get quality scores; old ones remain NULL.

### Phase 3: Backfill Script
1. Create `scripts/backfill_quality_scores.py` — reads existing enrichment rows, computes field_coverage and flag-based quality.
2. Backfilled scores have `confidence = NULL` (since we cannot retroactively get LLM confidence).
3. Quality formula degrades gracefully: with `confidence = NULL`, defaults to 0.5, so formula becomes `60% field_coverage + 15% + 10% flag_penalty`.
4. Run on staging first, verify, then run on production.

### Phase 4: API + Frontend
1. Add quality API endpoints.
2. Add `QualityBadge` component and wire into `StageCard`.
3. Add quality summary to `CompletionPanel`.

### Phase 5: LangGraph Integration
1. Add `enrichment_quality` to `AgentState`.
2. Wire tool results to accumulate quality in state.
3. (Future) Add quality-aware routing logic.

## 10. Testing Strategy

### Unit Tests

**`tests/unit/test_quality_scoring.py`** — test the shared module:
- `test_field_coverage_all_populated` — 100% coverage returns 1.0
- `test_field_coverage_empty_values_excluded` — "unverified", null, empty string don't count
- `test_field_coverage_jsonb_empty_array` — empty `[]` counts as not populated
- `test_compute_quality_score_perfect` — all components maxed = 100
- `test_compute_quality_score_with_flags` — flags reduce score correctly
- `test_compute_quality_score_no_confidence` — defaults to 0.5
- `test_assess_block_quality_adds_universal_flags` — low coverage triggers `incomplete_research`
- `test_assess_block_quality_deduplicates_flags` — no duplicate flags

**Per-enricher tests** — verify quality is computed and persisted:
- `test_signals_enricher_returns_quality_score`
- `test_news_enricher_flags_no_media_coverage`
- `test_registry_enricher_flags_dissolved_entity`
- `test_contact_enricher_block_quality_jsonb`

### Integration Tests

- Test quality API endpoint returns correct per-block breakdown.
- Test that backfill script produces valid scores for existing data.
- Test quality columns are included in enrichment UPSERT.

### Manual Verification

1. Run enrichment on a test company.
2. Query quality API endpoint.
3. Verify scores match expected field coverage.
4. Check frontend badges render correctly.

---

## Appendix A: Enricher File Map

| Block | Enricher File | DB Table(s) | Block Code |
|-------|--------------|-------------|------------|
| Company Profile | `l1_enricher.py` | `company_enrichment_l1` | `l1` |
| Deep Research | `l2_enricher.py` | `company_enrichment_profile`, `company_enrichment_opportunity` | `l2_profile`, `l2_opportunity` |
| Strategic Signals | `signals_enricher.py` | `company_enrichment_signals` | `signals` |
| News & PR | `news_enricher.py` | `company_news` | `news` |
| Legal & Registry | `registries/*.py` | `company_legal_profile` | `registry` |
| Role & Employment | `person_enricher.py` | `contact_enrichment` | `person` |
| Social & Online | `social_enricher.py` | `contact_enrichment` | `social` |
| Career History | `career_enricher.py` | `contact_enrichment` | `career` |
| Contact Details | `contact_details_enricher.py` | `contact_enrichment` | `contact_details` |

## Appendix B: Quality Score Examples

**High quality signals enrichment (score: 88):**
- Field coverage: 9/10 = 0.90 (missing only `it_spend_indicators`)
- Confidence: 0.85 (LLM reported)
- QC flags: none
- Score: `0.60 * 90 + 0.30 * 85 + 0.10 * 100 = 54 + 25.5 + 10 = 90` (rounded)

**Medium quality news enrichment (score: 58):**
- Field coverage: 3/5 = 0.60 (missing `sentiment_score`, `thought_leadership`)
- Confidence: 0.6 (LLM reported)
- QC flags: `["sentiment_missing"]`
- Score: `0.60 * 60 + 0.30 * 60 + 0.10 * 80 = 36 + 18 + 8 = 62`

**Low quality career enrichment (score: 32):**
- Field coverage: 1/5 = 0.20 (only `career_highlights` populated)
- Confidence: 0.3 (LLM reported low confidence)
- QC flags: `["incomplete_research", "low_confidence", "no_career_history"]`
- Score: `0.60 * 20 + 0.30 * 30 + 0.10 * 40 = 12 + 9 + 4 = 25`
