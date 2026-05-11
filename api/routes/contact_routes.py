import json
import math
import re

from flask import Blueprint, g, jsonify, request

from ..auth import require_auth, require_role, resolve_tenant
from ..display import (
    display_contact_source,
    display_department,
    display_icp_fit,
    display_language,
    display_linkedin_activity,
    display_relationship_status,
    display_seniority,
    display_status,
    display_tier,
)
from ..models import db
from ..services.contact_helpers import (
    derive_salutation,
    is_valid_email,
    write_field_change,
)
from ..services.phone_normalize import normalize_phone

contacts_bp = Blueprint("contacts", __name__)


def _compute_contact_score(contact_score, ai_champion_score, authority_score):
    """Compute a composite score from weighted average of non-null scores.

    Weights: contact_score=0.4, ai_champion_score=0.3, authority_score=0.3.
    All input scores are on 0-100 scale.
    Returns integer 0-100, or None if all inputs are null.
    """
    weights = []
    values = []
    if contact_score is not None:
        weights.append(0.4)
        values.append(float(contact_score))
    if ai_champion_score is not None:
        weights.append(0.3)
        values.append(float(ai_champion_score))
    if authority_score is not None:
        weights.append(0.3)
        values.append(float(authority_score))
    if not weights:
        return None
    total_weight = sum(weights)
    weighted_sum = sum(w * v for w, v in zip(weights, values))
    return round(weighted_sum / total_weight)


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


ALLOWED_SORT = {
    "last_name",
    "first_name",
    "job_title",
    "email_address",
    "contact_score",
    "icp_fit",
    "message_status",
    "created_at",
    "seniority_level",
    "department",
    "ai_champion_score",
    "authority_score",
    "linkedin_activity_level",
    "last_enriched_at",
    "company_name",
}

# Map sort keys that don't live on the contacts table
_SORT_COL_MAP = {
    "company_name": "co.name",
}


@contacts_bp.route("/api/contacts", methods=["POST"])
@require_role("editor")
def create_contact():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    first_name = (body.get("first_name") or "").strip()
    last_name = (body.get("last_name") or "").strip()
    if not first_name or not last_name:
        return jsonify({"error": "first_name and last_name are required"}), 400

    allowed_fields = {
        "email_address",
        "job_title",
        "company_id",
        "seniority_level",
        "department",
        "phone_number",
        "notes",
        "address_style",
    }

    # Enum validation
    enum_validators = {
        "address_style": {"tykat", "vykat"},
        "seniority_level": {
            "c_level",
            "vp",
            "director",
            "manager",
            "individual_contributor",
            "founder",
            "other",
        },
        "department": {
            "executive",
            "engineering",
            "product",
            "sales",
            "marketing",
            "customer_success",
            "finance",
            "hr",
            "operations",
            "other",
        },
    }

    columns = ["tenant_id", "first_name", "last_name"]
    placeholders = [":tenant_id", ":first_name", ":last_name"]
    params = {
        "tenant_id": tenant_id,
        "first_name": first_name,
        "last_name": last_name,
    }

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

    # Normalize phone number before saving
    if "phone_number" in params:
        params["phone_number"] = (
            normalize_phone(params["phone_number"]) or params["phone_number"]
        )

    # Validate company_id belongs to tenant
    if "company_id" in params:
        check = db.session.execute(
            db.text("SELECT id FROM companies WHERE id = :cid AND tenant_id = :tid"),
            {"cid": params["company_id"], "tid": tenant_id},
        ).fetchone()
        if not check:
            return jsonify({"error": "Company not found"}), 404

    col_str = ", ".join(columns)
    val_str = ", ".join(placeholders)
    sql = f"INSERT INTO contacts ({col_str}) VALUES ({val_str}) RETURNING id, first_name, last_name, email_address, job_title, company_id, seniority_level, department, phone_number, notes, created_at"
    row = db.session.execute(db.text(sql), params).fetchone()
    db.session.commit()

    return jsonify(
        {
            "id": row.id,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "full_name": f"{row.first_name} {row.last_name}".strip(),
            "email_address": row.email_address,
            "job_title": row.job_title,
            "company_id": row.company_id,
            "seniority_level": row.seniority_level,
            "department": row.department,
            "phone_number": row.phone_number,
            "notes": row.notes,
            "created_at": _iso(row.created_at),
        }
    ), 201


@contacts_bp.route("/api/contacts", methods=["GET"])
@require_auth
def list_contacts():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(100, max(1, request.args.get("page_size", 25, type=int)))
    search = request.args.get("search", "").strip()
    tag_name = request.args.get("tag_name", "").strip()
    owner_name = request.args.get("owner_name", "").strip()
    icp_fit = request.args.get("icp_fit", "").strip()
    message_status = request.args.get("message_status", "").strip()
    company_id = request.args.get("company_id", "").strip()
    sort = request.args.get("sort", "last_name").strip()
    sort_dir = request.args.get("sort_dir", "asc").strip().lower()

    if sort not in ALLOWED_SORT:
        sort = "last_name"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    where = ["ct.tenant_id = :tenant_id"]
    params = {"tenant_id": tenant_id}

    if search:
        where.append(
            "(LOWER(ct.first_name) LIKE LOWER(:search) OR LOWER(ct.last_name) LIKE LOWER(:search)"
            " OR LOWER(ct.email_address) LIKE LOWER(:search)"
            " OR LOWER(ct.job_title) LIKE LOWER(:search))"
        )
        params["search"] = f"%{search}%"
    if tag_name:
        where.append("""EXISTS (
            SELECT 1 FROM contact_tag_assignments cta
            JOIN tags bt ON bt.id = cta.tag_id
            WHERE cta.contact_id = ct.id AND bt.name = :tag_name
        )""")
        params["tag_name"] = tag_name
    if owner_name:
        where.append("o.name = :owner_name")
        params["owner_name"] = owner_name
    if icp_fit:
        where.append("ct.icp_fit = :icp_fit")
        params["icp_fit"] = icp_fit
    if message_status:
        where.append("ct.message_status = :message_status")
        params["message_status"] = message_status
    if company_id:
        where.append("ct.company_id = :company_id")
        params["company_id"] = company_id

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
            # Use json_extract for SQLite compat, ->> for Postgres
            dialect = db.engine.dialect.name
            if dialect == "sqlite":
                where.append(
                    f"json_extract(ct.custom_fields, '$.{field_key}') = :cf_val_{cf_idx}"
                )
            else:
                where.append(
                    f"ct.custom_fields ->> :cf_key_{cf_idx} = :cf_val_{cf_idx}"
                )
                params[f"cf_key_{cf_idx}"] = field_key
            params[f"cf_val_{cf_idx}"] = param_val.strip()
            cf_idx += 1

    # --- Multi-value ICP filters ---
    _add_multi_filter(where, params, "company_status", "co.status", request)
    _add_multi_filter(where, params, "company_tier", "co.tier", request)
    _add_multi_filter(where, params, "industry", "co.industry", request)
    _add_multi_filter(where, params, "company_size", "co.company_size", request)
    _add_multi_filter(where, params, "geo_region", "co.geo_region", request)
    _add_multi_filter(where, params, "revenue_range", "co.revenue_range", request)
    _add_multi_filter(where, params, "seniority_level", "ct.seniority_level", request)
    _add_multi_filter(where, params, "department", "ct.department", request)
    _add_multi_filter(
        where, params, "linkedin_activity", "ct.linkedin_activity_level", request
    )

    # --- JSONB array filters (skills / interests from contact_enrichment) ---
    skills_raw = request.args.get("skills", "").strip()
    if skills_raw:
        skills_vals = [v.strip() for v in skills_raw.split(",") if v.strip()]
        if skills_vals:
            skills_exclude = (
                request.args.get("skills_exclude", "").strip().lower() == "true"
            )
            skills_clauses = []
            for i, v in enumerate(skills_vals):
                params[f"skill_{i}"] = v.lower()
                skills_clauses.append(f"LOWER(CAST(sk.value AS TEXT)) = :skill_{i}")
            combined_skills = " OR ".join(skills_clauses)
            if skills_exclude:
                where.append(
                    f"""NOT EXISTS (
                        SELECT 1 FROM contact_enrichment ce_sk,
                        LATERAL jsonb_array_elements_text(ce_sk.expertise_areas) sk(value)
                        WHERE ce_sk.contact_id = ct.id AND ({combined_skills})
                    )"""
                )
            else:
                where.append(
                    f"""EXISTS (
                        SELECT 1 FROM contact_enrichment ce_sk,
                        LATERAL jsonb_array_elements_text(ce_sk.expertise_areas) sk(value)
                        WHERE ce_sk.contact_id = ct.id AND ({combined_skills})
                    )"""
                )

    interests_raw = request.args.get("interests", "").strip()
    if interests_raw:
        interests_vals = [v.strip() for v in interests_raw.split(",") if v.strip()]
        if interests_vals:
            interests_exclude = (
                request.args.get("interests_exclude", "").strip().lower() == "true"
            )
            interests_clauses = []
            for i, v in enumerate(interests_vals):
                params[f"interest_{i}"] = v.lower()
                interests_clauses.append(
                    f"LOWER(CAST(ti.value AS TEXT)) = :interest_{i}"
                )
            combined_interests = " OR ".join(interests_clauses)
            if interests_exclude:
                where.append(
                    f"""NOT EXISTS (
                        SELECT 1 FROM contact_enrichment ce_ti,
                        LATERAL jsonb_array_elements_text(ce_ti.technology_interests) ti(value)
                        WHERE ce_ti.contact_id = ct.id AND ({combined_interests})
                    )"""
                )
            else:
                where.append(
                    f"""EXISTS (
                        SELECT 1 FROM contact_enrichment ce_ti,
                        LATERAL jsonb_array_elements_text(ce_ti.technology_interests) ti(value)
                        WHERE ce_ti.contact_id = ct.id AND ({combined_interests})
                    )"""
                )

    # Job titles filter (ILIKE match)
    job_titles_raw = request.args.get("job_titles", "").strip()
    if job_titles_raw:
        titles = [t.strip() for t in job_titles_raw.split(",") if t.strip()]
        if titles:
            job_exclude = (
                request.args.get("job_titles_exclude", "").strip().lower() == "true"
            )
            title_clauses = []
            for i, t in enumerate(titles):
                params[f"jt_{i}"] = f"%{t}%"
                title_clauses.append(f"LOWER(ct.job_title) LIKE LOWER(:jt_{i})")
            combined = " OR ".join(title_clauses)
            if job_exclude:
                where.append(f"(ct.job_title IS NULL OR NOT ({combined}))")
            else:
                where.append(f"({combined})")

    # Campaign exclusion
    exclude_campaign_id = request.args.get("exclude_campaign_id", "").strip()

    where_clause = " AND ".join(where)

    # Build JOINs - always join companies for potential company filters
    joins = """
        LEFT JOIN companies co ON ct.company_id = co.id
        LEFT JOIN owners o ON ct.owner_id = o.id
    """

    # Campaign exclusion join
    if exclude_campaign_id:
        joins += """
        LEFT JOIN campaign_contacts cc
            ON cc.contact_id = ct.id AND cc.campaign_id = :excl_campaign_id
        """
        where.append("cc.id IS NULL")
        params["excl_campaign_id"] = exclude_campaign_id
        where_clause = " AND ".join(where)

    # Count
    total = (
        db.session.execute(
            db.text(f"""
            SELECT COUNT(*)
            FROM contacts ct
            {joins}
            WHERE {where_clause}
        """),
            params,
        ).scalar()
        or 0
    )

    pages = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size

    sort_col = _SORT_COL_MAP.get(sort, f"ct.{sort}")
    # Append `ct.id ASC` as a unique tiebreaker so pagination stays stable when
    # the primary sort column has tied/NULL values (otherwise duplicate rows can
    # appear across page boundaries). See BL-1116.
    order = f"{sort_col} {'ASC' if sort_dir == 'asc' else 'DESC'} NULLS LAST, ct.id ASC"

    rows = db.session.execute(
        db.text(f"""
            SELECT
                ct.id, ct.first_name, ct.last_name, ct.job_title,
                co.id AS company_id, co.name AS company_name,
                ct.email_address,
                COALESCE(ct.contact_score, ce.contact_score) AS contact_score,
                COALESCE(CAST(ct.icp_fit AS TEXT), ce.icp_fit) AS icp_fit,
                ct.message_status,
                o.name AS owner_name,
                COALESCE(CAST(ct.seniority_level AS TEXT), ce.seniority) AS seniority_level,
                COALESCE(CAST(ct.department AS TEXT), ce.department) AS department,
                ct.location_city, ct.location_country,
                ct.linkedin_url, ct.phone_number,
                ct.ai_champion_score, ct.authority_score,
                ct.linkedin_activity_level, ct.language,
                ct.contact_source,
                ct.address_style,
                co.tier AS company_tier,
                co.status AS company_status_raw,
                ct.processed_enrich,
                ct.last_enriched_at
            FROM contacts ct
            LEFT JOIN contact_enrichment ce ON ce.contact_id = ct.id
            {joins}
            WHERE {where_clause}
            ORDER BY {order}
            LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": page_size, "offset": offset},
    ).fetchall()

    # Collect contact IDs for batch tag lookup
    contact_ids = [str(r[0]) for r in rows]
    tag_map: dict[str, list[str]] = {cid: [] for cid in contact_ids}
    if contact_ids:
        # Use IN clause with positional params for SQLite compat
        placeholders = ", ".join(f":cid_{i}" for i in range(len(contact_ids)))
        tag_params = {f"cid_{i}": cid for i, cid in enumerate(contact_ids)}
        tag_rows = db.session.execute(
            db.text(f"""
                SELECT cta.contact_id, t.name
                FROM contact_tag_assignments cta
                JOIN tags t ON t.id = cta.tag_id
                WHERE cta.contact_id IN ({placeholders})
                ORDER BY t.name
            """),
            tag_params,
        ).fetchall()
        for tr in tag_rows:
            tag_map.setdefault(str(tr[0]), []).append(tr[1])

    # Batch lookup: which contacts have enrichment data
    enrich_map: dict[str, bool] = {cid: False for cid in contact_ids}
    if contact_ids:
        placeholders = ", ".join(f":eid_{i}" for i in range(len(contact_ids)))
        enrich_params = {f"eid_{i}": cid for i, cid in enumerate(contact_ids)}
        enrich_rows = db.session.execute(
            db.text(f"""
                SELECT ce.contact_id
                FROM contact_enrichment ce
                WHERE ce.contact_id IN ({placeholders})
            """),
            enrich_params,
        ).fetchall()
        for er in enrich_rows:
            enrich_map[str(er[0])] = True

    def _enrichment_status(processed_enrich, has_enrichment, last_enriched_at):
        """Derive a compact enrichment status label."""
        if has_enrichment:
            return "enriched"
        if processed_enrich:
            return "processed"
        if last_enriched_at:
            return "partial"
        return "none"

    contacts = []
    for r in rows:
        cid = str(r[0])
        first = r[1] or ""
        last = r[2] or ""
        full_name = (first + " " + last).strip() if last else first
        tag_names = tag_map.get(cid, [])
        raw_contact_score = r[7]
        raw_ai_champion = int(r[17]) if r[17] is not None else None
        raw_authority = int(r[18]) if r[18] is not None else None
        has_enrichment = enrich_map.get(cid, False)
        processed = bool(r[25]) if r[25] is not None else False
        last_enriched = r[26]
        contacts.append(
            {
                "id": cid,
                "full_name": full_name,
                "first_name": first,
                "last_name": last,
                "job_title": r[3],
                "company_id": str(r[4]) if r[4] else None,
                "company_name": r[5],
                "email_address": r[6],
                "contact_score": raw_contact_score,
                "score": _compute_contact_score(
                    raw_contact_score, raw_ai_champion, raw_authority
                ),
                "icp_fit": display_icp_fit(r[8]),
                "message_status": r[9],
                "owner_name": r[10],
                "tag_name": tag_names[0] if tag_names else None,
                "tag_names": tag_names,
                "seniority_level": display_seniority(r[11]),
                "department": display_department(r[12]),
                "location_city": r[13],
                "location_country": r[14],
                "linkedin_url": r[15],
                "phone_number": r[16],
                "ai_champion_score": raw_ai_champion,
                "authority_score": raw_authority,
                "linkedin_activity_level": display_linkedin_activity(r[19]),
                "language": display_language(r[20]),
                "contact_source": display_contact_source(r[21]),
                "address_style": r[22],
                "company_tier": display_tier(r[23]),
                "company_status": display_status(r[24])
                if r[24]
                else None,  # co.status raw
                "enrichment_status": _enrichment_status(
                    processed, has_enrichment, last_enriched
                ),
                "last_enriched_at": _iso(last_enriched),
            }
        )

    return jsonify(
        {
            "contacts": contacts,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    )


@contacts_bp.route("/api/contacts/<contact_id>", methods=["GET"])
@require_auth
def get_contact(contact_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text("""
            SELECT
                ct.id, ct.first_name, ct.last_name, ct.job_title,
                ct.email_address, ct.linkedin_url, ct.phone_number,
                ct.profile_photo_url,
                COALESCE(CAST(ct.seniority_level AS TEXT), ce.seniority) AS seniority_level,
                COALESCE(CAST(ct.department AS TEXT), ce.department) AS department,
                ct.location_city, ct.location_country,
                COALESCE(CAST(ct.icp_fit AS TEXT), ce.icp_fit) AS icp_fit,
                ct.relationship_status,
                ct.contact_source, ct.language, ct.message_status,
                ct.ai_champion, ct.ai_champion_score,
                ct.authority_score,
                COALESCE(ct.contact_score, ce.contact_score) AS contact_score,
                ct.enrichment_cost_usd, ct.processed_enrich,
                ct.email_lookup, ct.duplicity_check,
                ct.duplicity_conflict, ct.duplicity_detail,
                ct.notes, ct.error, ct.custom_fields,
                ct.created_at, ct.updated_at,
                ct.last_enriched_at, ct.employment_status,
                ct.employment_verified_at,
                co.id AS company_id, co.name AS company_name,
                co.domain AS company_domain, co.status AS company_status,
                co.tier AS company_tier,
                o.name AS owner_name, b.name AS tag_name,
                ct.address_style, ct.salutation, ct.salutation_overridden
            FROM contacts ct
            LEFT JOIN companies co ON ct.company_id = co.id
            LEFT JOIN owners o ON ct.owner_id = o.id
            LEFT JOIN tags b ON ct.tag_id = b.id
            LEFT JOIN contact_enrichment ce ON ce.contact_id = ct.id
            WHERE ct.id = :id AND ct.tenant_id = :tenant_id
        """),
        {"id": contact_id, "tenant_id": tenant_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Contact not found"}), 404

    first = row[1] or ""
    last = row[2] or ""
    raw_contact_score_d = row[20]
    raw_ai_champion_d = row[18]
    raw_authority_d = row[19]
    contact = {
        "id": str(row[0]),
        "first_name": first,
        "last_name": last,
        "full_name": (first + " " + last).strip() if last else first,
        "job_title": row[3],
        "email_address": row[4],
        "linkedin_url": row[5],
        "phone_number": row[6],
        "profile_photo_url": row[7],
        "seniority_level": display_seniority(row[8]),
        "department": display_department(row[9]),
        "location_city": row[10],
        "location_country": row[11],
        "icp_fit": display_icp_fit(row[12]),
        "relationship_status": display_relationship_status(row[13]),
        "contact_source": display_contact_source(row[14]),
        "language": display_language(row[15]),
        "message_status": row[16],
        "ai_champion": row[17],
        "ai_champion_score": raw_ai_champion_d,
        "authority_score": raw_authority_d,
        "contact_score": raw_contact_score_d,
        "score": _compute_contact_score(
            raw_contact_score_d, raw_ai_champion_d, raw_authority_d
        ),
        "enrichment_cost_usd": float(row[21]) if row[21] is not None else None,
        "processed_enrich": row[22],
        "email_lookup": row[23],
        "duplicity_check": row[24],
        "duplicity_conflict": row[25],
        "duplicity_detail": row[26],
        "notes": row[27],
        "error": row[28],
        "custom_fields": _parse_jsonb(row[29]),
        "created_at": _iso(row[30]),
        "updated_at": _iso(row[31]),
        "last_enriched_at": _iso(row[32]),
        "employment_status": row[33],
        "employment_verified_at": _iso(row[34]),
        "company": {
            "id": str(row[35]),
            "name": row[36],
            "domain": row[37],
            "status": display_status(row[38]),
            "tier": display_tier(row[39]),
        }
        if row[35]
        else None,
        "owner_name": row[40],
        "tag_name": row[41],
        "address_style": row[42],
        "salutation": row[43],
        "salutation_overridden": bool(row[44]) if row[44] is not None else False,
    }

    # Stage completions (DAG tracking)
    sc_rows = db.session.execute(
        db.text("""
            SELECT stage, status, completed_at, cost_usd, error
            FROM entity_stage_completions
            WHERE entity_type = 'contact' AND entity_id = :id
            ORDER BY completed_at NULLS LAST
        """),
        {"id": contact_id},
    ).fetchall()
    contact["stage_completions"] = [
        {
            "stage": r[0],
            "status": r[1],
            "completed_at": _iso(r[2]),
            "cost_usd": float(r[3]) if r[3] is not None else None,
            "error": r[4],
        }
        for r in sc_rows
    ]

    # Contact enrichment
    enrich_row = db.session.execute(
        db.text("""
            SELECT person_summary, linkedin_profile_summary,
                   relationship_synthesis,
                   ai_champion, ai_champion_score, authority_score,
                   career_trajectory, previous_companies,
                   speaking_engagements, publications,
                   twitter_handle, github_username,
                   education, certifications, expertise_areas,
                   budget_signals, buying_signals, pain_indicators,
                   technology_interests, personalization_angle,
                   connection_points, conversation_starters,
                   objection_prediction,
                   enriched_at, enrichment_cost_usd
            FROM contact_enrichment
            WHERE contact_id = :id
        """),
        {"id": contact_id},
    ).fetchone()

    if enrich_row:
        contact["enrichment"] = {
            "person_summary": enrich_row[0],
            "linkedin_profile_summary": enrich_row[1],
            "relationship_synthesis": enrich_row[2],
            "ai_champion": enrich_row[3],
            "ai_champion_score": enrich_row[4],
            "authority_score": enrich_row[5],
            "career_trajectory": enrich_row[6],
            "previous_companies": _parse_jsonb(enrich_row[7]),
            "speaking_engagements": enrich_row[8],
            "publications": enrich_row[9],
            "twitter_handle": enrich_row[10],
            "github_username": enrich_row[11],
            "education": enrich_row[12],
            "certifications": enrich_row[13],
            "expertise_areas": _parse_jsonb(enrich_row[14]),
            "budget_signals": enrich_row[15],
            "buying_signals": enrich_row[16],
            "pain_indicators": enrich_row[17],
            "technology_interests": _parse_jsonb(enrich_row[18]),
            "personalization_angle": enrich_row[19],
            "connection_points": _parse_jsonb(enrich_row[20]),
            "conversation_starters": enrich_row[21],
            "objection_prediction": enrich_row[22],
            "enriched_at": _iso(enrich_row[23]),
            "enrichment_cost_usd": float(enrich_row[24])
            if enrich_row[24] is not None
            else None,
        }
    else:
        contact["enrichment"] = None

    # Messages
    msg_rows = db.session.execute(
        db.text("""
            SELECT m.id, m.channel, m.sequence_step, m.variant,
                   m.subject, m.status, m.tone
            FROM messages m
            WHERE m.contact_id = :id
            ORDER BY m.sequence_step, m.variant
        """),
        {"id": contact_id},
    ).fetchall()
    contact["messages"] = [
        {
            "id": str(r[0]),
            "channel": r[1],
            "sequence_step": r[2],
            "variant": (r[3] or "a").upper(),
            "subject": r[4],
            "status": r[5],
            "tone": r[6],
        }
        for r in msg_rows
    ]

    # Email activity (send logs joined through messages → campaigns).
    # BL-1029: contact history is the "all attempts" audit view — it keeps
    # superseded rows so users can see the full retry trail. The
    # `superseded_at` column lets the UI grey-out / flag retried attempts.
    email_rows = db.session.execute(
        db.text("""
            SELECT c.name AS campaign_name,
                   m.subject,
                   esl.status,
                   esl.sent_at,
                   esl.delivered_at,
                   esl.opened_at,
                   esl.open_count,
                   esl.clicked_at,
                   esl.click_count,
                   esl.bounced_at,
                   esl.superseded_at
            FROM email_send_log esl
            JOIN messages m ON m.id = esl.message_id
            LEFT JOIN campaign_contacts cc ON cc.id = m.campaign_contact_id
            LEFT JOIN campaigns c ON c.id = cc.campaign_id
            WHERE m.contact_id = :id
            ORDER BY esl.sent_at DESC
        """),
        {"id": contact_id},
    ).fetchall()
    contact["email_activity"] = [
        {
            "campaign_name": r[0],
            "subject": r[1],
            "status": r[2],
            "sent_at": _iso(r[3]),
            "delivered_at": _iso(r[4]),
            "opened_at": _iso(r[5]),
            "open_count": r[6] or 0,
            "clicked_at": _iso(r[7]),
            "click_count": r[8] or 0,
            "bounced_at": _iso(r[9]),
            "superseded_at": _iso(r[10]),
        }
        for r in email_rows
    ]

    return jsonify(contact)


@contacts_bp.route("/api/contacts/<contact_id>", methods=["DELETE"])
@require_role("editor")
def delete_contact(contact_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify contact belongs to tenant
    row = db.session.execute(
        db.text("SELECT id FROM contacts WHERE id = :id AND tenant_id = :tid"),
        {"id": contact_id, "tid": str(tenant_id)},
    ).fetchone()
    if not row:
        return jsonify({"error": "Contact not found"}), 404

    params = {"id": contact_id, "tid": str(tenant_id)}

    # Delete junction records first
    db.session.execute(
        db.text(
            "DELETE FROM contact_tag_assignments WHERE contact_id = :id AND tenant_id = :tid"
        ),
        params,
    )
    db.session.execute(
        db.text(
            "DELETE FROM campaign_contacts WHERE contact_id = :id AND tenant_id = :tid"
        ),
        params,
    )

    # Delete the contact
    db.session.execute(
        db.text("DELETE FROM contacts WHERE id = :id AND tenant_id = :tid"),
        params,
    )
    db.session.commit()

    return jsonify({"deleted": True})


@contacts_bp.route("/api/contacts/<contact_id>", methods=["PATCH"])
@require_role("editor")
def update_contact(contact_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    allowed = {
        "notes",
        "icp_fit",
        "message_status",
        "relationship_status",
        "seniority_level",
        "department",
        "contact_source",
        "language",
        "first_name",
        "last_name",
        "email_address",
        "job_title",
        "phone_number",
        "address_style",
        "salutation",
    }
    fields = {k: v for k, v in body.items() if k in allowed}

    # Normalize phone number before saving
    if "phone_number" in fields and fields["phone_number"] is not None:
        fields["phone_number"] = normalize_phone(fields["phone_number"])

    # Validate email format (cheap regex; reject obvious garbage before commit)
    if "email_address" in fields:
        if not is_valid_email(fields["email_address"]):
            return jsonify(
                {
                    "error": "Invalid email format",
                    "field": "email_address",
                }
            ), 400

    custom_fields_update = body.get("custom_fields")

    if not fields and not custom_fields_update:
        return jsonify({"error": "No valid fields to update"}), 400

    # Enum validation for fields with finite allowed values
    contact_enum_validators = {
        "icp_fit": {"strong_fit", "moderate_fit", "weak_fit", "unknown"},
        "seniority_level": {
            "c_level",
            "vp",
            "director",
            "manager",
            "individual_contributor",
            "founder",
            "other",
        },
        "department": {
            "executive",
            "engineering",
            "product",
            "sales",
            "marketing",
            "customer_success",
            "finance",
            "hr",
            "operations",
            "other",
        },
        "message_status": {
            "not_started",
            "generating",
            "pending_review",
            "approved",
            "sent",
            "replied",
            "no_channel",
            "generation_failed",
        },
        "language": {
            "en",
            "cs",
            "da",
            "de",
            "es",
            "fi",
            "fr",
            "it",
            "nl",
            "no",
            "pl",
            "pt",
            "sv",
        },
        "contact_source": {
            "inbound",
            "outbound",
            "referral",
            "event",
            "social",
            "other",
        },
        "relationship_status": {
            "prospect",
            "active",
            "dormant",
            "former",
            "partner",
            "internal",
        },
        "address_style": {"tykat", "vykat"},
    }
    for field, value in fields.items():
        if (
            field in contact_enum_validators
            and value not in contact_enum_validators[field]
        ):
            return jsonify(
                {
                    "error": f"Invalid value '{value}' for field '{field}'",
                    "field": field,
                    "allowed": sorted(contact_enum_validators[field]),
                }
            ), 400

    # Pull current row including the salutation_overridden flag so we can
    # decide whether to re-derive on a first_name edit, and so we can diff
    # every editable field for the audit log.
    existing = db.session.execute(
        db.text(
            """
            SELECT
                id,
                custom_fields,
                first_name,
                last_name,
                email_address,
                job_title,
                phone_number,
                notes,
                icp_fit,
                message_status,
                relationship_status,
                seniority_level,
                department,
                contact_source,
                language,
                address_style,
                salutation,
                salutation_overridden
            FROM contacts
            WHERE id = :id AND tenant_id = :t
            """
        ),
        {"id": contact_id, "t": tenant_id},
    ).fetchone()
    if not existing:
        return jsonify({"error": "Contact not found"}), 404

    existing_map = {
        "first_name": existing[2],
        "last_name": existing[3],
        "email_address": existing[4],
        "job_title": existing[5],
        "phone_number": existing[6],
        "notes": existing[7],
        "icp_fit": existing[8],
        "message_status": existing[9],
        "relationship_status": existing[10],
        "seniority_level": existing[11],
        "department": existing[12],
        "contact_source": existing[13],
        "language": existing[14],
        "address_style": existing[15],
        "salutation": existing[16],
    }
    salutation_overridden = bool(existing[17])

    # Duplicate-email guard: if email is changing to one already used by a
    # different contact in the same tenant, return 409 with a warning the UI
    # can confirm-override via ?confirm_duplicate=true.
    if "email_address" in fields and fields["email_address"]:
        new_email = (fields["email_address"] or "").strip()
        if new_email and new_email != (existing_map.get("email_address") or ""):
            confirm = request.args.get("confirm_duplicate", "").strip().lower() in {
                "true",
                "1",
                "yes",
            }
            dupe = db.session.execute(
                db.text(
                    """
                    SELECT id, first_name, last_name
                    FROM contacts
                    WHERE tenant_id = :t
                      AND id != :id
                      AND LOWER(email_address) = LOWER(:email)
                    LIMIT 1
                    """
                ),
                {"t": tenant_id, "id": contact_id, "email": new_email},
            ).fetchone()
            if dupe and not confirm:
                full_name = f"{dupe[1] or ''} {dupe[2] or ''}".strip() or "(no name)"
                return jsonify(
                    {
                        "warning": "duplicate",
                        "code": "duplicate_email",
                        "error": (
                            f"Email already in use by {full_name}. "
                            "Confirm to save anyway."
                        ),
                        "details": {
                            "existing_id": dupe[0],
                            "existing_name": full_name,
                        },
                    }
                ), 409

    # Salutation auto-derive rules:
    #   * If client explicitly sets `salutation`, mark as overridden.
    #   * If client edits `first_name` AND salutation has NOT been overridden,
    #     recompute the auto-vocative form so the cached field stays fresh.
    if "salutation" in fields:
        # Treat empty string as "clear and let auto-derive run again": reset flag.
        if fields["salutation"] in (None, ""):
            salutation_overridden = False
        else:
            salutation_overridden = True
        fields["salutation_overridden"] = salutation_overridden
    elif "first_name" in fields and not salutation_overridden:
        derived = derive_salutation(fields["first_name"])
        if derived is not None:
            fields["salutation"] = derived

    set_parts = []
    params = {"id": contact_id}
    for k, v in fields.items():
        set_parts.append(f"{k} = :{k}")
        params[k] = v

    if custom_fields_update and isinstance(custom_fields_update, dict):
        existing_cf = _parse_jsonb(existing[1])
        existing_cf.update(custom_fields_update)
        set_parts.append("custom_fields = :custom_fields")
        params["custom_fields"] = json.dumps(existing_cf)

    db.session.execute(
        db.text(f"UPDATE contacts SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )

    # Write audit rows for every changed editable field. `salutation_overridden`
    # is meta -- we don't audit it; the salutation change itself carries
    # the provenance.
    changed_by = getattr(getattr(g, "current_user", None), "id", None)
    for field_name, new_value in fields.items():
        if field_name == "salutation_overridden":
            continue
        old_value = existing_map.get(field_name)
        if old_value == new_value:
            continue
        write_field_change(
            tenant_id=tenant_id,
            entity_type="contact",
            entity_id=contact_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
        )

    db.session.commit()

    return jsonify({"ok": True})


@contacts_bp.route("/api/contacts/filter-counts", methods=["POST"])
@require_auth
def filter_counts():
    """Return faceted counts for all filterable fields.

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
    exclude_campaign_id = (
        body.get("exclude_campaign_id", "").strip()
        if body.get("exclude_campaign_id")
        else ""
    )

    # Define all facet fields with their column references
    # JSONB array facet fields (from contact_enrichment)
    JSONB_FACET_FIELDS = {
        "skills": "expertise_areas",
        "interests": "technology_interests",
    }

    FACET_FIELDS = {
        "company_status": "co.status",
        "company_tier": "co.tier",
        "industry": "co.industry",
        "company_size": "co.company_size",
        "geo_region": "co.geo_region",
        "revenue_range": "co.revenue_range",
        "seniority_level": "ct.seniority_level",
        "department": "ct.department",
        "linkedin_activity": "ct.linkedin_activity_level",
    }

    def _build_base_where(params, exclude_facet=None):
        """Build WHERE clause applying all filters EXCEPT exclude_facet."""
        where = ["ct.tenant_id = :tenant_id"]
        params["tenant_id"] = tenant_id

        if search:
            where.append(
                "(LOWER(ct.first_name) LIKE LOWER(:search) OR LOWER(ct.last_name) LIKE LOWER(:search)"
                " OR LOWER(ct.email_address) LIKE LOWER(:search)"
                " OR LOWER(ct.job_title) LIKE LOWER(:search))"
            )
            params["search"] = f"%{search}%"
        if tag_name:
            where.append("""EXISTS (
                SELECT 1 FROM contact_tag_assignments cta
                JOIN tags bt ON bt.id = cta.tag_id
                WHERE cta.contact_id = ct.id AND bt.name = :tag_name
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

        # Apply JSONB array filters (skills / interests) EXCEPT the one being faceted
        for jf_key, jf_column in JSONB_FACET_FIELDS.items():
            if jf_key == exclude_facet:
                continue
            jf = filters.get(jf_key, {})
            jf_values = jf.get("values", [])[:100] if isinstance(jf, dict) else []
            if not jf_values:
                continue
            jf_exclude = jf.get("exclude", False) if isinstance(jf, dict) else False
            jf_clauses = []
            for i, v in enumerate(jf_values):
                params[f"{jf_key}_{i}"] = v.lower()
                jf_clauses.append(f"LOWER(CAST(jfv.value AS TEXT)) = :{jf_key}_{i}")
            combined_jf = " OR ".join(jf_clauses)
            if jf_exclude:
                where.append(
                    f"""NOT EXISTS (
                        SELECT 1 FROM contact_enrichment ce_jf,
                        LATERAL jsonb_array_elements_text(ce_jf.{jf_column}) jfv(value)
                        WHERE ce_jf.contact_id = ct.id AND ({combined_jf})
                    )"""
                )
            else:
                where.append(
                    f"""EXISTS (
                        SELECT 1 FROM contact_enrichment ce_jf,
                        LATERAL jsonb_array_elements_text(ce_jf.{jf_column}) jfv(value)
                        WHERE ce_jf.contact_id = ct.id AND ({combined_jf})
                    )"""
                )

        return " AND ".join(where)

    joins = """
        LEFT JOIN companies co ON ct.company_id = co.id
        LEFT JOIN owners o ON ct.owner_id = o.id
    """
    if exclude_campaign_id:
        joins += """
        LEFT JOIN campaign_contacts cc
            ON cc.contact_id = ct.id AND cc.campaign_id = :excl_campaign_id
        """

    facets = {}
    for field_key, column in FACET_FIELDS.items():
        params = {}
        where_clause = _build_base_where(params, exclude_facet=field_key)
        if exclude_campaign_id:
            params["excl_campaign_id"] = exclude_campaign_id
            extra_where = " AND cc.id IS NULL"
        else:
            extra_where = ""

        rows = db.session.execute(
            db.text(f"""
                SELECT {column} AS val, COUNT(*) AS cnt
                FROM contacts ct
                {joins}
                WHERE {where_clause}{extra_where}
                  AND {column} IS NOT NULL
                GROUP BY {column}
                ORDER BY cnt DESC
            """),
            params,
        ).fetchall()
        facets[field_key] = [{"value": r[0], "count": r[1]} for r in rows]

    # JSONB array facet counts (skills / interests)
    # Uses PostgreSQL-specific LATERAL + jsonb_array_elements_text;
    # gracefully returns empty facets on engines that lack these (e.g. SQLite in tests).
    for jf_key, jf_column in JSONB_FACET_FIELDS.items():
        params = {}
        where_clause = _build_base_where(params, exclude_facet=jf_key)
        if exclude_campaign_id:
            params["excl_campaign_id"] = exclude_campaign_id
            extra_where = " AND cc.id IS NULL"
        else:
            extra_where = ""

        try:
            rows = db.session.execute(
                db.text(f"""
                    SELECT elem.value AS val, COUNT(DISTINCT ct.id) AS cnt
                    FROM contacts ct
                    {joins}
                    JOIN contact_enrichment ce_fc ON ce_fc.contact_id = ct.id
                    CROSS JOIN LATERAL jsonb_array_elements_text(ce_fc.{jf_column}) elem(value)
                    WHERE {where_clause}{extra_where}
                      AND ce_fc.{jf_column} IS NOT NULL
                    GROUP BY elem.value
                    ORDER BY cnt DESC
                    LIMIT 50
                """),
                params,
            ).fetchall()
            facets[jf_key] = [{"value": r[0], "count": r[1]} for r in rows]
        except Exception:
            # SQLite or other engines without LATERAL/jsonb support
            db.session.rollback()
            facets[jf_key] = []

    # Total count with ALL filters applied
    total_params = {}
    total_where = _build_base_where(total_params)
    if exclude_campaign_id:
        total_params["excl_campaign_id"] = exclude_campaign_id
        extra_where = " AND cc.id IS NULL"
    else:
        extra_where = ""

    total = (
        db.session.execute(
            db.text(f"""
            SELECT COUNT(*)
            FROM contacts ct
            {joins}
            WHERE {total_where}{extra_where}
        """),
            total_params,
        ).scalar()
        or 0
    )

    return jsonify({"total": total, "facets": facets})


@contacts_bp.route("/api/contacts/job-titles", methods=["GET"])
@require_auth
def job_title_suggestions():
    """Return distinct job titles matching a query, with counts."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    q = request.args.get("q", "").strip()
    limit = min(50, max(1, request.args.get("limit", 20, type=int)))

    if len(q) < 2:
        return jsonify({"titles": []})

    rows = db.session.execute(
        db.text("""
            SELECT ct.job_title, COUNT(*) AS cnt
            FROM contacts ct
            WHERE ct.tenant_id = :tenant_id
              AND ct.job_title IS NOT NULL
              AND LOWER(ct.job_title) LIKE LOWER(:q)
            GROUP BY ct.job_title
            ORDER BY cnt DESC
            LIMIT :limit
        """),
        {"tenant_id": tenant_id, "q": f"%{q}%", "limit": limit},
    ).fetchall()

    return jsonify({"titles": [{"title": r[0], "count": r[1]} for r in rows]})


# ── Contact Search API ──────────────────────────────────


@contacts_bp.route("/api/contacts/search", methods=["POST"])
@require_auth
def search_contacts():
    """Faceted contact search with counts per filter dimension."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    filters = body.get("filters", {})
    text_search = (body.get("text_search") or "").strip()
    page = max(1, body.get("page", 1))
    page_size = min(100, max(1, body.get("page_size", 25)))
    sort_by = body.get("sort_by", "contact_score")
    sort_dir = body.get("sort_dir", "desc").lower()
    include_facets = body.get("include_facets", True)

    ALLOWED_SORT = {
        "contact_score",
        "ai_champion_score",
        "first_name",
        "last_name",
        "company_name",
        "created_at",
    }
    if sort_by not in ALLOWED_SORT:
        sort_by = "contact_score"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    SEARCH_FACETS = {
        "seniority_level": "ct.seniority_level",
        "department": "ct.department",
        "industry": "co.industry",
        "tier": "co.tier",
        "company_size": "co.company_size",
        "geo_region": "co.geo_region",
        "icp_fit": "ct.icp_fit",
    }

    def _search_where(params, exclude_facet=None):
        where = ["ct.tenant_id = :tenant_id"]
        params["tenant_id"] = tenant_id

        if text_search:
            where.append(
                "(LOWER(ct.first_name) LIKE LOWER(:q)"
                " OR LOWER(ct.last_name) LIKE LOWER(:q)"
                " OR LOWER(ct.email_address) LIKE LOWER(:q)"
                " OR LOWER(ct.job_title) LIKE LOWER(:q)"
                " OR LOWER(co.name) LIKE LOWER(:q))"
            )
            params["q"] = f"%{text_search}%"

        for key, col in SEARCH_FACETS.items():
            if key == exclude_facet:
                continue
            vals = filters.get(key)
            if not vals:
                continue
            if not isinstance(vals, list):
                vals = [vals]
            vals = vals[:50]
            placeholders = ", ".join(f":sf_{key}_{i}" for i in range(len(vals)))
            for i, v in enumerate(vals):
                params[f"sf_{key}_{i}"] = v
            where.append(f"{col} IN ({placeholders})")

        if filters.get("min_contact_score") is not None:
            where.append("ct.contact_score >= :min_score")
            params["min_score"] = filters["min_contact_score"]

        if filters.get("enrichment_ready"):
            where.append(
                """EXISTS (
                SELECT 1 FROM entity_stage_completions esc
                WHERE esc.entity_id = ct.id
                  AND esc.stage = 'person'
                  AND esc.status = 'completed'
            )"""
            )

        if filters.get("exclude_in_campaigns"):
            where.append(
                """NOT EXISTS (
                SELECT 1 FROM campaign_contacts cc2
                JOIN campaigns cmp ON cmp.id = cc2.campaign_id
                WHERE cc2.contact_id = ct.id
                  AND cmp.status NOT IN ('archived', 'draft')
            )"""
            )

        return " AND ".join(where)

    joins = """
        LEFT JOIN companies co ON ct.company_id = co.id
        LEFT JOIN owners o ON ct.owner_id = o.id
    """

    sort_col_map = {
        "contact_score": "ct.contact_score",
        "ai_champion_score": "ct.ai_champion_score",
        "first_name": "ct.first_name",
        "last_name": "ct.last_name",
        "company_name": "co.name",
        "created_at": "ct.created_at",
    }
    order_col = sort_col_map.get(sort_by, "ct.contact_score")

    # Main query
    main_params = {}
    main_where = _search_where(main_params)

    total = (
        db.session.execute(
            db.text(
                f"""
            SELECT COUNT(*)
            FROM contacts ct {joins}
            WHERE {main_where}
        """
            ),
            main_params,
        ).scalar()
        or 0
    )

    offset = (page - 1) * page_size
    main_params["limit"] = page_size
    main_params["offset"] = offset

    rows = db.session.execute(
        db.text(
            f"""
            SELECT
                ct.id, ct.first_name, ct.last_name, ct.email_address,
                ct.job_title, ct.linkedin_url, ct.seniority_level,
                ct.department, ct.contact_score, ct.ai_champion_score,
                ct.icp_fit, ct.created_at,
                co.id AS company_id, co.name AS company_name,
                co.industry, co.tier, co.company_size, co.geo_region
            FROM contacts ct {joins}
            WHERE {main_where}
            ORDER BY {order_col} {sort_dir} NULLS LAST, ct.id ASC
            LIMIT :limit OFFSET :offset
        """
        ),
        main_params,
    ).fetchall()

    # Enrichment readiness + active campaigns for returned contacts
    contact_ids = [r[0] for r in rows]
    enrichment_map = {}
    campaign_map = {}
    if contact_ids:
        id_placeholders = ", ".join(f":cid_{i}" for i in range(len(contact_ids)))
        id_params = {f"cid_{i}": cid for i, cid in enumerate(contact_ids)}

        enrich_rows = db.session.execute(
            db.text(
                f"""
                SELECT entity_id, stage, status
                FROM entity_stage_completions
                WHERE entity_id IN ({id_placeholders})
            """
            ),
            id_params,
        ).fetchall()
        for er in enrich_rows:
            enrichment_map.setdefault(str(er[0]), []).append(
                {"stage": er[1], "status": er[2]}
            )

        camp_rows = db.session.execute(
            db.text(
                f"""
                SELECT cc2.contact_id, cmp.id, cmp.name, cmp.status
                FROM campaign_contacts cc2
                JOIN campaigns cmp ON cmp.id = cc2.campaign_id
                WHERE cc2.contact_id IN ({id_placeholders})
                  AND cmp.status NOT IN ('archived')
            """
            ),
            id_params,
        ).fetchall()
        for cr in camp_rows:
            campaign_map.setdefault(str(cr[0]), []).append(
                {"id": str(cr[1]), "name": cr[2], "status": cr[3]}
            )

    contacts = []
    for r in rows:
        cid = str(r[0])
        created = r[11]
        contacts.append(
            {
                "id": cid,
                "first_name": r[1],
                "last_name": r[2],
                "email_address": r[3],
                "job_title": r[4],
                "linkedin_url": r[5],
                "seniority_level": display_seniority(r[6]),
                "department": display_department(r[7]),
                "contact_score": float(r[8]) if r[8] else None,
                "ai_champion_score": float(r[9]) if r[9] else None,
                "icp_fit": r[10],
                "created_at": (
                    created.isoformat() if hasattr(created, "isoformat") else created
                ),
                "company": {
                    "id": str(r[12]) if r[12] else None,
                    "name": r[13],
                    "industry": r[14],
                    "tier": display_tier(r[15]),
                    "company_size": r[16],
                    "geo_region": r[17],
                },
                "enrichment_stages": enrichment_map.get(cid, []),
                "active_campaigns": campaign_map.get(cid, []),
            }
        )

    result = {
        "contacts": contacts,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }

    if include_facets:
        facets = {}
        for key, col in SEARCH_FACETS.items():
            if key == "icp_fit":
                continue
            fp = {}
            fw = _search_where(fp, exclude_facet=key)
            frows = db.session.execute(
                db.text(
                    f"""
                    SELECT {col} AS val, COUNT(*) AS cnt
                    FROM contacts ct {joins}
                    WHERE {fw} AND {col} IS NOT NULL
                    GROUP BY {col}
                    ORDER BY cnt DESC
                """
                ),
                fp,
            ).fetchall()
            facets[key] = [{"value": fr[0], "count": fr[1]} for fr in frows]
        result["facets"] = facets

    return jsonify(result)


@contacts_bp.route("/api/contacts/search/summary", methods=["POST"])
@require_auth
def search_contacts_summary():
    """Lightweight aggregate stats for current filter criteria."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    filters = body.get("filters", {})
    text_search = (body.get("text_search") or "").strip()

    where = ["ct.tenant_id = :tenant_id"]
    params = {"tenant_id": tenant_id}

    if text_search:
        where.append(
            "(LOWER(ct.first_name) LIKE LOWER(:q)"
            " OR LOWER(ct.last_name) LIKE LOWER(:q)"
            " OR LOWER(ct.email_address) LIKE LOWER(:q)"
            " OR LOWER(ct.job_title) LIKE LOWER(:q)"
            " OR LOWER(co.name) LIKE LOWER(:q))"
        )
        params["q"] = f"%{text_search}%"

    for key, col in {
        "seniority_level": "ct.seniority_level",
        "department": "ct.department",
        "industry": "co.industry",
        "tier": "co.tier",
        "company_size": "co.company_size",
        "geo_region": "co.geo_region",
    }.items():
        vals = filters.get(key)
        if not vals:
            continue
        if not isinstance(vals, list):
            vals = [vals]
        vals = vals[:50]
        ph_list = ", ".join(f":ss_{key}_{i}" for i in range(len(vals)))
        for i, v in enumerate(vals):
            params[f"ss_{key}_{i}"] = v
        where.append(f"{col} IN ({ph_list})")

    where_str = " AND ".join(where)
    joins = "LEFT JOIN companies co ON ct.company_id = co.id"

    row = db.session.execute(
        db.text(
            f"""
            SELECT
                COUNT(*) AS total,
                AVG(ct.contact_score) AS avg_score,
                COUNT(CASE WHEN ct.email_address IS NOT NULL
                    THEN 1 END) AS with_email,
                COUNT(CASE WHEN ct.linkedin_url IS NOT NULL
                    THEN 1 END) AS with_linkedin
            FROM contacts ct {joins}
            WHERE {where_str}
        """
        ),
        params,
    ).fetchone()

    return jsonify(
        {
            "total": row[0] or 0,
            "avg_contact_score": round(float(row[1]), 2) if row[1] else None,
            "with_email": row[2] or 0,
            "with_linkedin": row[3] or 0,
        }
    )
