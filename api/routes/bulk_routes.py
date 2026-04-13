from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from ..auth import require_role, resolve_tenant
from ..models import db

bulk_bp = Blueprint("bulk", __name__)

MAX_BULK_RECORDS = 10000


def _build_entity_query(
    entity_type: str, tenant_id: str, ids: list | None, filters: dict | None
):
    """Build a SELECT of entity IDs from explicit IDs or filter criteria.

    Returns (sql_fragment, params) where sql_fragment selects id column.
    """
    if entity_type == "contact":
        table = "contacts"
        alias = "ct"
    elif entity_type == "company":
        table = "companies"
        alias = "c"
    else:
        return None, None

    where = [f"{alias}.tenant_id = :tenant_id"]
    params: dict = {"tenant_id": tenant_id}

    if ids:
        # Explicit IDs mode
        placeholders = ", ".join(f":id_{i}" for i in range(len(ids)))
        where.append(f"{alias}.id IN ({placeholders})")
        for i, eid in enumerate(ids):
            params[f"id_{i}"] = eid
    elif filters:
        # Filter mode — replicate list endpoint filter logic
        if filters.get("tag_name"):
            if entity_type == "contact":
                where.append("""EXISTS (
                    SELECT 1 FROM contact_tag_assignments cta
                    JOIN tags bt ON bt.id = cta.tag_id
                    WHERE cta.contact_id = ct.id AND bt.name = :f_tag_name
                )""")
            else:
                where.append("""EXISTS (
                    SELECT 1 FROM company_tag_assignments cota
                    JOIN tags bt ON bt.id = cota.tag_id
                    WHERE cota.company_id = c.id AND bt.name = :f_tag_name
                )""")
            params["f_tag_name"] = filters["tag_name"]

        if filters.get("owner_name"):
            where.append(f"""EXISTS (
                SELECT 1 FROM owners o
                WHERE o.id = {alias}.owner_id AND o.name = :f_owner_name
            )""")
            params["f_owner_name"] = filters["owner_name"]

        if filters.get("search"):
            if entity_type == "contact":
                where.append(
                    "(LOWER(ct.first_name) LIKE LOWER(:f_search) OR LOWER(ct.last_name) LIKE LOWER(:f_search)"
                    " OR LOWER(ct.email_address) LIKE LOWER(:f_search)"
                    " OR LOWER(ct.job_title) LIKE LOWER(:f_search))"
                )
            else:
                where.append(
                    "(LOWER(c.name) LIKE LOWER(:f_search) OR LOWER(c.domain) LIKE LOWER(:f_search))"
                )
            params["f_search"] = f"%{filters['search']}%"

        if entity_type == "contact":
            if filters.get("icp_fit"):
                where.append("ct.icp_fit = :f_icp_fit")
                params["f_icp_fit"] = filters["icp_fit"]
            if filters.get("message_status"):
                where.append("ct.message_status = :f_message_status")
                params["f_message_status"] = filters["message_status"]
        else:
            if filters.get("status"):
                where.append("c.status = :f_status")
                params["f_status"] = filters["status"]
            if filters.get("tier"):
                where.append("c.tier = :f_tier")
                params["f_tier"] = filters["tier"]
    else:
        return None, None

    where_clause = " AND ".join(where)
    sql = f"SELECT {alias}.id FROM {table} {alias} WHERE {where_clause} LIMIT {MAX_BULK_RECORDS}"
    return sql, params


@bulk_bp.route("/api/bulk/add-tags", methods=["POST"])
@require_role("editor")
def bulk_add_tags():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    entity_type = body.get("entity_type")
    ids = body.get("ids")
    filters = body.get("filters")
    tag_ids = body.get("tag_ids", [])

    if entity_type not in ("contact", "company"):
        return jsonify({"error": "entity_type must be 'contact' or 'company'"}), 400
    if not tag_ids:
        return jsonify({"error": "tag_ids is required"}), 400
    if not ids and filters is None:
        return jsonify({"error": "ids or filters required"}), 400

    # Validate tag_ids belong to tenant
    tag_ph = ", ".join(f":tid_{i}" for i in range(len(tag_ids)))
    tag_params = {"t": str(tenant_id)}
    for i, tid in enumerate(tag_ids):
        tag_params[f"tid_{i}"] = tid
    valid_tags = db.session.execute(
        db.text(f"SELECT id FROM tags WHERE tenant_id = :t AND id IN ({tag_ph})"),
        tag_params,
    ).fetchall()
    valid_tag_ids = [str(r[0]) for r in valid_tags]
    if not valid_tag_ids:
        return jsonify({"error": "No valid tags found"}), 400

    # Get entity IDs
    entity_sql, entity_params = _build_entity_query(
        entity_type, str(tenant_id), ids, filters
    )
    if not entity_sql:
        return jsonify({"error": "ids or filters required"}), 400

    entity_rows = db.session.execute(db.text(entity_sql), entity_params).fetchall()
    entity_ids = [str(r[0]) for r in entity_rows]

    if not entity_ids:
        return jsonify(
            {"affected": 0, "new_assignments": 0, "already_tagged": 0, "errors": []}
        )

    # Insert into junction table
    junction_table = (
        "contact_tag_assignments"
        if entity_type == "contact"
        else "company_tag_assignments"
    )
    fk_col = "contact_id" if entity_type == "contact" else "company_id"

    new_count = 0
    for tag_id in valid_tag_ids:
        for eid in entity_ids:
            try:
                db.session.execute(
                    db.text(f"""
                        INSERT INTO {junction_table} (id, tenant_id, {fk_col}, tag_id)
                        VALUES (:id, :tenant_id, :entity_id, :tag_id)
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(tenant_id),
                        "entity_id": eid,
                        "tag_id": tag_id,
                    },
                )
                new_count += 1
            except Exception:
                pass  # skip conflicts

    db.session.commit()
    total = len(entity_ids) * len(valid_tag_ids)
    return jsonify(
        {
            "affected": len(entity_ids),
            "new_assignments": new_count,
            "already_tagged": total - new_count,
            "errors": [],
        }
    )


@bulk_bp.route("/api/bulk/remove-tags", methods=["POST"])
@require_role("editor")
def bulk_remove_tags():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    entity_type = body.get("entity_type")
    ids = body.get("ids")
    filters = body.get("filters")
    tag_ids = body.get("tag_ids", [])

    if entity_type not in ("contact", "company"):
        return jsonify({"error": "entity_type must be 'contact' or 'company'"}), 400
    if not tag_ids:
        return jsonify({"error": "tag_ids is required"}), 400
    if not ids and filters is None:
        return jsonify({"error": "ids or filters required"}), 400

    # Get entity IDs
    entity_sql, entity_params = _build_entity_query(
        entity_type, str(tenant_id), ids, filters
    )
    if not entity_sql:
        return jsonify({"error": "ids or filters required"}), 400

    entity_rows = db.session.execute(db.text(entity_sql), entity_params).fetchall()
    entity_ids = [str(r[0]) for r in entity_rows]

    if not entity_ids:
        return jsonify({"affected": 0, "removed": 0, "not_found": 0, "errors": []})

    junction_table = (
        "contact_tag_assignments"
        if entity_type == "contact"
        else "company_tag_assignments"
    )
    fk_col = "contact_id" if entity_type == "contact" else "company_id"

    # Build DELETE with IN clauses
    eid_ph = ", ".join(f":eid_{i}" for i in range(len(entity_ids)))
    tid_ph = ", ".join(f":tid_{i}" for i in range(len(tag_ids)))
    del_params = {"tenant_id": str(tenant_id)}
    for i, eid in enumerate(entity_ids):
        del_params[f"eid_{i}"] = eid
    for i, tid in enumerate(tag_ids):
        del_params[f"tid_{i}"] = tid

    result = db.session.execute(
        db.text(f"""
            DELETE FROM {junction_table}
            WHERE tenant_id = :tenant_id
              AND {fk_col} IN ({eid_ph})
              AND tag_id IN ({tid_ph})
        """),
        del_params,
    )
    removed = result.rowcount
    db.session.commit()

    total = len(entity_ids) * len(tag_ids)
    return jsonify(
        {
            "affected": len(entity_ids),
            "removed": removed,
            "not_found": total - removed,
            "errors": [],
        }
    )


@bulk_bp.route("/api/bulk/assign-campaign", methods=["POST"])
@require_role("editor")
def bulk_assign_campaign():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    entity_type = body.get("entity_type", "contact")
    ids = body.get("ids")
    filters = body.get("filters")
    campaign_id = body.get("campaign_id")

    if not campaign_id:
        return jsonify({"error": "campaign_id is required"}), 400
    if entity_type != "contact":
        return jsonify({"error": "Only contacts can be assigned to campaigns"}), 400
    if not ids and filters is None:
        return jsonify({"error": "ids or filters required"}), 400

    # Validate campaign belongs to tenant
    camp = db.session.execute(
        db.text("SELECT id FROM campaigns WHERE id = :cid AND tenant_id = :t"),
        {"cid": campaign_id, "t": str(tenant_id)},
    ).fetchone()
    if not camp:
        return jsonify({"error": "Campaign not found"}), 404

    # Get contact IDs
    entity_sql, entity_params = _build_entity_query(
        "contact", str(tenant_id), ids, filters
    )
    if not entity_sql:
        return jsonify({"error": "ids or filters required"}), 400

    entity_rows = db.session.execute(db.text(entity_sql), entity_params).fetchall()
    contact_ids = [str(r[0]) for r in entity_rows]

    if not contact_ids:
        return jsonify({"affected": 0, "errors": []})

    new_count = 0
    for cid in contact_ids:
        try:
            db.session.execute(
                db.text("""
                    INSERT INTO campaign_contacts (id, campaign_id, contact_id, tenant_id)
                    VALUES (:id, :campaign_id, :contact_id, :tenant_id)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "id": str(uuid.uuid4()),
                    "campaign_id": campaign_id,
                    "contact_id": cid,
                    "tenant_id": str(tenant_id),
                },
            )
            new_count += 1
        except Exception:
            pass

    # Update campaign total_contacts count
    db.session.execute(
        db.text("""
            UPDATE campaigns SET total_contacts = (
                SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id = :cid
            ) WHERE id = :cid
        """),
        {"cid": campaign_id},
    )

    db.session.commit()
    return jsonify({"affected": new_count, "errors": []})


@bulk_bp.route("/api/contacts/matching-count", methods=["POST"])
@require_role("viewer")
def contacts_matching_count():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    filters = body.get("filters", {})

    where = ["ct.tenant_id = :tenant_id"]
    params: dict = {"tenant_id": str(tenant_id)}

    if filters.get("tag_name"):
        where.append("""EXISTS (
            SELECT 1 FROM contact_tag_assignments cta
            JOIN tags bt ON bt.id = cta.tag_id
            WHERE cta.contact_id = ct.id AND bt.name = :f_tag_name
        )""")
        params["f_tag_name"] = filters["tag_name"]
    if filters.get("owner_name"):
        where.append("""EXISTS (
            SELECT 1 FROM owners o WHERE o.id = ct.owner_id AND o.name = :f_owner_name
        )""")
        params["f_owner_name"] = filters["owner_name"]
    if filters.get("search"):
        where.append(
            "(LOWER(ct.first_name) LIKE LOWER(:f_search) OR LOWER(ct.last_name) LIKE LOWER(:f_search)"
            " OR LOWER(ct.email_address) LIKE LOWER(:f_search)"
            " OR LOWER(ct.job_title) LIKE LOWER(:f_search))"
        )
        params["f_search"] = f"%{filters['search']}%"
    if filters.get("icp_fit"):
        where.append("ct.icp_fit = :f_icp_fit")
        params["f_icp_fit"] = filters["icp_fit"]
    if filters.get("message_status"):
        where.append("ct.message_status = :f_message_status")
        params["f_message_status"] = filters["message_status"]

    where_clause = " AND ".join(where)
    count = (
        db.session.execute(
            db.text(f"SELECT COUNT(*) FROM contacts ct WHERE {where_clause}"),
            params,
        ).scalar()
        or 0
    )

    return jsonify({"count": count})


@bulk_bp.route("/api/companies/matching-count", methods=["POST"])
@require_role("viewer")
def companies_matching_count():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    filters = body.get("filters", {})

    where = ["c.tenant_id = :tenant_id"]
    params: dict = {"tenant_id": str(tenant_id)}

    if filters.get("tag_name"):
        where.append("""EXISTS (
            SELECT 1 FROM company_tag_assignments cota
            JOIN tags bt ON bt.id = cota.tag_id
            WHERE cota.company_id = c.id AND bt.name = :f_tag_name
        )""")
        params["f_tag_name"] = filters["tag_name"]
    if filters.get("owner_name"):
        where.append("""EXISTS (
            SELECT 1 FROM owners o WHERE o.id = c.owner_id AND o.name = :f_owner_name
        )""")
        params["f_owner_name"] = filters["owner_name"]
    if filters.get("search"):
        where.append(
            "(LOWER(c.name) LIKE LOWER(:f_search) OR LOWER(c.domain) LIKE LOWER(:f_search))"
        )
        params["f_search"] = f"%{filters['search']}%"
    if filters.get("status"):
        where.append("c.status = :f_status")
        params["f_status"] = filters["status"]
    if filters.get("tier"):
        where.append("c.tier = :f_tier")
        params["f_tier"] = filters["tier"]

    where_clause = " AND ".join(where)
    count = (
        db.session.execute(
            db.text(f"SELECT COUNT(*) FROM companies c WHERE {where_clause}"),
            params,
        ).scalar()
        or 0
    )

    return jsonify({"count": count})
