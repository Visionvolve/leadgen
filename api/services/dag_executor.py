"""DAG-based pipeline executor using entity_stage_completions for eligibility.

Replaces the hardcoded ELIGIBILITY_QUERIES with a generic, completion-record-based
eligibility builder. Each stage's eligible entities are determined by checking that
all required dependencies (hard + activated soft) have 'completed' rows.
"""

import datetime
import logging
import threading
import time
import uuid as _uuid_mod
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import current_app
from sqlalchemy import text

from ..models import db
from .stage_registry import get_stage, resolve_deps, topo_sort

logger = logging.getLogger(__name__)

REACTIVE_POLL_INTERVAL = 15  # seconds between re-querying eligible IDs


def record_completion(
    tenant_id,
    tag_id,
    pipeline_run_id,
    entity_type,
    entity_id,
    stage,
    status="completed",
    cost_usd=0,
    error=None,
):
    """Insert an entity_stage_completions record.

    This is the core dual-write function: called after every entity processing
    to record what stage completed (or failed/skipped) for which entity.
    """
    row_id = str(_uuid_mod.uuid4())
    params = {
        "id": row_id,
        "tenant_id": str(tenant_id),
        "tag_id": str(tag_id),
        "pipeline_run_id": str(pipeline_run_id) if pipeline_run_id else None,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "stage": stage,
        "status": status,
        "cost_usd": cost_usd or 0,
        "error": str(error)[:500] if error else None,
        "_now": datetime.datetime.utcnow().isoformat(),
    }
    try:
        # Try PG upsert first
        db.session.execute(
            text("""
                INSERT INTO entity_stage_completions
                    (id, tenant_id, tag_id, pipeline_run_id, entity_type,
                     entity_id, stage, status, cost_usd, error)
                VALUES (:id, :tenant_id, :tag_id, :pipeline_run_id, :entity_type,
                        :entity_id, :stage, :status, :cost_usd, :error)
                ON CONFLICT (pipeline_run_id, entity_id, stage) DO UPDATE
                SET status = EXCLUDED.status, cost_usd = EXCLUDED.cost_usd,
                    error = EXCLUDED.error, completed_at = :_now
            """),
            params,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        # Fallback for SQLite (no ON CONFLICT with partial unique)
        try:
            db.session.execute(
                text("""
                    INSERT INTO entity_stage_completions
                        (id, tenant_id, tag_id, pipeline_run_id, entity_type,
                         entity_id, stage, status, cost_usd, error)
                    VALUES (:id, :tenant_id, :tag_id, :pipeline_run_id, :entity_type,
                            :entity_id, :stage, :status, :cost_usd, :error)
                """),
                params,
            )
            db.session.commit()
        except Exception as e2:
            logger.warning(
                "Failed to record completion for %s/%s/%s: %s",
                entity_id,
                stage,
                status,
                e2,
            )
            db.session.rollback()


def _auto_record_triage(tenant_id, tag_id, pipeline_run_id, entity_id, l1_result):
    """After L1 auto-triages a company, write a triage completion record.

    The L1 enricher sets company status to 'triage_passed' or 'needs_review'.
    The DAG executor needs a triage completion record for L2 eligibility
    (L2 hard-depends on triage). This bridges the gap when triage isn't
    run as a separate stage.
    """
    try:
        row = db.session.execute(
            text("SELECT status FROM companies WHERE id = :id"),
            {"id": str(entity_id)},
        ).fetchone()
        if not row:
            return

        company_status = row[0]
        if company_status == "triage_passed":
            triage_status = "completed"
        elif company_status in ("triage_disqualified", "needs_review"):
            triage_status = "disqualified"
        else:
            # Not auto-triaged (e.g., enrichment_failed) — don't write triage record
            return

        record_completion(
            tenant_id,
            tag_id,
            pipeline_run_id,
            "company",
            entity_id,
            "triage",
            status=triage_status,
            cost_usd=0,
        )
    except Exception as e:
        logger.warning("Failed to auto-record triage for %s: %s", entity_id, e)


def build_eligibility_query(
    stage_code,
    pipeline_run_id,
    tenant_id,
    tag_id,
    owner_id=None,
    tier_filter=None,
    soft_deps_enabled=None,
    entity_ids=None,
    re_enrich_horizon=None,
):
    """Build SQL + params to find entities eligible for a given stage.

    An entity is eligible when:
    1. Belongs to correct tenant/tag
    2. Not already completed/failed/skipped for this stage in this pipeline run
    3. All hard_deps have 'completed' rows for this entity (or its parent company)
    4. All activated soft_deps have 'completed' rows
    5. Country gate passes (if applicable)
    """
    stage_def = get_stage(stage_code)
    if not stage_def:
        return None, {}

    entity_type = stage_def["entity_type"]
    deps = resolve_deps(stage_code, soft_deps_enabled)

    params = {
        "tenant_id": str(tenant_id),
        "tag_id": str(tag_id),
        "pipeline_run_id": str(pipeline_run_id) if pipeline_run_id else None,
        "stage": stage_code,
    }

    if entity_type == "company":
        base_table = "companies"
        id_col = "e.id"
    else:
        # contact entity_type
        base_table = "contacts"
        id_col = "e.id"

    # Base: select entities in this tenant+tag
    sql_parts = [f"SELECT {id_col} FROM {base_table} e"]
    where_clauses = [
        "e.tenant_id = :tenant_id",
        "e.tag_id = :tag_id",
    ]

    # Not already completed for this stage+run
    where_clauses.append(f"""
        NOT EXISTS (
            SELECT 1 FROM entity_stage_completions esc_self
            WHERE esc_self.entity_id = {id_col}
              AND esc_self.stage = :stage
              AND esc_self.pipeline_run_id = :pipeline_run_id
        )
    """)

    # Dependency checks
    for i, dep in enumerate(deps):
        dep_def = get_stage(dep)
        if not dep_def:
            continue

        dep_entity_type = dep_def["entity_type"]
        param_dep = f"dep_{i}"
        params[param_dep] = dep

        if dep_entity_type == entity_type:
            # Same entity type: check entity_id directly
            where_clauses.append(f"""
                EXISTS (
                    SELECT 1 FROM entity_stage_completions esc_{i}
                    WHERE esc_{i}.entity_id = {id_col}
                      AND esc_{i}.stage = :{param_dep}
                      AND esc_{i}.status = 'completed'
                      AND esc_{i}.pipeline_run_id = :pipeline_run_id
                )
            """)
        elif dep_entity_type == "company" and entity_type == "contact":
            # Cross-entity: contact depends on company stage
            # Check via contacts.company_id
            where_clauses.append(f"""
                EXISTS (
                    SELECT 1 FROM entity_stage_completions esc_{i}
                    WHERE esc_{i}.entity_id = e.company_id
                      AND esc_{i}.stage = :{param_dep}
                      AND esc_{i}.status = 'completed'
                      AND esc_{i}.pipeline_run_id = :pipeline_run_id
                )
            """)

    # Owner filter
    if owner_id:
        where_clauses.append("e.owner_id = :owner_id")
        params["owner_id"] = str(owner_id)

    # Tier filter (company stages only)
    if tier_filter and entity_type == "company":
        from ..display import tier_db_values

        tier_vals = tier_db_values(tier_filter)
        if tier_vals:
            placeholders = ", ".join(f":tier_{i}" for i in range(len(tier_vals)))
            where_clauses.append(f"e.tier IN ({placeholders})")
            for i, tv in enumerate(tier_vals):
                params[f"tier_{i}"] = tv

    # Entity ID filter
    if entity_ids:
        eid_placeholders = ", ".join(f":eid_{i}" for i in range(len(entity_ids)))
        where_clauses.append(f"{id_col} IN ({eid_placeholders})")
        for i, eid in enumerate(entity_ids):
            params[f"eid_{i}"] = str(eid)

    # Re-enrich horizon: allow entities whose last completion is older than horizon
    if re_enrich_horizon:
        params["re_enrich_horizon"] = re_enrich_horizon
        # Override the default "not already completed" check.
        # Remove the standard NOT EXISTS (added above) and replace with horizon-aware version.
        # Find and remove the NOT EXISTS clause we already added
        for idx, clause in enumerate(where_clauses):
            if "esc_self" in clause and "NOT EXISTS" in clause:
                where_clauses[idx] = f"""
                    NOT EXISTS (
                        SELECT 1 FROM entity_stage_completions esc_self
                        WHERE esc_self.entity_id = {id_col}
                          AND esc_self.stage = :stage
                          AND esc_self.pipeline_run_id = :pipeline_run_id
                    )
                    AND (
                        NOT EXISTS (
                            SELECT 1 FROM entity_stage_completions esc_prev
                            WHERE esc_prev.entity_id = {id_col}
                              AND esc_prev.stage = :stage
                              AND esc_prev.status = 'completed'
                              AND esc_prev.completed_at >= :re_enrich_horizon
                        )
                    )
                """
                break

    # Country gate
    country_gate = stage_def.get("country_gate")
    if country_gate:
        country_conditions = []
        countries = country_gate.get("countries", [])
        tlds = country_gate.get("tlds", [])

        if entity_type == "company":
            if countries:
                c_placeholders = ", ".join(
                    f":cg_country_{i}" for i in range(len(countries))
                )
                country_conditions.append(f"e.hq_country IN ({c_placeholders})")
                for i, c in enumerate(countries):
                    params[f"cg_country_{i}"] = c
            if tlds:
                for i, tld in enumerate(tlds):
                    country_conditions.append(f"e.domain LIKE :cg_tld_{i}")
                    params[f"cg_tld_{i}"] = f"%{tld}"

            if country_conditions:
                where_clauses.append(f"({' OR '.join(country_conditions)})")

    sql = " ".join(sql_parts)
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += (
        " ORDER BY e.name"
        if entity_type == "company"
        else " ORDER BY e.last_name, e.first_name"
    )

    return sql, params


def get_dag_eligible_ids(
    stage_code,
    pipeline_run_id,
    tenant_id,
    tag_id,
    owner_id=None,
    tier_filter=None,
    soft_deps_enabled=None,
    entity_ids=None,
    re_enrich_horizon=None,
):
    """Query PG for eligible entity IDs using DAG-based eligibility."""
    sql, params = build_eligibility_query(
        stage_code,
        pipeline_run_id,
        tenant_id,
        tag_id,
        owner_id,
        tier_filter,
        soft_deps_enabled,
        entity_ids=entity_ids,
        re_enrich_horizon=re_enrich_horizon,
    )
    if sql is None:
        return []

    rows = db.session.execute(text(sql), params).fetchall()
    return [str(row[0]) for row in rows]


def count_dag_eligible(
    stage_code,
    pipeline_run_id,
    tenant_id,
    tag_id,
    owner_id=None,
    tier_filter=None,
    soft_deps_enabled=None,
    entity_ids=None,
    re_enrich_horizon=None,
):
    """Count eligible entities without loading IDs."""
    sql, params = build_eligibility_query(
        stage_code,
        pipeline_run_id,
        tenant_id,
        tag_id,
        owner_id,
        tier_filter,
        soft_deps_enabled,
        entity_ids=entity_ids,
        re_enrich_horizon=re_enrich_horizon,
    )
    if sql is None:
        return 0

    count_sql = f"SELECT COUNT(*) FROM ({sql}) sub"
    row = db.session.execute(text(count_sql), params).fetchone()
    return row[0] if row else 0


def count_eligible_for_estimate(
    stage_code,
    tenant_id,
    tag_id,
    owner_id=None,
    tier_filter=None,
    entity_ids=None,
    re_enrich_horizon=None,
):
    """Count eligible entities for cost estimation (no pipeline_run_id needed).

    Simplified eligibility: entity exists in tenant+tag, matches filters,
    and (if re_enrich) last completion for this stage is older than horizon.
    """
    stage_def = get_stage(stage_code)
    if not stage_def:
        return 0

    entity_type = stage_def["entity_type"]
    params = {"tenant_id": str(tenant_id)}

    if entity_type == "company":
        base_table = "companies"
        id_col = "e.id"
    else:
        base_table = "contacts"
        id_col = "e.id"

    where_clauses = [
        "e.tenant_id = :tenant_id",
    ]

    # Tag filter is optional — when tag_id is None, count all entities in tenant
    if tag_id:
        where_clauses.append("e.tag_id = :tag_id")
        params["tag_id"] = str(tag_id)

    # Owner filter
    if owner_id:
        where_clauses.append("e.owner_id = :owner_id")
        params["owner_id"] = str(owner_id)

    # Tier filter (company stages only)
    if tier_filter and entity_type == "company":
        from ..display import tier_db_values

        tier_vals = tier_db_values(tier_filter)
        if tier_vals:
            placeholders = ", ".join(f":tier_{i}" for i in range(len(tier_vals)))
            where_clauses.append(f"e.tier IN ({placeholders})")
            for i, tv in enumerate(tier_vals):
                params[f"tier_{i}"] = tv

    # Entity ID filter
    if entity_ids:
        eid_placeholders = ", ".join(f":eid_{i}" for i in range(len(entity_ids)))
        where_clauses.append(f"{id_col} IN ({eid_placeholders})")
        for i, eid in enumerate(entity_ids):
            params[f"eid_{i}"] = str(eid)

    # Re-enrich horizon: exclude entities with recent completions
    if re_enrich_horizon:
        params["stage"] = stage_code
        params["re_enrich_horizon"] = re_enrich_horizon
        where_clauses.append(f"""
            NOT EXISTS (
                SELECT 1 FROM entity_stage_completions esc_prev
                WHERE esc_prev.entity_id = {id_col}
                  AND esc_prev.stage = :stage
                  AND esc_prev.status = 'completed'
                  AND esc_prev.completed_at >= :re_enrich_horizon
            )
        """)

    # Country gate
    country_gate = stage_def.get("country_gate")
    if country_gate and entity_type == "company":
        country_conditions = []
        countries = country_gate.get("countries", [])
        tlds = country_gate.get("tlds", [])
        if countries:
            c_placeholders = ", ".join(
                f":cg_country_{i}" for i in range(len(countries))
            )
            country_conditions.append(f"e.hq_country IN ({c_placeholders})")
            for i, c in enumerate(countries):
                params[f"cg_country_{i}"] = c
        if tlds:
            for i, tld in enumerate(tlds):
                country_conditions.append(f"e.domain LIKE :cg_tld_{i}")
                params[f"cg_tld_{i}"] = f"%{tld}"
        if country_conditions:
            where_clauses.append(f"({' OR '.join(country_conditions)})")

    sql = f"SELECT COUNT(*) FROM {base_table} e WHERE " + " AND ".join(where_clauses)
    row = db.session.execute(text(sql), params).fetchone()
    return row[0] if row else 0


def auto_skip_country_gated(stage_code, pipeline_run_id, tenant_id, tag_id):
    """Bulk-insert 'skipped' rows for entities that don't match a country gate.

    Called at stage thread startup. This unblocks downstream stages immediately
    for entities that this stage doesn't apply to.
    """
    stage_def = get_stage(stage_code)
    if not stage_def or not stage_def.get("country_gate"):
        return 0

    entity_type = stage_def["entity_type"]
    if entity_type != "company":
        return 0  # Country gates only apply to companies currently

    country_gate = stage_def["country_gate"]
    countries = country_gate.get("countries", [])
    tlds = country_gate.get("tlds", [])

    # Build the "does NOT match gate" condition
    gate_conditions = []
    params = {
        "tenant_id": str(tenant_id),
        "tag_id": str(tag_id),
        "pipeline_run_id": str(pipeline_run_id) if pipeline_run_id else None,
        "stage": stage_code,
    }

    if countries:
        c_placeholders = ", ".join(f":cg_{i}" for i in range(len(countries)))
        gate_conditions.append(f"c.hq_country IN ({c_placeholders})")
        for i, c in enumerate(countries):
            params[f"cg_{i}"] = c
    if tlds:
        for i, tld in enumerate(tlds):
            gate_conditions.append(f"c.domain LIKE :tld_{i}")
            params[f"tld_{i}"] = f"%{tld}"

    if not gate_conditions:
        return 0

    gate_expr = " OR ".join(gate_conditions)

    # Insert 'skipped' for companies that do NOT match and don't already have a row
    sql = f"""
        INSERT INTO entity_stage_completions
            (tenant_id, tag_id, pipeline_run_id, entity_type, entity_id, stage, status)
        SELECT c.tenant_id, c.tag_id, :pipeline_run_id, 'company', c.id, :stage, 'skipped'
        FROM companies c
        WHERE c.tenant_id = :tenant_id AND c.tag_id = :tag_id
          AND NOT ({gate_expr})
          AND NOT EXISTS (
              SELECT 1 FROM entity_stage_completions esc
              WHERE esc.entity_id = c.id AND esc.stage = :stage
                AND esc.pipeline_run_id = :pipeline_run_id
          )
    """

    try:
        result = db.session.execute(text(sql), params)
        db.session.commit()
        count = result.rowcount
        if count > 0:
            logger.info(
                "Auto-skipped %d companies for stage %s (country gate)",
                count,
                stage_code,
            )
        return count
    except Exception as e:
        logger.warning("Auto-skip failed for %s: %s", stage_code, e)
        db.session.rollback()
        return 0


# ---------------------------------------------------------------------------
# DAG-aware reactive stage execution
# ---------------------------------------------------------------------------


def _check_stop_signal(run_id):
    """Check if a stage_run has been requested to stop."""
    row = db.session.execute(
        text("SELECT status FROM stage_runs WHERE id = :id"),
        {"id": str(run_id)},
    ).fetchone()
    return row and row[0] == "stopping"


def _get_entity_name(stage_code, entity_id, tenant_id):
    """Look up display name for the entity being processed."""
    stage_def = get_stage(stage_code)
    if not stage_def:
        return str(entity_id)

    try:
        if stage_def["entity_type"] == "contact":
            row = db.session.execute(
                text(
                    "SELECT first_name, last_name FROM contacts WHERE id = :id AND tenant_id = :t"
                ),
                {"id": str(entity_id), "t": str(tenant_id)},
            ).fetchone()
            if row:
                return f"{row[0] or ''} {row[1] or ''}".strip() or str(entity_id)
        else:
            row = db.session.execute(
                text("SELECT name FROM companies WHERE id = :id AND tenant_id = :t"),
                {"id": str(entity_id), "t": str(tenant_id)},
            ).fetchone()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    return str(entity_id)


def _update_stage_run(run_id, **kwargs):
    """Update a stage_run record."""
    set_parts = []
    params = {"id": str(run_id)}
    for key, value in kwargs.items():
        set_parts.append(f"{key} = :{key}")
        params[key] = value

    if "completed_at" not in kwargs and kwargs.get("status") in (
        "completed",
        "failed",
        "stopped",
    ):
        set_parts.append("completed_at = :completed_at")
        params["completed_at"] = datetime.datetime.utcnow().isoformat()

    if not set_parts:
        return

    sql = f"UPDATE stage_runs SET {', '.join(set_parts)} WHERE id = :id"
    db.session.execute(text(sql), params)
    db.session.commit()


def _update_current_item(run_id, entity_name, status="processing"):
    """Store the current item being processed in the stage_run config."""
    try:
        import json as _json

        row = db.session.execute(
            text("SELECT config FROM stage_runs WHERE id = :id"),
            {"id": str(run_id)},
        ).fetchone()
        if row:
            config = _json.loads(row[0] or "{}")
            config["current_item"] = {"name": entity_name, "status": status}
            if status != "processing":
                recent = config.get("recent_items", [])
                recent.append({"name": entity_name, "status": status})
                if len(recent) > 20:
                    recent = recent[-20:]
                config["recent_items"] = recent
            db.session.execute(
                text("UPDATE stage_runs SET config = :config WHERE id = :id"),
                {"id": str(run_id), "config": _json.dumps(config)},
            )
            db.session.commit()
    except Exception:
        pass


def _fetch_previous_data(entity_type, entity_id, stage_code):
    """Fetch existing enrichment data for re-enrichment context.

    Returns a dict of current field values, or None if entity not found.
    """
    try:
        if entity_type == "company":
            row = db.session.execute(
                text("""
                    SELECT name, domain, industry, business_type, summary,
                           verified_revenue_eur_m, verified_employees,
                           hq_city, hq_country, ownership_type, tier
                    FROM companies WHERE id = :id
                """),
                {"id": str(entity_id)},
            ).fetchone()
            if row:
                return {
                    "name": row[0],
                    "domain": row[1],
                    "industry": row[2],
                    "business_type": row[3],
                    "summary": row[4],
                    "revenue_eur_m": float(row[5]) if row[5] else None,
                    "employees": row[6],
                    "hq_city": row[7],
                    "hq_country": row[8],
                    "ownership_type": row[9],
                    "tier": row[10],
                }
        else:
            row = db.session.execute(
                text("""
                    SELECT first_name, last_name, job_title, linkedin_url,
                           seniority, department
                    FROM contacts WHERE id = :id
                """),
                {"id": str(entity_id)},
            ).fetchone()
            if row:
                return {
                    "first_name": row[0],
                    "last_name": row[1],
                    "job_title": row[2],
                    "linkedin_url": row[3],
                    "seniority": row[4],
                    "department": row[5],
                }
    except Exception as e:
        logger.warning("Failed to fetch previous data for %s: %s", entity_id, e)
    return None


def run_dag_stage(
    app,
    run_id,
    stage_code,
    pipeline_run_id,
    tenant_id,
    tag_id,
    owner_id=None,
    tier_filter=None,
    soft_deps_enabled=None,
    predecessor_run_ids=None,
    sample_size=None,
    entity_ids=None,
    re_enrich_horizons=None,
):
    """Background thread: DAG-aware reactive stage execution.

    Like run_stage_reactive but uses completion-record-based eligibility
    and records completions after each entity.
    """
    from .pipeline_engine import _process_entity, _extract_cost
    import threading

    _api_semaphore = threading.Semaphore(20)

    stage_def = get_stage(stage_code)
    if not stage_def:
        _update_stage_run(run_id, status="failed", error=f"Unknown stage: {stage_code}")
        return

    entity_type = stage_def["entity_type"]

    def _process_entity_in_thread(entity_id, prev_data, app_obj):
        """Process one entity with rate limiting in its own app context."""
        with app_obj.app_context():
            with _api_semaphore:
                return _process_entity(
                    stage_code, entity_id, tenant_id, previous_data=prev_data
                )

    with app.app_context():
        max_workers = current_app.config.get("ENRICHMENT_MAX_WORKERS", 5)

        # Auto-skip entities that don't match country gate
        auto_skip_country_gated(stage_code, pipeline_run_id, tenant_id, tag_id)

        processed_ids = set()
        total_cost = 0.0
        done_count = 0
        failed_count = 0
        sample_remaining = sample_size

        _update_stage_run(run_id, status="running")
        logger.info(
            "DAG stage %s started (run %s, pipeline %s, %d workers)",
            stage_code,
            run_id,
            pipeline_run_id,
            max_workers,
        )

        while True:
            if _check_stop_signal(run_id):
                _update_stage_run(
                    run_id,
                    status="stopped",
                    done=done_count,
                    failed=failed_count,
                    cost_usd=total_cost,
                )
                return

            if sample_remaining is not None and sample_remaining <= 0:
                _update_stage_run(
                    run_id,
                    status="completed",
                    done=done_count,
                    failed=failed_count,
                    cost_usd=total_cost,
                )
                return

            # Query eligible entities using DAG-based eligibility
            try:
                # Get re-enrich horizon for this specific stage
                stage_horizon = None
                if re_enrich_horizons and stage_code in re_enrich_horizons:
                    stage_horizon = re_enrich_horizons[stage_code]

                all_eligible = get_dag_eligible_ids(
                    stage_code,
                    pipeline_run_id,
                    tenant_id,
                    tag_id,
                    owner_id,
                    tier_filter,
                    soft_deps_enabled,
                    entity_ids=entity_ids,
                    re_enrich_horizon=stage_horizon,
                )
            except Exception as e:
                logger.error("DAG stage %s eligibility query failed: %s", stage_code, e)
                db.session.rollback()
                time.sleep(REACTIVE_POLL_INTERVAL)
                continue

            new_ids = [eid for eid in all_eligible if eid not in processed_ids]

            if sample_remaining is not None and len(new_ids) > sample_remaining:
                new_ids = new_ids[:sample_remaining]

            if new_ids:
                new_total = done_count + failed_count + len(new_ids)
                _update_stage_run(run_id, total=new_total)

                if max_workers <= 1:
                    # Serial processing (original path)
                    for entity_id in new_ids:
                        if _check_stop_signal(run_id):
                            _update_stage_run(
                                run_id,
                                status="stopped",
                                done=done_count,
                                failed=failed_count,
                                cost_usd=total_cost,
                            )
                            return

                        processed_ids.add(entity_id)
                        entity_name = _get_entity_name(stage_code, entity_id, tenant_id)
                        _update_current_item(run_id, entity_name, "processing")

                        try:
                            prev_data = None
                            if re_enrich_horizons and stage_code in re_enrich_horizons:
                                prev_data = _fetch_previous_data(
                                    entity_type, entity_id, stage_code
                                )

                            result = _process_entity(
                                stage_code,
                                entity_id,
                                tenant_id,
                                previous_data=prev_data,
                            )
                            cost = _extract_cost(result)
                            total_cost += cost

                            if isinstance(result, dict) and "gate_passed" in result:
                                completion_status = (
                                    "completed"
                                    if result["gate_passed"]
                                    else "disqualified"
                                )
                            else:
                                completion_status = "completed"

                            done_count += 1
                            record_completion(
                                tenant_id,
                                tag_id,
                                pipeline_run_id,
                                entity_type,
                                entity_id,
                                stage_code,
                                status=completion_status,
                                cost_usd=cost,
                            )

                            # L1 auto-triage: also record triage completion
                            # so L2 (which hard-depends on triage) becomes eligible
                            if stage_code == "l1" and entity_type == "company":
                                _auto_record_triage(
                                    tenant_id,
                                    tag_id,
                                    pipeline_run_id,
                                    entity_id,
                                    result,
                                )

                            _update_current_item(run_id, entity_name, "ok")
                            _update_stage_run(
                                run_id,
                                done=done_count,
                                cost_usd=total_cost,
                                failed=failed_count,
                            )
                        except Exception as e:
                            db.session.rollback()
                            failed_count += 1
                            record_completion(
                                tenant_id,
                                tag_id,
                                pipeline_run_id,
                                entity_type,
                                entity_id,
                                stage_code,
                                status="failed",
                                error=str(e),
                            )
                            _update_current_item(run_id, entity_name, "failed")
                            logger.warning(
                                "DAG stage %s item %s failed: %s",
                                stage_code,
                                entity_id,
                                e,
                            )
                            _update_stage_run(
                                run_id,
                                done=done_count,
                                failed=failed_count,
                                cost_usd=total_cost,
                                error=str(e)[:500],
                            )

                        if sample_remaining is not None:
                            sample_remaining -= 1
                            if sample_remaining <= 0:
                                break
                else:
                    # Parallel processing with ThreadPoolExecutor
                    app_obj = current_app._get_current_object()
                    batch_ids = list(new_ids)  # snapshot

                    # Prepare previous data before submitting to threads
                    prev_data_map = {}
                    if re_enrich_horizons and stage_code in re_enrich_horizons:
                        for eid in batch_ids:
                            prev_data_map[eid] = _fetch_previous_data(
                                entity_type, eid, stage_code
                            )

                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {}
                        for entity_id in batch_ids:
                            if _check_stop_signal(run_id):
                                break
                            processed_ids.add(entity_id)
                            prev_data = prev_data_map.get(entity_id)
                            future = executor.submit(
                                _process_entity_in_thread, entity_id, prev_data, app_obj
                            )
                            futures[future] = entity_id

                        for future in as_completed(futures):
                            entity_id = futures[future]
                            entity_name = _get_entity_name(
                                stage_code, entity_id, tenant_id
                            )

                            try:
                                result = future.result()
                                cost = _extract_cost(result)
                                total_cost += cost

                                if isinstance(result, dict) and "gate_passed" in result:
                                    completion_status = (
                                        "completed"
                                        if result["gate_passed"]
                                        else "disqualified"
                                    )
                                else:
                                    completion_status = "completed"

                                done_count += 1
                                record_completion(
                                    tenant_id,
                                    tag_id,
                                    pipeline_run_id,
                                    entity_type,
                                    entity_id,
                                    stage_code,
                                    status=completion_status,
                                    cost_usd=cost,
                                )

                                # L1 auto-triage: also record triage completion
                                if stage_code == "l1" and entity_type == "company":
                                    _auto_record_triage(
                                        tenant_id,
                                        tag_id,
                                        pipeline_run_id,
                                        entity_id,
                                        result,
                                    )

                                _update_current_item(run_id, entity_name, "ok")
                                _update_stage_run(
                                    run_id,
                                    done=done_count,
                                    cost_usd=total_cost,
                                    failed=failed_count,
                                )
                                logger.info(
                                    "[%s] Enriched %s (%d/%d)",
                                    stage_code,
                                    entity_name,
                                    done_count,
                                    len(batch_ids),
                                )
                            except Exception as e:
                                failed_count += 1
                                record_completion(
                                    tenant_id,
                                    tag_id,
                                    pipeline_run_id,
                                    entity_type,
                                    entity_id,
                                    stage_code,
                                    status="failed",
                                    error=str(e),
                                )
                                _update_current_item(run_id, entity_name, "failed")
                                logger.warning(
                                    "DAG stage %s item %s failed: %s",
                                    stage_code,
                                    entity_id,
                                    e,
                                )
                                _update_stage_run(
                                    run_id,
                                    done=done_count,
                                    failed=failed_count,
                                    cost_usd=total_cost,
                                    error=str(e)[:500],
                                )

                            if sample_remaining is not None:
                                sample_remaining -= 1
                                if sample_remaining <= 0:
                                    break
            else:
                # No new items — check termination
                preds_done = _predecessors_terminal(predecessor_run_ids)
                if preds_done:
                    final_status = (
                        "completed" if done_count > 0 or failed_count == 0 else "failed"
                    )
                    _update_stage_run(
                        run_id,
                        status=final_status,
                        done=done_count,
                        failed=failed_count,
                        cost_usd=total_cost,
                    )
                    logger.info(
                        "DAG stage %s %s: %d done, %d failed, $%.4f",
                        stage_code,
                        final_status,
                        done_count,
                        failed_count,
                        total_cost,
                    )
                    return

            time.sleep(REACTIVE_POLL_INTERVAL)


def _predecessors_terminal(predecessor_run_ids):
    """Check if all predecessor stage_runs are in a terminal state."""
    if not predecessor_run_ids:
        return True

    placeholders = ", ".join(f":pred_{i}" for i in range(len(predecessor_run_ids)))
    params = {f"pred_{i}": str(rid) for i, rid in enumerate(predecessor_run_ids)}
    sql = f"""
        SELECT COUNT(*) FROM stage_runs
        WHERE id IN ({placeholders})
          AND status NOT IN ('completed', 'failed', 'stopped')
    """
    row = db.session.execute(text(sql), params).fetchone()
    return row[0] == 0


# ---------------------------------------------------------------------------
# DAG pipeline coordinator
# ---------------------------------------------------------------------------


def _update_pipeline_run(pipeline_run_id, **kwargs):
    """Update a pipeline_runs record."""
    set_parts = []
    params = {"id": str(pipeline_run_id)}
    for key, value in kwargs.items():
        set_parts.append(f"{key} = :{key}")
        params[key] = value

    if "completed_at" not in kwargs and kwargs.get("status") in (
        "completed",
        "failed",
        "stopped",
    ):
        set_parts.append("completed_at = :completed_at")
        params["completed_at"] = datetime.datetime.utcnow().isoformat()

    if not set_parts:
        return

    sql = f"UPDATE pipeline_runs SET {', '.join(set_parts)} WHERE id = :id"
    db.session.execute(text(sql), params)
    db.session.commit()


def coordinate_dag_pipeline(app, pipeline_run_id, stage_run_ids):
    """Coordinator thread: polls all stage statuses and marks pipeline complete."""
    with app.app_context():
        logger.info("DAG pipeline coordinator started (run %s)", pipeline_run_id)

        while True:
            time.sleep(10)

            try:
                # Check if pipeline was requested to stop
                prow = db.session.execute(
                    text("SELECT status FROM pipeline_runs WHERE id = :id"),
                    {"id": str(pipeline_run_id)},
                ).fetchone()

                if prow and prow[0] == "stopping":
                    for stage, run_id in stage_run_ids.items():
                        row = db.session.execute(
                            text("SELECT status FROM stage_runs WHERE id = :id"),
                            {"id": str(run_id)},
                        ).fetchone()
                        if row and row[0] in ("pending", "running"):
                            db.session.execute(
                                text(
                                    "UPDATE stage_runs SET status = 'stopping' WHERE id = :id"
                                ),
                                {"id": str(run_id)},
                            )
                    db.session.commit()

                # Check all stage statuses
                all_terminal = True
                total_cost = 0.0
                any_failed = False

                for stage, run_id in stage_run_ids.items():
                    row = db.session.execute(
                        text("SELECT status, cost_usd FROM stage_runs WHERE id = :id"),
                        {"id": str(run_id)},
                    ).fetchone()
                    if row:
                        if row[0] not in ("completed", "failed", "stopped"):
                            all_terminal = False
                        if row[0] == "failed":
                            any_failed = True
                        total_cost += float(row[1] or 0)

                if all_terminal:
                    final_status = (
                        "stopped"
                        if (prow and prow[0] == "stopping")
                        else "failed"
                        if any_failed
                        else "completed"
                    )
                    _update_pipeline_run(
                        pipeline_run_id, status=final_status, cost_usd=total_cost
                    )
                    logger.info(
                        "DAG pipeline %s %s, total cost $%.4f",
                        pipeline_run_id,
                        final_status,
                        total_cost,
                    )
                    return
                else:
                    _update_pipeline_run(pipeline_run_id, cost_usd=total_cost)

            except Exception as e:
                logger.error("DAG pipeline coordinator error: %s", e)


def start_dag_pipeline(
    app,
    pipeline_run_id,
    stages_to_run,
    tenant_id,
    tag_id,
    owner_id=None,
    tier_filter=None,
    stage_run_ids=None,
    soft_deps_enabled=None,
    sample_size=None,
    entity_ids=None,
    re_enrich_horizons=None,
):
    """Spawn DAG-aware reactive stage threads for all stages + coordinator.

    Unlike start_pipeline_threads, this uses completion-record-based eligibility
    and records completions after each entity.
    """
    sorted_stages = topo_sort(stages_to_run, soft_deps_enabled)
    threads = {}

    for stage_code in sorted_stages:
        run_id = stage_run_ids[stage_code]

        # Build predecessor run IDs from the stage's deps
        deps = resolve_deps(stage_code, soft_deps_enabled)
        predecessor_run_ids = [
            stage_run_ids[dep] for dep in deps if dep in stage_run_ids
        ]

        t = threading.Thread(
            target=run_dag_stage,
            args=(app, run_id, stage_code, pipeline_run_id, tenant_id, tag_id),
            kwargs={
                "owner_id": owner_id,
                "tier_filter": tier_filter,
                "soft_deps_enabled": soft_deps_enabled,
                "predecessor_run_ids": predecessor_run_ids,
                "sample_size": sample_size,
                "entity_ids": entity_ids,
                "re_enrich_horizons": re_enrich_horizons,
            },
            daemon=True,
            name=f"dag-{stage_code}-{run_id}",
        )
        t.start()
        threads[stage_code] = t

    # Coordinator thread
    coord = threading.Thread(
        target=coordinate_dag_pipeline,
        args=(app, pipeline_run_id, stage_run_ids),
        daemon=True,
        name=f"dag-coord-{pipeline_run_id}",
    )
    coord.start()

    return threads
