"""Auto-segmentation service for companies.

Uses enrichment data (industry, business model, HQ country) to assign
companies to segments that drive product recommendations and campaign targeting.

Segment definitions:
- obec: municipalities, cultural organizations, city offices
- spolek: clubs, associations, volunteer fire brigades, Sokol/Orel
- rotary_lions: Rotary and Lions clubs
- skola: schools, gymnasia, universities
- agentura: event agencies, production companies
- dach_agentura: agencies headquartered in DE/AT/CH
- other: everything else
"""

from __future__ import annotations

import logging

from ..models import db

logger = logging.getLogger(__name__)

# Segment rules: list of (segment, keywords_in_industry_or_name, country_filter)
# Rules are evaluated top-to-bottom; first match wins.
SEGMENT_RULES: list[dict] = [
    {
        "segment": "rotary_lions",
        "keywords": [
            "rotary",
            "lions",
            "lions club",
            "rotary club",
        ],
        "fields": ["industry", "name"],
    },
    {
        "segment": "dach_agentura",
        "keywords": [
            "agentur",
            "event",
            "production",
            "agency",
            "veranstaltung",
        ],
        "fields": ["industry", "name"],
        "country_filter": ["DE", "AT", "CH", "Germany", "Austria", "Switzerland"],
    },
    {
        "segment": "obec",
        "keywords": [
            "obec",
            "město",
            "městský úřad",
            "kulturní",
            "kulturní dům",
            "kulturní středisko",
            "obecní úřad",
            "městský",
            "municipality",
            "městys",
        ],
        "fields": ["industry", "name", "legal_form"],
    },
    {
        "segment": "spolek",
        "keywords": [
            "spolek",
            "sdružení",
            "hasič",
            "sokol",
            "orel",
            "sbor dobrovolných",
            "svaz",
            "jednota",
            "association",
            "club",
        ],
        "fields": ["industry", "name", "legal_form"],
    },
    {
        "segment": "skola",
        "keywords": [
            "škola",
            "gymnázium",
            "univerzita",
            "vysoká škola",
            "střední škola",
            "základní škola",
            "school",
            "university",
            "akademie",
        ],
        "fields": ["industry", "name"],
    },
    {
        "segment": "agentura",
        "keywords": [
            "agentura",
            "event",
            "production",
            "agency",
            "eventová",
            "produkční",
        ],
        "fields": ["industry", "name"],
    },
]


def _match_keywords(text: str, keywords: list[str]) -> bool:
    """Check if any keyword appears in the text (case-insensitive)."""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def classify_segment(
    *,
    industry: str | None = None,
    name: str | None = None,
    legal_form: str | None = None,
    hq_country: str | None = None,
) -> str:
    """Classify a company into a segment based on its attributes.

    Returns the segment string (e.g. 'obec', 'spolek', 'dach_agentura')
    or 'other' if no rule matches.
    """
    field_map = {
        "industry": industry,
        "name": name,
        "legal_form": legal_form,
    }

    for rule in SEGMENT_RULES:
        # Check country filter first (if present)
        country_filter = rule.get("country_filter")
        if country_filter:
            if not hq_country or not any(
                c.lower() in hq_country.lower() for c in country_filter
            ):
                continue

        # Check keywords against specified fields
        matched = False
        for field_name in rule["fields"]:
            text = field_map.get(field_name)
            if _match_keywords(text, rule["keywords"]):
                matched = True
                break

        if matched:
            return rule["segment"]

    return "other"


def auto_segment_company(company_id: str) -> str | None:
    """Auto-segment a single company based on its enrichment data.

    Returns the assigned segment string, or None if the company was not found.
    Updates the company's segment column in place.
    """
    row = db.session.execute(
        db.text("""
            SELECT industry, name, legal_form, hq_country, segment
            FROM companies WHERE id = :id
        """),
        {"id": company_id},
    ).fetchone()

    if not row:
        return None

    current_industry = row[0]
    current_name = row[1]
    current_legal_form = row[2]
    current_country = row[3]
    existing_segment = row[4]

    segment = classify_segment(
        industry=current_industry,
        name=current_name,
        legal_form=current_legal_form,
        hq_country=current_country,
    )

    # Update only if changed
    if segment != existing_segment:
        db.session.execute(
            db.text("""
                UPDATE companies
                SET segment = :seg, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"seg": segment, "id": company_id},
        )

    return segment


def auto_segment_tenant(tenant_id: str, force: bool = False) -> dict:
    """Run auto-segmentation on all companies in a tenant.

    Args:
        tenant_id: UUID of the tenant.
        force: If True, re-segment all companies. If False, only unsegmented ones.

    Returns:
        Dict with counts by segment and total processed.
    """
    where = "tenant_id = :t"
    if not force:
        where += " AND (segment IS NULL OR segment = '')"

    rows = db.session.execute(
        db.text(f"""
            SELECT id, industry, name, legal_form, hq_country
            FROM companies
            WHERE {where}
        """),
        {"t": tenant_id},
    ).fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        cid = str(row[0])
        segment = classify_segment(
            industry=row[1],
            name=row[2],
            legal_form=row[3],
            hq_country=row[4],
        )
        counts[segment] = counts.get(segment, 0) + 1

        db.session.execute(
            db.text("""
                UPDATE companies
                SET segment = :seg, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"seg": segment, "id": cid},
        )

    db.session.commit()

    return {
        "total": len(rows),
        "by_segment": counts,
    }


def get_recommended_products(tenant_id: str, segment: str) -> list[dict]:
    """Get product recommendations for a segment.

    Returns a list of product dicts with recommendation_type and priority,
    ordered by recommendation_type (entry first) then priority.
    """
    rows = db.session.execute(
        db.text("""
            SELECT p.id, p.name, p.name_en, p.category,
                   p.price_czk, p.price_eur, p.price_unit,
                   p.best_for, p.description_cs,
                   spr.recommendation_type, spr.priority
            FROM segment_product_recommendations spr
            JOIN products p ON spr.product_id = p.id
            WHERE spr.tenant_id = :t AND spr.segment = :seg AND p.is_active = true
            ORDER BY spr.recommendation_type, spr.priority
        """),
        {"t": tenant_id, "seg": segment},
    ).fetchall()

    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "name_en": r[2],
            "category": r[3],
            "price_czk": float(r[4]) if r[4] else None,
            "price_eur": float(r[5]) if r[5] else None,
            "price_unit": r[6],
            "best_for": r[7],
            "description_cs": r[8],
            "recommendation_type": r[9],
            "priority": r[10],
        }
        for r in rows
    ]
