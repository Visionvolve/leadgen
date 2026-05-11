import json
import math
import re

from flask import Blueprint, g, jsonify, request

from ..auth import require_auth, require_role, resolve_tenant
from ..display import (
    display_business_model,
    display_business_type,
    display_buying_stage,
    display_cohort,
    display_company_size,
    display_confidence,
    display_crm_status,
    display_engagement_status,
    display_enrichment_stage,
    display_geo_region,
    display_icp_fit,
    display_industry,
    display_industry_category,
    display_ownership_type,
    display_revenue_range,
    display_status,
    display_tier,
)
from ..models import db
from ..services.contact_helpers import write_field_change

companies_bp = Blueprint("companies", __name__)


def _add_multi_filter(where, params, param_name, column, request_obj):
    """Add a multi-value include/exclude filter to the WHERE clause."""
    raw = request_obj.args.get(param_name, "").strip()
    if not raw:
        return
    values = [v.strip() for v in raw.split(",") if v.strip()]
    if not values:
        return
    exclude = (
        request_obj.args.get(f"{param_name}_exclude", "").strip().lower() == "true"
    )
    placeholders = ", ".join(f":{param_name}_{i}" for i in range(len(values)))
    for i, v in enumerate(values):
        params[f"{param_name}_{i}"] = v
    if exclude:
        where.append(f"({column} IS NULL OR {column} NOT IN ({placeholders}))")
    else:
        where.append(f"{column} IN ({placeholders})")


def _iso(v):
    """Safely convert a datetime or string to ISO format."""
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _parse_jsonb(v):
    """Parse a JSONB value that may be a string (SQLite) or dict (Postgres)."""
    if v is None:
        return {}
    if isinstance(v, str):
        return json.loads(v) if v else {}
    return v


# Stage progression order for derived_stage computation
_STAGE_ORDER = ["l1", "triage", "l2", "person", "generate", "review"]
_STAGE_LABELS = {
    "l1": "Classified",
    "triage": "Qualified",
    "l2": "Researched",
    "person": "Contacts Ready",
    "generate": "Messages Generated",
    "review": "Ready for Outreach",
}


def _derive_stage(completions, status=None):
    """Compute derived stage label from entity_stage_completions.

    Returns dict with label and stage key, or None if no completions.
    """
    if not completions:
        return {"label": "New", "stage": None}

    completed = {c["stage"] for c in completions if c["status"] == "completed"}

    # Walk stage order in reverse to find the latest completed
    for stage in reversed(_STAGE_ORDER):
        if stage in completed:
            return {"label": _STAGE_LABELS[stage], "stage": stage}

    # Has completions but none in our stage order (e.g., all failed)
    return {"label": "New", "stage": None}


def _compute_enrichment_stage(status, has_l1, has_l2, has_person_enrichment):
    """Compute enrichment_stage from company status and enrichment data.

    Returns the stage key (e.g. 'imported', 'researched', 'qualified', etc.).
    """
    if status and ("failed" in status or "error" in status):
        return "failed"
    if status == "triage_disqualified":
        return "disqualified"
    if status == "enriched_l2" and has_person_enrichment:
        return "contacts_ready"
    if status in ("enriched_l2", "enriched", "synced", "needs_review") or has_l2:
        return "enriched"
    if status == "triage_passed":
        return "qualified"
    if has_l1:
        return "researched"
    return "imported"


ALLOWED_SORT = {
    "name",
    "domain",
    "status",
    "tier",
    "triage_score",
    "hq_country",
    "industry",
    "contact_count",
    "created_at",
    "company_size",
    "geo_region",
    "revenue_range",
    "data_quality_score",
    "verified_employees",
    "verified_revenue_eur_m",
    "credibility_score",
    "enrichment_stage",
}


@companies_bp.route("/api/companies", methods=["POST"])
@require_role("editor")
def create_company():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    allowed_fields = {
        "domain",
        "website_url",
        "industry",
        "company_size",
        "geo_region",
        "notes",
    }

    # Enum validation
    enum_validators = {
        "industry": {
            "software_saas",
            "it",
            "professional_services",
            "financial_services",
            "healthcare",
            "manufacturing",
            "retail",
            "media",
            "energy",
            "telecom",
            "transport",
            "construction",
            "education",
            "public_sector",
            "other",
        },
        "company_size": {"micro", "startup", "smb", "mid_market", "enterprise"},
        "geo_region": {
            "dach",
            "nordics",
            "benelux",
            "cee",
            "uk_ireland",
            "southern_europe",
            "us",
            "other",
        },
    }

    columns = ["tenant_id", "name"]
    placeholders = [":tenant_id", ":name"]
    params = {"tenant_id": tenant_id, "name": name}

    for field in allowed_fields:
        val = body.get(field)
        if val is not None:
            val_str = str(val).strip()
            if not val_str:
                continue
            if field in enum_validators and val_str not in enum_validators[field]:
                return jsonify({"error": f"Invalid value for {field}"}), 400
            columns.append(field)
            placeholders.append(f":{field}")
            params[field] = val_str

    col_str = ", ".join(columns)
    val_str = ", ".join(placeholders)
    sql = f"INSERT INTO companies ({col_str}) VALUES ({val_str}) RETURNING id, name, domain, website_url, industry, company_size, geo_region, notes, created_at"
    row = db.session.execute(db.text(sql), params).fetchone()
    db.session.commit()

    return jsonify(
        {
            "id": row.id,
            "name": row.name,
            "domain": row.domain,
            "website_url": row.website_url,
            "industry": row.industry,
            "company_size": row.company_size,
            "geo_region": row.geo_region,
            "notes": row.notes,
            "created_at": _iso(row.created_at),
        }
    ), 201


@companies_bp.route("/api/companies", methods=["GET"])
@require_auth
def list_companies():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(100, max(1, request.args.get("page_size", 25, type=int)))
    search = request.args.get("search", "").strip()
    tag_name = request.args.get("tag_name", "").strip()
    owner_name = request.args.get("owner_name", "").strip()
    sort = request.args.get("sort", "name").strip()
    sort_dir = request.args.get("sort_dir", "asc").strip().lower()

    if sort not in ALLOWED_SORT:
        sort = "name"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    where = ["c.tenant_id = :tenant_id"]
    params = {"tenant_id": tenant_id}

    if search:
        where.append(
            "(LOWER(c.name) LIKE LOWER(:search) OR LOWER(c.domain) LIKE LOWER(:search))"
        )
        params["search"] = f"%{search}%"
    if tag_name:
        where.append("""EXISTS (
            SELECT 1 FROM company_tag_assignments cota
            JOIN tags bt ON bt.id = cota.tag_id
            WHERE cota.company_id = c.id AND bt.name = :tag_name
        )""")
        params["tag_name"] = tag_name
    if owner_name:
        where.append("o.name = :owner_name")
        params["owner_name"] = owner_name

    # --- Multi-value ICP filters ---
    _add_multi_filter(where, params, "status", "c.status", request)
    _add_multi_filter(where, params, "tier", "c.tier", request)
    _add_multi_filter(where, params, "industry", "c.industry", request)
    _add_multi_filter(where, params, "company_size", "c.company_size", request)
    _add_multi_filter(where, params, "geo_region", "c.geo_region", request)
    _add_multi_filter(where, params, "revenue_range", "c.revenue_range", request)

    # --- enrichment_stage filter (computed from status + enrichment tables) ---
    # Must match _compute_enrichment_stage() logic exactly.
    # The function checks conditions in priority order, so each SQL clause must
    # replicate the same precedence: failed > disqualified > contacts_ready >
    # enriched > qualified > researched > imported.
    es_raw = request.args.get("enrichment_stage", "").strip()
    if es_raw:
        es_values = [v.strip().lower() for v in es_raw.split(",") if v.strip()]
        if es_values:
            es_exclude = (
                request.args.get("enrichment_stage_exclude", "").strip().lower()
                == "true"
            )
            # Each clause mirrors _compute_enrichment_stage() priority order:
            # 1. failed: status contains 'failed' or 'error'
            # 2. disqualified: status = 'triage_disqualified'
            # 3. contacts_ready: status = 'enriched_l2' AND has person enrichment
            # 4. enriched: status IN (...) OR has_l2, but NOT contacts_ready
            # 5. qualified: status = 'triage_passed'
            # 6. researched: has_l1 but none of the above
            # 7. imported: everything else (no L1, no special status)
            # c.status is a PG enum — LIKE requires a text cast.
            # COALESCE handles NULL status (NULL LIKE x → NULL, which breaks NOT).
            # c.status is a PG enum — LIKE requires a text cast.
            # Use COALESCE for NULL-safety (NULL comparisons yield NULL, not False).
            _ST = "COALESCE(CAST(c.status AS TEXT), '')"
            _FAILED_COND = f"({_ST} LIKE '%failed%' OR {_ST} LIKE '%error%')"
            _NOT_FAILED = f"NOT {_FAILED_COND}"
            # NULL-safe NOT IN: (c.status IS NULL OR c.status NOT IN (...))
            _NOT_IN_SPECIAL = (
                "(c.status IS NULL OR c.status NOT IN"
                " ('triage_disqualified','triage_passed','enriched_l2','enriched','synced','needs_review'))"
            )
            _ES_STATUS_MAP = {
                "failed": _FAILED_COND,
                "disqualified": f"({_NOT_FAILED} AND c.status = 'triage_disqualified')",
                "contacts_ready": (
                    f"({_NOT_FAILED} AND c.status = 'enriched_l2'"
                    " AND EXISTS ("
                    "  SELECT 1 FROM contacts ct3"
                    "  JOIN contact_enrichment ce3 ON ce3.contact_id = ct3.id"
                    "  WHERE ct3.company_id = c.id"
                    "))"
                ),
                "enriched": (
                    f"({_NOT_FAILED}"
                    " AND (c.status IS NULL OR c.status != 'triage_disqualified')"
                    " AND ("
                    "  c.status IN ('enriched_l2','enriched','synced','needs_review')"
                    "  OR EXISTS (SELECT 1 FROM company_enrichment_profile l2f WHERE l2f.company_id = c.id)"
                    " )"
                    " AND NOT ("
                    "  c.status = 'enriched_l2'"
                    "  AND EXISTS ("
                    "    SELECT 1 FROM contacts ct4"
                    "    JOIN contact_enrichment ce4 ON ce4.contact_id = ct4.id"
                    "    WHERE ct4.company_id = c.id"
                    "  )"
                    " ))"
                ),
                "qualified": (
                    f"({_NOT_FAILED} AND c.status = 'triage_passed'"
                    " AND NOT EXISTS (SELECT 1 FROM company_enrichment_profile l2q WHERE l2q.company_id = c.id)"
                    ")"
                ),
                "researched": (
                    f"({_NOT_FAILED}"
                    f" AND {_NOT_IN_SPECIAL}"
                    " AND NOT EXISTS (SELECT 1 FROM company_enrichment_profile l2r WHERE l2r.company_id = c.id)"
                    " AND EXISTS (SELECT 1 FROM company_enrichment_l1 l1r WHERE l1r.company_id = c.id)"
                    ")"
                ),
                "imported": (
                    f"({_NOT_FAILED}"
                    f" AND {_NOT_IN_SPECIAL}"
                    " AND NOT EXISTS (SELECT 1 FROM company_enrichment_profile l2i WHERE l2i.company_id = c.id)"
                    " AND NOT EXISTS (SELECT 1 FROM company_enrichment_l1 l1i WHERE l1i.company_id = c.id)"
                    ")"
                ),
            }
            stage_clauses = []
            for sv in es_values:
                clause = _ES_STATUS_MAP.get(sv)
                if clause:
                    stage_clauses.append(clause)
            if stage_clauses:
                combined = " OR ".join(f"({sc})" for sc in stage_clauses)
                if es_exclude:
                    where.append(f"NOT ({combined})")
                else:
                    where.append(f"({combined})")

    # Custom field filters: cf_{key}=value
    cf_idx = 0
    for param_key, param_val in request.args.items():
        if param_key.startswith("cf_") and param_val.strip():
            field_key = param_key[3:]
            # SECURITY: field_key is interpolated into SQLite json_extract path below.
            # This regex whitelist is the ONLY defense against SQL injection for custom field keys.
            # Do NOT weaken this pattern without also parameterizing the SQLite path.
            if not re.match(r"^[a-zA-Z0-9_]+$", field_key):
                continue
            dialect = db.engine.dialect.name
            if dialect == "sqlite":
                where.append(
                    f"json_extract(c.custom_fields, '$.{field_key}') = :cf_val_{cf_idx}"
                )
            else:
                where.append(f"c.custom_fields ->> :cf_key_{cf_idx} = :cf_val_{cf_idx}")
                params[f"cf_key_{cf_idx}"] = field_key
            params[f"cf_val_{cf_idx}"] = param_val.strip()
            cf_idx += 1

    where_clause = " AND ".join(where)

    # Count query
    total = (
        db.session.execute(
            db.text(f"""
            SELECT COUNT(*)
            FROM companies c
            LEFT JOIN owners o ON c.owner_id = o.id
            WHERE {where_clause}
        """),
            params,
        ).scalar()
        or 0
    )

    pages = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size

    # Sort mapping for computed columns
    if sort == "contact_count":
        sort_col = "contact_count"
    elif sort == "enrichment_stage":
        # Order stages by pipeline progression
        sort_col = """CASE c.status
            WHEN 'triage_disqualified' THEN 0
            WHEN 'enrichment_failed' THEN 1
            WHEN 'enrichment_l2_failed' THEN 1
            WHEN 'error_pushing_lemlist' THEN 1
            WHEN 'new' THEN 2
            WHEN 'triage_passed' THEN 4
            WHEN 'enriched_l2' THEN 5
            WHEN 'enriched' THEN 5
            WHEN 'synced' THEN 5
            WHEN 'needs_review' THEN 5
            ELSE 3 END"""
    else:
        sort_col = f"c.{sort}"
    # Append `c.id ASC` as a unique tiebreaker so pagination stays stable when
    # the primary sort column has tied/NULL values (otherwise duplicate rows can
    # appear across page boundaries). See BL-1116.
    order = f"{sort_col} {'ASC' if sort_dir == 'asc' else 'DESC'} NULLS LAST, c.id ASC"

    rows = db.session.execute(
        db.text(f"""
            SELECT
                c.id, c.name, c.domain, c.status, c.tier,
                o.name AS owner_name,
                c.industry, c.hq_country, c.triage_score,
                (SELECT COUNT(*) FROM contacts ct WHERE ct.company_id = c.id) AS contact_count,
                c.created_at,
                c.company_size, c.geo_region, c.revenue_range,
                c.business_model, c.ownership_type, c.buying_stage,
                c.engagement_status,
                c.verified_employees, c.verified_revenue_eur_m,
                c.credibility_score, c.linkedin_url, c.website_url,
                c.data_quality_score, c.last_enriched_at,
                CASE WHEN l1.company_id IS NOT NULL THEN 1 ELSE 0 END AS has_l1,
                CASE WHEN l2p.company_id IS NOT NULL THEN 1 ELSE 0 END AS has_l2,
                CASE WHEN EXISTS (
                    SELECT 1 FROM contacts ct2
                    JOIN contact_enrichment ce ON ce.contact_id = ct2.id
                    WHERE ct2.company_id = c.id
                ) THEN 1 ELSE 0 END AS has_person_enrichment
            FROM companies c
            LEFT JOIN owners o ON c.owner_id = o.id
            LEFT JOIN company_enrichment_l1 l1 ON l1.company_id = c.id
            LEFT JOIN company_enrichment_profile l2p ON l2p.company_id = c.id
            WHERE {where_clause}
            ORDER BY {order}
            LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": page_size, "offset": offset},
    ).fetchall()

    company_ids = [str(r[0]) for r in rows]

    # Batch-fetch stage completions for list
    stage_map = {}
    if company_ids:
        placeholders = ", ".join(f":id_{i}" for i in range(len(company_ids)))
        id_params = {f"id_{i}": cid for i, cid in enumerate(company_ids)}
        sc_rows = db.session.execute(
            db.text(f"""
                SELECT entity_id, stage, status
                FROM entity_stage_completions
                WHERE entity_id IN ({placeholders}) AND entity_type = 'company'
            """),
            id_params,
        ).fetchall()
        for sc in sc_rows:
            eid = str(sc[0])
            stage_map.setdefault(eid, []).append({"stage": sc[1], "status": sc[2]})

    # Batch tag lookup via junction table
    tag_map: dict[str, list[str]] = {cid: [] for cid in company_ids}
    if company_ids:
        placeholders = ", ".join(f":cid_{i}" for i in range(len(company_ids)))
        tag_params = {f"cid_{i}": cid for i, cid in enumerate(company_ids)}
        tag_rows = db.session.execute(
            db.text(f"""
                SELECT cota.company_id, t.name
                FROM company_tag_assignments cota
                JOIN tags t ON t.id = cota.tag_id
                WHERE cota.company_id IN ({placeholders})
                ORDER BY t.name
            """),
            tag_params,
        ).fetchall()
        for tr in tag_rows:
            tag_map.setdefault(str(tr[0]), []).append(tr[1])

    companies = []
    for r in rows:
        cid = str(r[0])
        completions = stage_map.get(cid, [])
        tag_names = tag_map.get(cid, [])
        raw_status = r[3]
        has_l1 = bool(r[25])
        has_l2 = bool(r[26])
        has_person = bool(r[27])
        stage = _compute_enrichment_stage(raw_status, has_l1, has_l2, has_person)
        triage_score = float(r[8]) if r[8] is not None else None
        companies.append(
            {
                "id": cid,
                "name": r[1],
                "domain": r[2],
                "status": display_status(raw_status),
                "enrichment_stage": display_enrichment_stage(stage),
                "tier": display_tier(r[4]),
                "owner_name": r[5],
                "tag_name": tag_names[0] if tag_names else None,
                "tag_names": tag_names,
                "industry": display_industry(r[6]),
                "hq_country": r[7],
                "score": triage_score,
                "triage_score": triage_score,
                "contact_count": r[9] or 0,
                "derived_stage": _derive_stage(completions),
                "company_size": display_company_size(r[11]),
                "geo_region": display_geo_region(r[12]),
                "revenue_range": display_revenue_range(r[13]),
                "business_model": display_business_model(r[14]),
                "ownership_type": display_ownership_type(r[15]),
                "buying_stage": display_buying_stage(r[16]),
                "engagement_status": display_engagement_status(r[17]),
                "verified_employees": float(r[18]) if r[18] is not None else None,
                "verified_revenue_eur_m": float(r[19]) if r[19] is not None else None,
                "credibility_score": int(r[20]) if r[20] is not None else None,
                "linkedin_url": r[21],
                "website_url": r[22],
                "data_quality_score": int(r[23]) if r[23] is not None else None,
                "last_enriched_at": r[24].isoformat() if r[24] else None,
            }
        )

    return jsonify(
        {
            "companies": companies,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    )


@companies_bp.route("/api/companies/filter-counts", methods=["POST"])
@require_auth
def company_filter_counts():
    """Return faceted counts for all filterable company fields.

    Each field's counts are computed with all OTHER active filters applied
    (standard faceted search pattern).
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    filters = body.get("filters", {})
    search = body.get("search", "").strip()
    tag_name = body.get("tag_name", "").strip()
    owner_name = body.get("owner_name", "").strip()

    # Define all facet fields with their column references
    FACET_FIELDS = {
        "status": "c.status",
        "tier": "c.tier",
        "industry": "c.industry",
        "company_size": "c.company_size",
        "geo_region": "c.geo_region",
        "revenue_range": "c.revenue_range",
    }

    def _build_base_where(params, exclude_facet=None):
        """Build WHERE clause applying all filters EXCEPT exclude_facet."""
        where = ["c.tenant_id = :tenant_id"]
        params["tenant_id"] = tenant_id

        if search:
            where.append(
                "(LOWER(c.name) LIKE LOWER(:search) OR LOWER(c.domain) LIKE LOWER(:search))"
            )
            params["search"] = f"%{search}%"
        if tag_name:
            where.append("""EXISTS (
                SELECT 1 FROM company_tag_assignments cota
                JOIN tags bt ON bt.id = cota.tag_id
                WHERE cota.company_id = c.id AND bt.name = :tag_name
            )""")
            params["tag_name"] = tag_name
        if owner_name:
            where.append("o.name = :owner_name")
            params["owner_name"] = owner_name

        # Apply all multi-value filters EXCEPT the one being faceted
        for field_key, column in FACET_FIELDS.items():
            if field_key == exclude_facet:
                continue
            f = filters.get(field_key, {})
            values = f.get("values", [])[:100] if isinstance(f, dict) else []
            if not values:
                continue
            exclude = f.get("exclude", False) if isinstance(f, dict) else False
            placeholders = ", ".join(f":{field_key}_{i}" for i in range(len(values)))
            for i, v in enumerate(values):
                params[f"{field_key}_{i}"] = v
            if exclude:
                where.append(f"({column} IS NULL OR {column} NOT IN ({placeholders}))")
            else:
                where.append(f"{column} IN ({placeholders})")

        return " AND ".join(where)

    joins = """
        LEFT JOIN owners o ON c.owner_id = o.id
    """

    facets = {}
    for field_key, column in FACET_FIELDS.items():
        params = {}
        where_clause = _build_base_where(params, exclude_facet=field_key)

        rows = db.session.execute(
            db.text(f"""
                SELECT {column} AS val, COUNT(*) AS cnt
                FROM companies c
                {joins}
                WHERE {where_clause}
                  AND {column} IS NOT NULL
                GROUP BY {column}
                ORDER BY cnt DESC
            """),
            params,
        ).fetchall()
        facets[field_key] = [{"value": r[0], "count": r[1]} for r in rows]

    # enrichment_stage facet (computed, not a direct column)
    es_params = {}
    es_where = _build_base_where(es_params)
    es_rows = db.session.execute(
        db.text(f"""
            SELECT
                c.status,
                CASE WHEN l1.company_id IS NOT NULL THEN 1 ELSE 0 END AS has_l1,
                CASE WHEN l2p.company_id IS NOT NULL THEN 1 ELSE 0 END AS has_l2,
                CASE WHEN EXISTS (
                    SELECT 1 FROM contacts ct2
                    JOIN contact_enrichment ce ON ce.contact_id = ct2.id
                    WHERE ct2.company_id = c.id
                ) THEN 1 ELSE 0 END AS has_person
            FROM companies c
            {joins}
            LEFT JOIN company_enrichment_l1 l1 ON l1.company_id = c.id
            LEFT JOIN company_enrichment_profile l2p ON l2p.company_id = c.id
            WHERE {es_where}
        """),
        es_params,
    ).fetchall()
    stage_counts = {}
    for r in es_rows:
        stage = _compute_enrichment_stage(r[0], bool(r[1]), bool(r[2]), bool(r[3]))
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    facets["enrichment_stage"] = [
        {"value": k, "count": v}
        for k, v in sorted(stage_counts.items(), key=lambda x: -x[1])
    ]

    # Total count with ALL filters applied
    total_params = {}
    total_where = _build_base_where(total_params)

    total = (
        db.session.execute(
            db.text(f"""
            SELECT COUNT(*)
            FROM companies c
            {joins}
            WHERE {total_where}
        """),
            total_params,
        ).scalar()
        or 0
    )

    return jsonify({"total": total, "facets": facets})


@companies_bp.route("/api/companies/<company_id>", methods=["GET"])
@require_auth
def get_company(company_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text("""
            SELECT
                c.id, c.name, c.domain, c.status, c.tier,
                c.business_model, c.company_size, c.ownership_type,
                c.geo_region, c.industry, c.industry_category,
                c.revenue_range, c.buying_stage, c.engagement_status,
                c.crm_status,
                c.business_type, c.cohort,
                c.summary, c.hq_city, c.hq_country,
                c.triage_score,
                c.verified_revenue_eur_m, c.verified_employees,
                c.enrichment_cost_usd,
                c.lemlist_synced, c.error_message, c.notes, c.custom_fields,
                c.created_at, c.updated_at,
                o.name AS owner_name, b.name AS tag_name,
                c.website_url, c.linkedin_url, c.logo_url,
                c.last_enriched_at, c.data_quality_score
            FROM companies c
            LEFT JOIN owners o ON c.owner_id = o.id
            LEFT JOIN tags b ON c.tag_id = b.id
            WHERE c.id = :id AND c.tenant_id = :tenant_id
        """),
        {"id": company_id, "tenant_id": tenant_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Company not found"}), 404

    company = {
        "id": str(row[0]),
        "name": row[1],
        "domain": row[2],
        "status": display_status(row[3]),
        "tier": display_tier(row[4]),
        "business_model": display_business_model(row[5]),
        "company_size": display_company_size(row[6]),
        "ownership_type": display_ownership_type(row[7]),
        "geo_region": display_geo_region(row[8]),
        "industry": display_industry(row[9]),
        "industry_category": display_industry_category(row[10]),
        "revenue_range": display_revenue_range(row[11]),
        "buying_stage": display_buying_stage(row[12]),
        "engagement_status": display_engagement_status(row[13]),
        "crm_status": display_crm_status(row[14]),
        "business_type": display_business_type(row[15]),
        "cohort": display_cohort(row[16]),
        "summary": row[17],
        "hq_city": row[18],
        "hq_country": row[19],
        "triage_score": float(row[20]) if row[20] is not None else None,
        "verified_revenue_eur_m": float(row[21]) if row[21] is not None else None,
        "verified_employees": float(row[22]) if row[22] is not None else None,
        "enrichment_cost_usd": float(row[23]) if row[23] is not None else None,
        "lemlist_synced": row[24],
        "error_message": row[25],
        "notes": row[26],
        "custom_fields": _parse_jsonb(row[27]),
        "created_at": _iso(row[28]),
        "updated_at": _iso(row[29]),
        "owner_name": row[30],
        "tag_name": row[31],
        "website_url": row[32],
        "linkedin_url": row[33],
        "logo_url": row[34],
        "last_enriched_at": _iso(row[35]),
        "data_quality_score": float(row[36]) if row[36] is not None else None,
    }

    # L1 enrichment
    l1_row = db.session.execute(
        db.text("""
            SELECT triage_notes, pre_score, research_query, raw_response,
                   confidence, quality_score, qc_flags,
                   enriched_at, enrichment_cost_usd
            FROM company_enrichment_l1
            WHERE company_id = :id
        """),
        {"id": company_id},
    ).fetchone()

    if l1_row:
        company["enrichment_l1"] = {
            "triage_notes": l1_row[0],
            "pre_score": float(l1_row[1]) if l1_row[1] is not None else None,
            "research_query": l1_row[2],
            "raw_response": _parse_jsonb(l1_row[3]),
            "confidence": float(l1_row[4]) if l1_row[4] is not None else None,
            "quality_score": l1_row[5],
            "qc_flags": _parse_jsonb(l1_row[6]),
            "enriched_at": _iso(l1_row[7]),
            "enrichment_cost_usd": float(l1_row[8]) if l1_row[8] is not None else None,
        }
    else:
        company["enrichment_l1"] = None

    # L2 enrichment — module-based structure
    l2_modules = {}

    # Profile module
    prof_row = db.session.execute(
        db.text("""
            SELECT company_intel, key_products, customer_segments, competitors,
                   tech_stack, leadership_team, certifications, expansion,
                   enriched_at, enrichment_cost_usd
            FROM company_enrichment_profile
            WHERE company_id = :id
        """),
        {"id": company_id},
    ).fetchone()
    if prof_row:
        l2_modules["profile"] = {
            "company_intel": prof_row[0],
            "key_products": prof_row[1],
            "customer_segments": prof_row[2],
            "competitors": prof_row[3],
            "tech_stack": prof_row[4],
            "leadership_team": prof_row[5],
            "certifications": prof_row[6],
            "expansion": prof_row[7],
            "enriched_at": _iso(prof_row[8]),
            "enrichment_cost_usd": float(prof_row[9])
            if prof_row[9] is not None
            else None,
        }

    # Signals module
    sig_row = db.session.execute(
        db.text("""
            SELECT digital_initiatives, leadership_changes, hiring_signals,
                   ai_hiring, tech_partnerships, competitor_ai_moves,
                   ai_adoption_level, news_confidence, growth_indicators,
                   job_posting_count, hiring_departments,
                   workflow_ai_evidence, regulatory_pressure, employee_sentiment,
                   tech_stack_categories, fiscal_year_end,
                   digital_maturity_score, it_spend_indicators,
                   enriched_at, enrichment_cost_usd
            FROM company_enrichment_signals
            WHERE company_id = :id
        """),
        {"id": company_id},
    ).fetchone()
    if sig_row:
        l2_modules["signals"] = {
            "digital_initiatives": sig_row[0],
            "leadership_changes": sig_row[1],
            "hiring_signals": sig_row[2],
            "ai_hiring": sig_row[3],
            "tech_partnerships": sig_row[4],
            "competitor_ai_moves": sig_row[5],
            "ai_adoption_level": sig_row[6],
            "news_confidence": sig_row[7],
            "growth_indicators": sig_row[8],
            "job_posting_count": sig_row[9],
            "hiring_departments": _parse_jsonb(sig_row[10]),
            "workflow_ai_evidence": sig_row[11],
            "regulatory_pressure": sig_row[12],
            "employee_sentiment": sig_row[13],
            "tech_stack_categories": sig_row[14],
            "fiscal_year_end": sig_row[15],
            "digital_maturity_score": sig_row[16],
            "it_spend_indicators": sig_row[17],
            "enriched_at": _iso(sig_row[18]),
            "enrichment_cost_usd": float(sig_row[19])
            if sig_row[19] is not None
            else None,
        }

    # Market module
    mkt_row = db.session.execute(
        db.text("""
            SELECT recent_news, funding_history, eu_grants,
                   media_sentiment, press_releases, thought_leadership,
                   expansion, workflow_ai_evidence, revenue_trend,
                   growth_signals, ma_activity,
                   enriched_at, enrichment_cost_usd
            FROM company_enrichment_market
            WHERE company_id = :id
        """),
        {"id": company_id},
    ).fetchone()
    if mkt_row:
        l2_modules["market"] = {
            "recent_news": mkt_row[0],
            "funding_history": mkt_row[1],
            "eu_grants": mkt_row[2],
            "media_sentiment": mkt_row[3],
            "press_releases": mkt_row[4],
            "thought_leadership": mkt_row[5],
            "expansion": mkt_row[6],
            "workflow_ai_evidence": mkt_row[7],
            "revenue_trend": mkt_row[8],
            "growth_signals": mkt_row[9],
            "ma_activity": mkt_row[10],
            "enriched_at": _iso(mkt_row[11]),
            "enrichment_cost_usd": float(mkt_row[12])
            if mkt_row[12] is not None
            else None,
        }

    # Opportunity module
    opp_row = db.session.execute(
        db.text("""
            SELECT pain_hypothesis, relevant_case_study, ai_opportunities,
                   quick_wins, industry_pain_points, cross_functional_pain,
                   adoption_barriers, pitch_framing, competitor_ai_moves,
                   enriched_at, enrichment_cost_usd
            FROM company_enrichment_opportunity
            WHERE company_id = :id
        """),
        {"id": company_id},
    ).fetchone()
    if opp_row:
        l2_modules["opportunity"] = {
            "pain_hypothesis": opp_row[0],
            "relevant_case_study": opp_row[1],
            "ai_opportunities": opp_row[2],
            "quick_wins": _parse_jsonb(opp_row[3]),
            "industry_pain_points": opp_row[4],
            "cross_functional_pain": opp_row[5],
            "adoption_barriers": opp_row[6],
            "pitch_framing": opp_row[7],
            "competitor_ai_moves": opp_row[8],
            "enriched_at": _iso(opp_row[9]),
            "enrichment_cost_usd": float(opp_row[10])
            if opp_row[10] is not None
            else None,
        }

    # Aggregate enriched_at / cost across modules
    enriched_ats = []
    total_cost = 0.0
    for mod in l2_modules.values():
        if mod.get("enriched_at"):
            enriched_ats.append(mod["enriched_at"])
        if mod.get("enrichment_cost_usd"):
            total_cost += mod["enrichment_cost_usd"]

    if l2_modules:
        company["enrichment_l2"] = {
            "modules": l2_modules,
            "enriched_at": max(enriched_ats) if enriched_ats else None,
            "enrichment_cost_usd": total_cost if total_cost > 0 else None,
        }
    else:
        company["enrichment_l2"] = None

    # Backfill top-level convenience fields from enrichment tables
    if company.get("enrichment_l1"):
        company["triage_notes"] = company["enrichment_l1"].get("triage_notes")
        company["pre_score"] = company["enrichment_l1"].get("pre_score")
    else:
        company["triage_notes"] = None
        company["pre_score"] = None

    if l2_modules.get("signals"):
        company["ai_adoption"] = display_confidence(
            l2_modules["signals"].get("ai_adoption_level")
        )
        company["news_confidence"] = display_confidence(
            l2_modules["signals"].get("news_confidence")
        )
    else:
        company["ai_adoption"] = None
        company["news_confidence"] = None

    # Legal profile (unified registry data)
    lp_row = db.session.execute(
        db.text("""
            SELECT registration_id, tax_id, official_name, legal_form,
                   legal_form_name, date_established, date_dissolved,
                   registered_address, address_city, address_postal_code,
                   nace_codes, registration_court, registration_number,
                   registered_capital, directors, registration_status,
                   insolvency_flag, insolvency_details, active_insolvency_count,
                   match_confidence, match_method, enriched_at,
                   registration_country, credibility_score, credibility_factors
            FROM company_legal_profile
            WHERE company_id = :id
        """),
        {"id": company_id},
    ).fetchone()

    if lp_row:
        company["registry_data"] = {
            "ico": lp_row[0],
            "dic": lp_row[1],
            "official_name": lp_row[2],
            "legal_form": lp_row[3],
            "legal_form_name": lp_row[4],
            "date_established": str(lp_row[5]) if lp_row[5] else None,
            "date_dissolved": str(lp_row[6]) if lp_row[6] else None,
            "registered_address": lp_row[7],
            "address_city": lp_row[8],
            "address_postal_code": lp_row[9],
            "nace_codes": _parse_jsonb(lp_row[10]),
            "registration_court": lp_row[11],
            "registration_number": lp_row[12],
            "registered_capital": lp_row[13],
            "directors": _parse_jsonb(lp_row[14]),
            "registration_status": lp_row[15],
            "insolvency_flag": lp_row[16],
            "insolvency_details": _parse_jsonb(lp_row[17]),
            "active_insolvency_count": lp_row[18] or 0,
            "match_confidence": float(lp_row[19]) if lp_row[19] is not None else None,
            "match_method": lp_row[20],
            "enriched_at": _iso(lp_row[21]),
            "registration_country": lp_row[22],
            "credibility_score": lp_row[23],
            "credibility_factors": _parse_jsonb(lp_row[24]),
        }
    else:
        # Fallback: read from legacy company_registry_data table
        reg_row = db.session.execute(
            db.text("""
                SELECT ico, dic, official_name, legal_form, legal_form_name,
                       date_established, date_dissolved, registered_address,
                       address_city, address_postal_code, nace_codes,
                       registration_court, registration_number, registered_capital,
                       directors, registration_status, insolvency_flag,
                       match_confidence, match_method, ares_updated_at,
                       enriched_at, registry_country
                FROM company_registry_data
                WHERE company_id = :id
            """),
            {"id": company_id},
        ).fetchone()

        if reg_row:
            company["registry_data"] = {
                "ico": reg_row[0],
                "dic": reg_row[1],
                "official_name": reg_row[2],
                "legal_form": reg_row[3],
                "legal_form_name": reg_row[4],
                "date_established": str(reg_row[5]) if reg_row[5] else None,
                "date_dissolved": str(reg_row[6]) if reg_row[6] else None,
                "registered_address": reg_row[7],
                "address_city": reg_row[8],
                "address_postal_code": reg_row[9],
                "nace_codes": _parse_jsonb(reg_row[10]),
                "registration_court": reg_row[11],
                "registration_number": reg_row[12],
                "registered_capital": reg_row[13],
                "directors": _parse_jsonb(reg_row[14]),
                "registration_status": reg_row[15],
                "insolvency_flag": reg_row[16],
                "match_confidence": float(reg_row[17])
                if reg_row[17] is not None
                else None,
                "match_method": reg_row[18],
                "enriched_at": _iso(reg_row[20]),
                "registration_country": reg_row[21],
            }
        else:
            company["registry_data"] = None

    # Stage completions (DAG tracking)
    sc_rows = db.session.execute(
        db.text("""
            SELECT stage, status, completed_at, cost_usd, error
            FROM entity_stage_completions
            WHERE entity_type = 'company' AND entity_id = :id
            ORDER BY completed_at NULLS LAST
        """),
        {"id": company_id},
    ).fetchall()
    company["stage_completions"] = [
        {
            "stage": r[0],
            "status": r[1],
            "completed_at": _iso(r[2]),
            "cost_usd": float(r[3]) if r[3] is not None else None,
            "error": r[4],
        }
        for r in sc_rows
    ]

    # Tags
    tag_rows = db.session.execute(
        db.text(
            "SELECT category, value FROM company_tags WHERE company_id = :id ORDER BY category, value"
        ),
        {"id": company_id},
    ).fetchall()
    company["tags"] = [{"category": r[0], "value": r[1]} for r in tag_rows]

    # Contacts summary (with enrichment fields via LEFT JOIN)
    contact_rows = db.session.execute(
        db.text("""
            SELECT ct.id, ct.first_name, ct.last_name, ct.job_title, ct.email_address,
                   ct.contact_score, ct.icp_fit, ct.message_status,
                   ct.linkedin_url, ct.seniority_level, ct.department,
                   ce.ai_champion, ce.ai_champion_score, ce.authority_score,
                   ce.person_summary, ce.career_trajectory
            FROM contacts ct
            LEFT JOIN contact_enrichment ce ON ce.contact_id = ct.id
            WHERE ct.company_id = :id
            ORDER BY ct.contact_score DESC NULLS LAST
        """),
        {"id": company_id},
    ).fetchall()
    company["contacts"] = [
        {
            "id": str(r[0]),
            "full_name": ((r[1] or "") + " " + (r[2] or "")).strip(),
            "first_name": r[1],
            "last_name": r[2],
            "job_title": r[3],
            "email_address": r[4],
            "contact_score": r[5],
            "icp_fit": display_icp_fit(r[6]),
            "message_status": r[7],
            "linkedin_url": r[8],
            "seniority_level": r[9],
            "department": r[10],
            "ai_champion": r[11],
            "ai_champion_score": r[12],
            "authority_score": r[13],
            "person_summary": r[14],
            "career_trajectory": r[15],
        }
        for r in contact_rows
    ]

    # Stage completions + derived stage
    sc_rows = db.session.execute(
        db.text("""
            SELECT stage, status, cost_usd, completed_at
            FROM entity_stage_completions
            WHERE entity_id = :id AND entity_type = 'company'
            ORDER BY completed_at ASC
        """),
        {"id": company_id},
    ).fetchall()

    completions = []
    for sc in sc_rows:
        completions.append(
            {
                "stage": sc[0],
                "status": sc[1],
                "cost_usd": float(sc[2]) if sc[2] is not None else None,
                "completed_at": _iso(sc[3]),
            }
        )

    company["stage_completions"] = completions
    company["derived_stage"] = _derive_stage(completions, company.get("status"))

    # Compute enrichment_stage for detail endpoint
    has_l1_detail = company.get("enrichment_l1") is not None
    has_l2_detail = company.get("enrichment_l2") is not None
    # Check if any contact for this company has person enrichment
    has_person_detail = any(
        ct.get("person_summary") is not None for ct in company.get("contacts", [])
    )
    raw_status_detail = row[3]
    company["enrichment_stage"] = display_enrichment_stage(
        _compute_enrichment_stage(
            raw_status_detail, has_l1_detail, has_l2_detail, has_person_detail
        )
    )
    # Score alias for triage_score
    company["score"] = company.get("triage_score")

    return jsonify(company)


@companies_bp.route("/api/companies/<company_id>", methods=["DELETE"])
@require_role("editor")
def delete_company(company_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify company belongs to tenant
    row = db.session.execute(
        db.text("SELECT id FROM companies WHERE id = :id AND tenant_id = :tid"),
        {"id": company_id, "tid": str(tenant_id)},
    ).fetchone()
    if not row:
        return jsonify({"error": "Company not found"}), 404

    params = {"id": company_id, "tid": str(tenant_id)}

    # Delete junction records first
    db.session.execute(
        db.text(
            "DELETE FROM company_tag_assignments WHERE company_id = :id AND tenant_id = :tid"
        ),
        params,
    )

    # Delete the company
    db.session.execute(
        db.text("DELETE FROM companies WHERE id = :id AND tenant_id = :tid"),
        params,
    )
    db.session.commit()

    return jsonify({"deleted": True})


@companies_bp.route("/api/companies/<company_id>", methods=["PATCH"])
@require_role("editor")
def update_company(company_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    allowed = {
        "status",
        "tier",
        "notes",
        "triage_notes",
        "buying_stage",
        "engagement_status",
        "crm_status",
        "cohort",
        "name",
        "domain",
        "website_url",
        "linkedin_url",
    }
    fields = {k: v for k, v in body.items() if k in allowed}
    custom_fields_update = body.get("custom_fields")

    if not fields and not custom_fields_update:
        return jsonify({"error": "No valid fields to update"}), 400

    # Enum validation for fields with finite allowed values
    company_enum_validators = {
        "status": {
            "new",
            "enrichment_failed",
            "triage_passed",
            "triage_review",
            "triage_disqualified",
            "enrichment_l2_failed",
            "enriched_l2",
            "synced",
            "needs_review",
            "enriched",
            "error_pushing_lemlist",
        },
        "tier": {
            "tier_1_platinum",
            "tier_2_gold",
            "tier_3_silver",
            "tier_4_bronze",
            "tier_5_copper",
            "deprioritize",
        },
        "buying_stage": {
            "unaware",
            "problem_aware",
            "exploring_ai",
            "looking_for_partners",
            "in_discussion",
            "proposal_sent",
            "won",
            "lost",
        },
        "engagement_status": {
            "cold",
            "approached",
            "prospect",
            "customer",
            "churned",
        },
        "crm_status": {
            "cold",
            "scheduled_for_outreach",
            "outreach",
            "prospect",
            "customer",
            "churn",
        },
        "cohort": {"a", "b"},
    }
    for field, value in fields.items():
        if (
            field in company_enum_validators
            and value not in company_enum_validators[field]
        ):
            return jsonify(
                {
                    "error": f"Invalid value '{value}' for field '{field}'",
                    "field": field,
                    "allowed": sorted(company_enum_validators[field]),
                }
            ), 400

    # Verify company belongs to tenant and pull current values for the audit diff.
    existing = db.session.execute(
        db.text(
            """
            SELECT
                id,
                custom_fields,
                name,
                domain,
                website_url,
                linkedin_url,
                notes,
                triage_notes,
                status,
                tier,
                buying_stage,
                engagement_status,
                crm_status,
                cohort
            FROM companies
            WHERE id = :id AND tenant_id = :t
            """
        ),
        {"id": company_id, "t": tenant_id},
    ).fetchone()
    if not existing:
        return jsonify({"error": "Company not found"}), 404

    existing_map = {
        "name": existing[2],
        "domain": existing[3],
        "website_url": existing[4],
        "linkedin_url": existing[5],
        "notes": existing[6],
        "triage_notes": existing[7],
        "status": existing[8],
        "tier": existing[9],
        "buying_stage": existing[10],
        "engagement_status": existing[11],
        "crm_status": existing[12],
        "cohort": existing[13],
    }

    set_parts = []
    params = {"id": company_id}
    for k, v in fields.items():
        set_parts.append(f"{k} = :{k}")
        params[k] = v

    if custom_fields_update and isinstance(custom_fields_update, dict):
        existing_cf = _parse_jsonb(existing[1])
        existing_cf.update(custom_fields_update)
        set_parts.append("custom_fields = :custom_fields")
        params["custom_fields"] = json.dumps(existing_cf)

    db.session.execute(
        db.text(f"UPDATE companies SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )

    # Audit log: one row per actually-changed field.
    changed_by = getattr(getattr(g, "current_user", None), "id", None)
    for field_name, new_value in fields.items():
        old_value = existing_map.get(field_name)
        if old_value == new_value:
            continue
        write_field_change(
            tenant_id=tenant_id,
            entity_type="company",
            entity_id=company_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
        )

    db.session.commit()

    return jsonify({"ok": True})


# ── Triage Review (BL-176) ────────────────────────────────
VALID_TRIAGE_ACTIONS = {"pass", "review", "disqualify"}


@companies_bp.route("/api/companies/<company_id>/triage", methods=["PATCH"])
@require_role("editor")
def triage_company(company_id):
    """Apply a triage decision to a company.

    Body: { action: "pass"|"review"|"disqualify", reason?: string }
    - pass: sets status to triage_passed
    - review: sets status to needs_review (keep for manual follow-up)
    - disqualify: sets status to triage_disqualified, reason required
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").strip().lower()
    reason = (body.get("reason") or "").strip()

    if action not in VALID_TRIAGE_ACTIONS:
        return (
            jsonify(
                {
                    "error": f"Invalid action '{action}'. Must be one of: {', '.join(sorted(VALID_TRIAGE_ACTIONS))}"
                }
            ),
            400,
        )

    if action == "disqualify" and not reason:
        return jsonify({"error": "Reason is required for disqualification"}), 400

    # Verify company belongs to tenant
    row = db.session.execute(
        db.text("SELECT id, status FROM companies WHERE id = :id AND tenant_id = :t"),
        {"id": company_id, "t": tenant_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Company not found"}), 404

    status_map = {
        "pass": "triage_passed",
        "review": "needs_review",
        "disqualify": "triage_disqualified",
    }
    new_status = status_map[action]

    # Build update — use CURRENT_TIMESTAMP for SQLite compat
    ts_fn = "CURRENT_TIMESTAMP" if db.engine.dialect.name == "sqlite" else "now()"
    set_parts = ["status = :new_status", f"updated_at = {ts_fn}"]
    params: dict = {"id": company_id, "new_status": new_status}

    if reason:
        set_parts.append("triage_notes = :reason")
        params["reason"] = reason

    db.session.execute(
        db.text(f"UPDATE companies SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )
    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "company_id": str(company_id),
            "action": action,
            "status": new_status,
        }
    )


@companies_bp.route("/api/companies/triage-queue", methods=["GET"])
@require_auth
def triage_queue():
    """Return companies pending triage review.

    These are companies that completed L1 enrichment and have a triage_score
    but haven't been explicitly passed/disqualified yet.
    Sorted by triage_score descending (best candidates first).
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(100, max(1, request.args.get("page_size", 25, type=int)))
    offset = (page - 1) * page_size

    # Companies that have L1 enrichment but are still "new" or "needs_review"
    # (not yet triage_passed or triage_disqualified)
    where_clause = """
        c.tenant_id = :t
        AND c.status IS NOT NULL
        AND c.status NOT IN ('triage_passed', 'triage_disqualified')
        AND EXISTS (
            SELECT 1 FROM company_enrichment_l1 l1 WHERE l1.company_id = c.id
        )
    """
    params: dict = {"t": tenant_id}

    tag_name = request.args.get("tag_name", "").strip()
    if tag_name:
        where_clause += """ AND EXISTS (
            SELECT 1 FROM company_tag_assignments cta
            JOIN tags bt ON bt.id = cta.tag_id
            WHERE cta.company_id = c.id AND bt.name = :tag_name
        )"""
        params["tag_name"] = tag_name

    # Count
    total = (
        db.session.execute(
            db.text(f"""
                SELECT COUNT(*)
                FROM companies c
                WHERE {where_clause}
            """),
            params,
        ).scalar()
        or 0
    )

    import math

    pages = max(1, math.ceil(total / page_size))

    rows = db.session.execute(
        db.text(f"""
            SELECT
                c.id, c.name, c.domain, c.tier, c.status,
                c.triage_score, l1.triage_notes, c.industry,
                c.hq_country, c.company_size, c.revenue_range,
                o.name AS owner_name,
                l1.pre_score, l1.confidence
            FROM companies c
            LEFT JOIN owners o ON c.owner_id = o.id
            LEFT JOIN company_enrichment_l1 l1 ON l1.company_id = c.id
            WHERE {where_clause}
            ORDER BY c.triage_score DESC NULLS LAST, c.name ASC, c.id ASC
            LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": page_size, "offset": offset},
    ).fetchall()

    companies = []
    for r in rows:
        companies.append(
            {
                "id": str(r[0]),
                "name": r[1],
                "domain": r[2],
                "tier": display_tier(r[3]),
                "status": display_status(r[4]),
                "triage_score": float(r[5]) if r[5] is not None else None,
                "triage_notes": r[6],
                "industry": display_industry(r[7]),
                "hq_country": r[8],
                "company_size": display_company_size(r[9]),
                "revenue_range": display_revenue_range(r[10]),
                "owner_name": r[11],
                "pre_score": float(r[12]) if r[12] is not None else None,
                "confidence": float(r[13]) if r[13] is not None else None,
            }
        )

    return jsonify(
        {
            "companies": companies,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    )


@companies_bp.route("/api/companies/<company_id>/enrich-registry", methods=["POST"])
@require_auth
def enrich_registry(company_id):
    """On-demand unified registry lookup for a single company."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify company belongs to tenant
    row = db.session.execute(
        db.text(
            "SELECT name, hq_country, domain FROM companies WHERE id = :id AND tenant_id = :t"
        ),
        {"id": company_id, "t": tenant_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Company not found"}), 404

    body = request.get_json(silent=True) or {}
    ico_override = body.get("ico")

    from ..services.registries.orchestrator import RegistryOrchestrator

    orchestrator = RegistryOrchestrator()
    result = orchestrator.enrich_company(
        company_id=company_id,
        tenant_id=str(tenant_id),
        name=row[0],
        reg_id=ico_override,
        hq_country=row[1],
        domain=row[2],
    )

    return jsonify(result)


@companies_bp.route("/api/companies/<company_id>/confirm-registry", methods=["POST"])
@require_auth
def confirm_registry(company_id):
    """Confirm an ARES match from a list of candidates by providing the ICO."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text(
            "SELECT name, hq_country, domain FROM companies WHERE id = :id AND tenant_id = :t"
        ),
        {"id": company_id, "t": tenant_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Company not found"}), 404

    body = request.get_json(silent=True) or {}
    ico = body.get("ico")
    if not ico:
        return jsonify({"error": "ico is required"}), 400

    from ..services.ares import enrich_company

    result = enrich_company(
        company_id=company_id,
        tenant_id=str(tenant_id),
        name=row[0],
        ico=ico,
        hq_country=row[1],
        domain=row[2],
    )

    return jsonify(result)


@companies_bp.route(
    "/api/companies/<company_id>/enrich-registry/<country>", methods=["POST"]
)
@require_auth
def enrich_registry_country(company_id, country):
    """On-demand registry lookup for a specific country adapter."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text(
            "SELECT name, hq_country, domain FROM companies WHERE id = :id AND tenant_id = :t"
        ),
        {"id": company_id, "t": tenant_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Company not found"}), 404

    from ..services.registries import get_adapter

    adapter = get_adapter(country.upper())
    if not adapter:
        return jsonify({"error": f"No registry adapter for country: {country}"}), 400

    body = request.get_json(silent=True) or {}
    reg_id = body.get("ico") or body.get("reg_id")

    result = adapter.enrich_company(
        company_id=company_id,
        tenant_id=str(tenant_id),
        name=row[0],
        reg_id=reg_id,
        hq_country=row[1],
        domain=row[2],
    )
    return jsonify(result)
