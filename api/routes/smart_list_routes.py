"""Saved smart lists — campaign-prep audience query primitive.

A smart list is a tenant-scoped, named JSON filter spec over either contacts
or companies. Operators define filters once (e.g. "CZ B2B agencies, cold"),
then re-run on demand to refresh the matching result set.

The ``filters`` JSON document is an AND-of-conditions mapping. Each key
matches the equivalent query-string parameter on the existing list
endpoints (``/api/companies`` and ``/api/contacts``), so a smart list and
a manual filter on the corresponding list page produce identical results.

Supported filter keys
---------------------

target='company':
    status, tier, industry, company_size, geo_region, revenue_range,
    organization_type, engagement_status, business_model, segment,
    hq_country (list of country codes/names, exact match)

target='contact':
    company_status, company_tier, industry, company_size, geo_region,
    revenue_range, seniority_level, department, language, address_style,
    hq_country (filters by company.hq_country)

For each key, the value is a list of strings; matching uses ``IN (...)``.

Source: BL-1111 / BL-1112 / BL-1113 (v25 Phase 10 — Campaign Database
Foundations).
"""

from __future__ import annotations

import math
import re
from typing import Any

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth, require_role, resolve_tenant
from ..models import SmartList, db

smart_lists_bp = Blueprint("smart_lists", __name__)


# Allowed filter keys per target. Maps the public filter-spec key to the
# fully-qualified SQL column name we substitute into the WHERE clause.
_COMPANY_FILTER_COLS: dict[str, str] = {
    "status": "c.status",
    "tier": "c.tier",
    "industry": "c.industry",
    "company_size": "c.company_size",
    "geo_region": "c.geo_region",
    "revenue_range": "c.revenue_range",
    "organization_type": "c.organization_type",
    "engagement_status": "c.engagement_status",
    "business_model": "c.business_model",
    "segment": "c.segment",
    "hq_country": "c.hq_country",
    "buying_stage": "c.buying_stage",
    "ownership_type": "c.ownership_type",
}

_CONTACT_FILTER_COLS: dict[str, str] = {
    "company_status": "co.status",
    "company_tier": "co.tier",
    "industry": "co.industry",
    "company_size": "co.company_size",
    "geo_region": "co.geo_region",
    "revenue_range": "co.revenue_range",
    "organization_type": "co.organization_type",
    "engagement_status": "co.engagement_status",
    "business_model": "co.business_model",
    "segment": "co.segment",
    "hq_country": "co.hq_country",
    "seniority_level": "ct.seniority_level",
    "department": "ct.department",
    "language": "ct.language",
    "address_style": "ct.address_style",
    "icp_fit": "ct.icp_fit",
    "message_status": "ct.message_status",
}

ALLOWED_TARGETS = {"contact", "company"}

# Identifier whitelist for the synthetic param binding names below.
_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


def _normalize_filters(target: str, filters: Any) -> dict[str, list[str]]:
    """Validate + normalize a raw filter spec into ``{key: [values]}``.

    Drops unknown keys, empty value lists, and non-string values.
    Raises ``ValueError`` on a malformed top-level shape.
    """
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be a JSON object")

    if target == "company":
        allowed = _COMPANY_FILTER_COLS
    elif target == "contact":
        allowed = _CONTACT_FILTER_COLS
    else:
        raise ValueError(f"unknown target {target!r}")

    normalized: dict[str, list[str]] = {}
    for raw_key, raw_val in filters.items():
        if not isinstance(raw_key, str) or not _KEY_RE.match(raw_key):
            continue
        if raw_key not in allowed:
            continue
        # Accept either a single scalar or a list of scalars.
        if isinstance(raw_val, (str, int, float, bool)):
            values = [str(raw_val)]
        elif isinstance(raw_val, list):
            values = [str(v).strip() for v in raw_val if str(v).strip()]
        else:
            continue
        # Strip + drop empties.
        cleaned = [v.strip() for v in values if isinstance(v, str) and v.strip()]
        if not cleaned:
            continue
        normalized[raw_key] = cleaned
    return normalized


def _build_where(
    target: str, filters: dict[str, list[str]], tenant_id: str
) -> tuple[str, dict[str, Any], str]:
    """Build a parameterized WHERE clause + params dict for the filter spec.

    Returns ``(where_clause, params, joins)``.
    """
    if target == "company":
        cols = _COMPANY_FILTER_COLS
        where = ["c.tenant_id = :tenant_id"]
        joins = ""
    else:  # contact
        cols = _CONTACT_FILTER_COLS
        where = ["ct.tenant_id = :tenant_id"]
        joins = "LEFT JOIN companies co ON ct.company_id = co.id"
    params: dict[str, Any] = {"tenant_id": tenant_id}

    for key, values in filters.items():
        column = cols.get(key)
        if not column:
            continue
        placeholders = []
        for i, v in enumerate(values):
            param_name = f"flt_{key}_{i}"
            placeholders.append(f":{param_name}")
            params[param_name] = v
        if not placeholders:
            continue
        where.append(f"{column} IN ({', '.join(placeholders)})")

    return " AND ".join(where), params, joins


def _run_query(
    target: str,
    filters: dict[str, list[str]],
    tenant_id: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Execute the filter against contacts or companies. Returns paginated
    rows with count + total."""
    where_clause, params, joins = _build_where(target, filters, tenant_id)

    if target == "company":
        count_sql = f"SELECT COUNT(*) FROM companies c WHERE {where_clause}"
        total = db.session.execute(db.text(count_sql), params).scalar() or 0

        pages = max(1, math.ceil(total / page_size)) if total else 1
        offset = (page - 1) * page_size

        rows = db.session.execute(
            db.text(
                f"""
                SELECT c.id, c.name, c.domain, c.status, c.tier,
                       c.organization_type, c.geo_region, c.engagement_status,
                       c.hq_country, c.industry
                FROM companies c
                WHERE {where_clause}
                ORDER BY c.name ASC, c.id ASC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": page_size, "offset": offset},
        ).fetchall()

        items = [
            {
                "id": str(r[0]),
                "name": r[1],
                "domain": r[2],
                "status": r[3],
                "tier": r[4],
                "organization_type": r[5],
                "geo_region": r[6],
                "engagement_status": r[7],
                "hq_country": r[8],
                "industry": r[9],
            }
            for r in rows
        ]
        key = "companies"
    else:  # contact
        count_sql = f"SELECT COUNT(*) FROM contacts ct {joins} WHERE {where_clause}"
        total = db.session.execute(db.text(count_sql), params).scalar() or 0

        pages = max(1, math.ceil(total / page_size)) if total else 1
        offset = (page - 1) * page_size

        rows = db.session.execute(
            db.text(
                f"""
                SELECT ct.id, ct.first_name, ct.last_name, ct.email_address,
                       ct.job_title, ct.company_id, co.name AS company_name,
                       ct.seniority_level, ct.department, ct.language,
                       co.organization_type
                FROM contacts ct
                {joins}
                WHERE {where_clause}
                ORDER BY ct.last_name ASC, ct.id ASC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": page_size, "offset": offset},
        ).fetchall()

        items = []
        for r in rows:
            first = r[1] or ""
            last = r[2] or ""
            full = (first + " " + last).strip() if last else first
            items.append(
                {
                    "id": str(r[0]),
                    "first_name": first,
                    "last_name": last,
                    "full_name": full,
                    "email_address": r[3],
                    "job_title": r[4],
                    "company_id": str(r[5]) if r[5] else None,
                    "company_name": r[6],
                    "seniority_level": r[7],
                    "department": r[8],
                    "language": r[9],
                    "organization_type": r[10],
                }
            )
        key = "contacts"

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        key: items,
    }


# --------------------------------------------------------------------------- #
#  CRUD endpoints
# --------------------------------------------------------------------------- #


@smart_lists_bp.route("/api/smart-lists", methods=["GET"])
@require_auth
def list_smart_lists():
    """List all saved smart lists for the current tenant."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    lists = (
        SmartList.query.filter_by(tenant_id=str(tenant_id))
        .order_by(SmartList.name.asc())
        .all()
    )
    return jsonify({"smart_lists": [sl.to_dict() for sl in lists]})


@smart_lists_bp.route("/api/smart-lists/<list_id>", methods=["GET"])
@require_auth
def get_smart_list(list_id):
    """Get a single smart list by id."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    sl = SmartList.query.filter_by(id=list_id, tenant_id=str(tenant_id)).first()
    if not sl:
        return jsonify({"error": "Smart list not found"}), 404
    return jsonify(sl.to_dict())


@smart_lists_bp.route("/api/smart-lists", methods=["POST"])
@require_role("editor")
def create_smart_list():
    """Create a new saved smart list."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    target = (body.get("target") or "").strip().lower()
    if target not in ALLOWED_TARGETS:
        return jsonify(
            {"error": f"target must be one of {sorted(ALLOWED_TARGETS)}"}
        ), 400

    try:
        filters = _normalize_filters(target, body.get("filters") or {})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    description = body.get("description")
    if description is not None:
        description = str(description).strip() or None

    sl = SmartList(
        tenant_id=str(tenant_id),
        name=name,
        description=description,
        target=target,
        filters=filters,
        created_by=str(g.current_user.id) if g.current_user else None,
    )
    db.session.add(sl)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": f"A smart list named {name!r} already exists"}), 409
    return jsonify(sl.to_dict()), 201


@smart_lists_bp.route("/api/smart-lists/<list_id>", methods=["PATCH"])
@require_role("editor")
def update_smart_list(list_id):
    """Update fields on a saved smart list."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    sl = SmartList.query.filter_by(id=list_id, tenant_id=str(tenant_id)).first()
    if not sl:
        return jsonify({"error": "Smart list not found"}), 404

    body = request.get_json(silent=True) or {}

    if "name" in body:
        new_name = (body.get("name") or "").strip()
        if not new_name:
            return jsonify({"error": "name cannot be empty"}), 400
        sl.name = new_name
    if "description" in body:
        desc = body.get("description")
        sl.description = (str(desc).strip() or None) if desc is not None else None

    new_target = sl.target
    if "target" in body:
        candidate = (body.get("target") or "").strip().lower()
        if candidate not in ALLOWED_TARGETS:
            return jsonify(
                {"error": f"target must be one of {sorted(ALLOWED_TARGETS)}"}
            ), 400
        new_target = candidate
        sl.target = candidate

    if "filters" in body:
        try:
            sl.filters = _normalize_filters(new_target, body.get("filters") or {})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    elif "target" in body and new_target != sl.target:
        # Target changed but filters were not re-validated; drop filters.
        sl.filters = {}

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": f"A smart list named {sl.name!r} already exists"}), 409
    return jsonify(sl.to_dict())


@smart_lists_bp.route("/api/smart-lists/<list_id>", methods=["DELETE"])
@require_role("editor")
def delete_smart_list(list_id):
    """Delete a saved smart list."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    sl = SmartList.query.filter_by(id=list_id, tenant_id=str(tenant_id)).first()
    if not sl:
        return jsonify({"error": "Smart list not found"}), 404
    db.session.delete(sl)
    db.session.commit()
    return jsonify({"ok": True}), 200


@smart_lists_bp.route("/api/smart-lists/<list_id>/run", methods=["POST"])
@require_auth
def run_smart_list(list_id):
    """Execute the saved filter and return paginated results.

    Also updates ``last_run_at`` and ``last_run_count``.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    sl = SmartList.query.filter_by(id=list_id, tenant_id=str(tenant_id)).first()
    if not sl:
        return jsonify({"error": "Smart list not found"}), 404

    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(100, max(1, request.args.get("page_size", 25, type=int)))

    filters_dict = sl.to_dict(include_filters=True)["filters"] or {}
    # Re-normalize in case the column shape evolved after the list was saved.
    try:
        filters = _normalize_filters(sl.target, filters_dict)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    result = _run_query(sl.target, filters, str(tenant_id), page, page_size)

    from sqlalchemy.sql import func as _func

    sl.last_run_count = result["total"]
    sl.last_run_at = _func.now()
    db.session.commit()
    db.session.refresh(sl)

    result["smart_list"] = sl.to_dict()
    return jsonify(result)


@smart_lists_bp.route("/api/smart-lists/preview", methods=["POST"])
@require_auth
def preview_smart_list():
    """Preview a transient filter spec without persisting a smart list."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    target = (body.get("target") or "").strip().lower()
    if target not in ALLOWED_TARGETS:
        return jsonify(
            {"error": f"target must be one of {sorted(ALLOWED_TARGETS)}"}
        ), 400

    try:
        filters = _normalize_filters(target, body.get("filters") or {})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    page = max(1, body.get("page", 1) if isinstance(body.get("page"), int) else 1)
    raw_ps = body.get("page_size", 25)
    page_size = min(100, max(1, raw_ps if isinstance(raw_ps, int) else 25))

    result = _run_query(target, filters, str(tenant_id), page, page_size)
    return jsonify(result)
