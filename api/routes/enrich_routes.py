"""Enrich API routes: estimate costs and start enrichment pipeline."""

import json

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import text

from ..auth import require_auth, resolve_tenant
from ..models import PipelineRun, StageRun, db
from ..services.pipeline_engine import (
    _LEGACY_STAGE_ALIASES,
    count_eligible,
    start_pipeline_threads,
    _process_entity,
)
from ..services.dag_executor import count_eligible_for_estimate
from ..services.stage_registry import get_stage_labels

enrich_bp = Blueprint("enrich", __name__)

ENRICHMENT_STAGES = [
    "l1",
    "triage",
    "l2",
    "signals",
    "registry",
    "news",
    "person",
    "social",
    "career",
    "contact_details",
    "qc",
]

# Static cost defaults (USD per item) — used when no historical data exists
STATIC_COST_DEFAULTS = {
    "l1": 0.02,
    "triage": 0.00,
    "l2": 0.08,
    "signals": 0.05,
    "registry": 0.00,
    "news": 0.04,
    "person": 0.04,
    "social": 0.03,
    "career": 0.03,
    "contact_details": 0.01,
    "qc": 0.00,
}


def _resolve_tag(tenant_id, tag_name):
    """Look up tag by name, return (tag_id, error_response)."""
    row = db.session.execute(
        text("SELECT id FROM tags WHERE tenant_id = :t AND name = :n"),
        {"t": str(tenant_id), "n": tag_name},
    ).fetchone()
    if not row:
        return None, (jsonify({"error": "Tag not found"}), 404)
    return row[0], None


def _resolve_owner(tenant_id, owner_name):
    """Look up owner by name, return owner_id or None."""
    if not owner_name:
        return None
    row = db.session.execute(
        text("SELECT id FROM owners WHERE tenant_id = :t AND name = :n"),
        {"t": str(tenant_id), "n": owner_name},
    ).fetchone()
    return row[0] if row else None


def _get_cost_per_item(tenant_id, stage):
    """Get average cost per item from historical stage_runs, falling back to static default.

    Requires at least 5 completed runs before trusting the historical average,
    to avoid unreliable estimates from early test runs.
    """
    row = db.session.execute(
        text("""
            SELECT AVG(cost_usd / NULLIF(done, 0)), COUNT(*)
            FROM stage_runs
            WHERE tenant_id = :t AND stage = :s
              AND status = 'completed' AND done > 0 AND cost_usd > 0
        """),
        {"t": str(tenant_id), "s": stage},
    ).fetchone()
    if row and row[0] is not None and row[1] >= 5:
        return round(float(row[0]), 4)
    return STATIC_COST_DEFAULTS.get(stage, 0.05)


@enrich_bp.route("/api/enrich/estimate", methods=["POST"])
@require_auth
def enrich_estimate():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    tag_name = body.get("tag_name", "")
    owner_name = body.get("owner_name", "")
    tier_filter = body.get("tier_filter", [])
    stages = body.get("stages", [])
    limit = body.get("limit")
    entity_ids = body.get("entity_ids", [])
    re_enrich = body.get("re_enrich", {})

    if not stages:
        return jsonify({"error": "stages is required"}), 400

    # Sanitise limit
    if limit is not None:
        try:
            limit = int(limit)
            if limit < 1:
                limit = None
        except (TypeError, ValueError):
            limit = None

    # Sanitise entity_ids
    if entity_ids:
        entity_ids = [str(eid).strip() for eid in entity_ids if eid]
        if not entity_ids:
            entity_ids = None
    else:
        entity_ids = None

    # Resolve legacy stage names
    stages = [_LEGACY_STAGE_ALIASES.get(s, s) for s in stages]
    stages = list(dict.fromkeys(stages))  # deduplicate preserving order

    # Validate stages
    invalid = [s for s in stages if s not in ENRICHMENT_STAGES]
    if invalid:
        return jsonify({"error": f"Invalid stages: {', '.join(invalid)}"}), 400

    # Tag is optional — when omitted, estimate across all entities in tenant
    tag_id = None
    if tag_name:
        tag_id, err = _resolve_tag(tenant_id, tag_name)
        if err:
            return err

    owner_id = _resolve_owner(tenant_id, owner_name)

    result = {}
    total_cost = 0.0

    for stage in stages:
        # Determine re-enrich horizon for this stage
        stage_re_enrich = re_enrich.get(stage, {})
        re_enrich_horizon = None
        if stage_re_enrich.get("enabled") and stage_re_enrich.get("horizon"):
            re_enrich_horizon = stage_re_enrich["horizon"]

        # Use DAG-based count when entity_ids or re_enrich are active,
        # otherwise use the original count_eligible with status-based filters
        if entity_ids or re_enrich_horizon:
            eligible = count_eligible_for_estimate(
                stage,
                tenant_id,
                tag_id,
                owner_id,
                tier_filter,
                entity_ids=entity_ids,
                re_enrich_horizon=re_enrich_horizon,
            )
        else:
            eligible = count_eligible(tenant_id, tag_id, stage, owner_id, tier_filter)
        if limit is not None:
            eligible = min(eligible, limit)
        cost_per_item = _get_cost_per_item(tenant_id, stage)
        estimated_cost = round(eligible * cost_per_item, 2)
        total_cost += estimated_cost
        result[stage] = {
            "eligible_count": eligible,
            "cost_per_item": cost_per_item,
            "estimated_cost": estimated_cost,
            "fields": get_stage_labels(stage),
        }

    return jsonify(
        {
            "stages": result,
            "total_estimated_cost": round(total_cost, 2),
        }
    )


@enrich_bp.route("/api/enrich/start", methods=["POST"])
@require_auth
def enrich_start():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    tag_name = body.get("tag_name", "")
    owner_name = body.get("owner_name", "")
    tier_filter = body.get("tier_filter", [])
    stages = body.get("stages", [])
    sample_size = body.get("sample_size")

    if not stages:
        return jsonify({"error": "stages is required"}), 400

    # Resolve legacy stage names
    stages = [_LEGACY_STAGE_ALIASES.get(s, s) for s in stages]
    stages = list(dict.fromkeys(stages))  # deduplicate preserving order

    # Validate stages
    invalid = [s for s in stages if s not in ENRICHMENT_STAGES]
    if invalid:
        return jsonify({"error": f"Invalid stages: {', '.join(invalid)}"}), 400

    # Tag is optional — when omitted, run across all entities in tenant
    tag_id = None
    if tag_name:
        tag_id, err = _resolve_tag(tenant_id, tag_name)
        if err:
            return err

    owner_id = _resolve_owner(tenant_id, owner_name)

    # Check no pipeline already running for this tag (or tenant-wide if no tag)
    if tag_id:
        existing = db.session.execute(
            text("""
                SELECT id FROM pipeline_runs
                WHERE tenant_id = :t AND tag_id = :b
                  AND status IN ('running', 'stopping')
                LIMIT 1
            """),
            {"t": str(tenant_id), "b": str(tag_id)},
        ).fetchone()
    else:
        existing = db.session.execute(
            text("""
                SELECT id FROM pipeline_runs
                WHERE tenant_id = :t AND tag_id IS NULL
                  AND status IN ('running', 'stopping')
                LIMIT 1
            """),
            {"t": str(tenant_id)},
        ).fetchone()
    if existing:
        return jsonify(
            {"error": "A pipeline is already running for this selection"}
        ), 409

    # Build config
    config = {}
    if tier_filter:
        config["tier_filter"] = tier_filter
    if owner_name:
        config["owner"] = owner_name
    if sample_size:
        config["sample_size"] = int(sample_size)

    # Create pipeline_run record
    pipeline_run = PipelineRun(
        tenant_id=str(tenant_id),
        tag_id=str(tag_id) if tag_id else None,
        owner_id=str(owner_id) if owner_id else None,
        status="running",
        config=json.dumps(config) if config else "{}",
    )
    db.session.add(pipeline_run)
    db.session.flush()
    pipeline_run_id = str(pipeline_run.id)

    # Create stage_run records for requested stages only
    stage_run_ids = {}
    for stage in stages:
        stage_config = dict(config)
        stage_config["pipeline_run_id"] = pipeline_run_id

        sr = StageRun(
            tenant_id=str(tenant_id),
            tag_id=str(tag_id) if tag_id else None,
            owner_id=str(owner_id) if owner_id else None,
            stage=stage,
            status="pending",
            total=0,
            config=json.dumps(stage_config),
        )
        db.session.add(sr)
        db.session.flush()
        stage_run_ids[stage] = str(sr.id)

    # Update pipeline_run with stage mapping
    pipeline_run.stages = json.dumps(stage_run_ids)
    db.session.commit()

    # Spawn threads
    start_pipeline_threads(
        current_app._get_current_object(),
        pipeline_run_id,
        stages,
        tenant_id,
        tag_id,
        owner_id=owner_id,
        tier_filter=tier_filter,
        stage_run_ids=stage_run_ids,
        sample_size=int(sample_size) if sample_size else None,
    )

    return jsonify(
        {
            "pipeline_run_id": pipeline_run_id,
            "stage_run_ids": stage_run_ids,
        }
    ), 201


@enrich_bp.route("/api/enrich/review", methods=["GET"])
@require_auth
def enrich_review():
    """List companies needing review after L1 enrichment."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    tag_name = request.args.get("tag_name", "")

    if not tag_name:
        return jsonify({"error": "tag_name is required"}), 400

    tag_id, err = _resolve_tag(tenant_id, tag_name)
    if err:
        return err

    rows = db.session.execute(
        text("""
            SELECT c.id, c.name, c.domain, c.status, c.error_message,
                   c.enrichment_cost_usd
            FROM companies c
            WHERE c.tenant_id = :t AND c.tag_id = :b
              AND c.status IN ('needs_review', 'enrichment_failed')
            ORDER BY c.name
        """),
        {"t": str(tenant_id), "b": str(tag_id)},
    ).fetchall()

    items = []
    for row in rows:
        # Parse error_message as JSON flags list if possible
        flags = []
        if row[4]:
            try:
                flags = json.loads(row[4])
            except (json.JSONDecodeError, TypeError):
                flags = [row[4]]

        items.append(
            {
                "id": str(row[0]),
                "name": row[1],
                "domain": row[2],
                "status": row[3],
                "flags": flags,
                "enrichment_cost_usd": float(row[5]) if row[5] else 0,
            }
        )

    return jsonify({"items": items, "total": len(items)})


@enrich_bp.route("/api/enrich/resolve", methods=["POST"])
@require_auth
def enrich_resolve():
    """Take corrective action on a flagged company."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    company_id = body.get("company_id")
    action = body.get("action")

    if not company_id:
        return jsonify({"error": "company_id is required"}), 400
    if action not in ("approve", "retry", "skip"):
        return jsonify({"error": "action must be 'approve', 'retry', or 'skip'"}), 400

    # Verify company belongs to tenant and is in reviewable state
    row = db.session.execute(
        text("""
            SELECT status FROM companies
            WHERE id = :id AND tenant_id = :t
        """),
        {"id": str(company_id), "t": str(tenant_id)},
    ).fetchone()

    if not row:
        return jsonify({"error": "Company not found"}), 404

    if row[0] not in ("needs_review", "enrichment_failed"):
        return jsonify({"error": f"Company status '{row[0]}' is not reviewable"}), 409

    if action == "approve":
        db.session.execute(
            text("""
                UPDATE companies
                SET status = 'triage_passed', error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"id": str(company_id)},
        )
        db.session.commit()
        return jsonify({"success": True, "new_status": "triage_passed"})

    elif action == "retry":
        db.session.execute(
            text("""
                UPDATE companies
                SET status = 'new', error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"id": str(company_id)},
        )
        db.session.commit()

        # Re-run L1 enrichment synchronously
        try:
            result = _process_entity("l1", str(company_id), str(tenant_id))
            new_status_row = db.session.execute(
                text("SELECT status FROM companies WHERE id = :id"),
                {"id": str(company_id)},
            ).fetchone()
            return jsonify(
                {
                    "success": True,
                    "new_status": new_status_row[0] if new_status_row else "unknown",
                    "result": result,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)[:500]}), 500

    elif action == "skip":
        db.session.execute(
            text("""
                UPDATE companies
                SET status = 'triage_disqualified', error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"id": str(company_id)},
        )
        db.session.commit()
        return jsonify({"success": True, "new_status": "triage_disqualified"})


# ---------------------------------------------------------------------------
# BL-158: Data Quality endpoints
# ---------------------------------------------------------------------------


@enrich_bp.route("/api/enrich/data-quality/<company_id>", methods=["GET"])
@require_auth
def enrich_data_quality_company(company_id):
    """BL-158: Analyze data quality for a single company."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    from ..services.data_quality import analyze_company_data_quality

    result = analyze_company_data_quality(str(company_id), str(tenant_id))
    if result.get("error"):
        return jsonify(result), 404

    return jsonify(result)


@enrich_bp.route("/api/enrich/data-quality", methods=["GET"])
@require_auth
def enrich_data_quality_batch():
    """BL-158: Analyze data quality across a batch (tag)."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    tag_name = request.args.get("tag_name", "")
    if not tag_name:
        return jsonify({"error": "tag_name query param required"}), 400

    tag_id, err = _resolve_tag(tenant_id, tag_name)
    if err:
        return err

    limit = request.args.get("limit", "50")
    try:
        limit = min(int(limit), 200)
    except (ValueError, TypeError):
        limit = 50

    from ..services.data_quality import analyze_batch_data_quality

    result = analyze_batch_data_quality(str(tenant_id), str(tag_id), limit=limit)
    return jsonify(result)


# ---------------------------------------------------------------------------
# BL-172: Anomaly Detection endpoints
# ---------------------------------------------------------------------------


@enrich_bp.route("/api/enrich/anomalies", methods=["GET"])
@require_auth
def enrich_anomalies():
    """BL-172: Detect anomalies in enrichment data for a batch."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    tag_name = request.args.get("tag_name", "")
    if not tag_name:
        return jsonify({"error": "tag_name query param required"}), 400

    tag_id, err = _resolve_tag(tenant_id, tag_name)
    if err:
        return err

    from ..services.anomaly_detector import detect_anomalies

    result = detect_anomalies(str(tenant_id), str(tag_id))
    return jsonify(result)
