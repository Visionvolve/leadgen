"""Pipeline engine: background threads that process entities through n8n workflows.

Supports two modes:
1. Single-stage: run_stage() processes a fixed list of entity IDs (individual stage buttons)
2. Reactive parallel: run_stage_reactive() polls for new eligible IDs as predecessors complete
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from flask import current_app
from sqlalchemy import text

from ..models import db

logger = logging.getLogger(__name__)

N8N_WEBHOOK_PATHS = {
    "l1": "/webhook/l1-enrich",
    "l2": "/webhook/l2-enrich",
    "person": "/webhook/person-enrich",
}

# Stages that have workflows wired up (n8n or direct Python)
AVAILABLE_STAGES = {"l1", "l2", "person", "registry"}
# Stages that call Python directly instead of n8n
DIRECT_STAGES = {
    "l1",
    "l2",
    "person",
    "registry",
    "triage",
    "qc",
    "signals",
    "news",
    "social",
    "career",
    "contact_details",
}
# Stages that are manual gates (not executable)
COMING_SOON_STAGES = {"review"}
# Legacy aliases for backward compat with old API calls
_LEGACY_STAGE_ALIASES = {
    "ares": "registry",
    "brreg": "registry",
    "prh": "registry",
    "recherche": "registry",
    "isir": "registry",
}

# Stage predecessors for reactive pipeline (which stage feeds into which)
STAGE_PREDECESSORS = {
    "l1": [],  # L1 has no predecessor — processes fixed set
    "l2": ["l1"],  # L2 watches L1 (triage is auto-output of L1)
    "person": ["l2"],  # Person watches L2
    "registry": [],  # Unified registry — independent, auto-detects country
    "qc": ["l2", "person"],  # QC runs after L2 + person are done
}

REACTIVE_POLL_INTERVAL = 15  # seconds between re-querying eligible IDs
COORDINATOR_POLL_INTERVAL = 10  # seconds between checking all stage statuses

ELIGIBILITY_QUERIES = {
    "l1": """
        SELECT c.id FROM companies c
        WHERE c.tenant_id = :tenant_id {tag_clause}
          AND c.status IN ('new', 'enrichment_failed')
          {owner_clause}
        ORDER BY c.name
    """,
    "l2": """
        SELECT c.id FROM companies c
        WHERE c.tenant_id = :tenant_id {tag_clause}
          AND c.status = 'triage_passed'
          {owner_clause}
          {tier_clause}
        ORDER BY c.name
    """,
    "person": """
        SELECT ct.id FROM contacts ct
        JOIN companies c ON ct.company_id = c.id
        WHERE ct.tenant_id = :tenant_id {contact_tag_clause}
          AND c.status = 'enriched_l2' AND NOT ct.processed_enrich
          {owner_clause}
        ORDER BY ct.last_name, ct.first_name
    """,
    "signals": """
        SELECT c.id FROM companies c
        WHERE c.tenant_id = :tenant_id {tag_clause}
          AND c.status IN ('triage_passed', 'enriched_l2')
          {owner_clause}
          {tier_clause}
        ORDER BY c.name
    """,
    "registry": """
        SELECT c.id FROM companies c
        LEFT JOIN company_legal_profile clp ON clp.company_id = c.id
        WHERE c.tenant_id = :tenant_id {tag_clause}
          AND clp.company_id IS NULL
          AND (
            c.hq_country IN ('CZ', 'Czech Republic', 'Czechia',
                             'NO', 'Norway', 'Norge',
                             'FI', 'Finland', 'Suomi',
                             'FR', 'France')
            OR c.domain LIKE '%%.cz'
            OR c.domain LIKE '%%.no'
            OR c.domain LIKE '%%.fi'
            OR c.domain LIKE '%%.fr'
            OR c.ico IS NOT NULL
          )
          {owner_clause}
        ORDER BY c.name
    """,
    "news": """
        SELECT c.id FROM companies c
        WHERE c.tenant_id = :tenant_id {tag_clause}
          AND c.status IN ('triage_passed', 'enriched_l2')
          {owner_clause}
          {tier_clause}
        ORDER BY c.name
    """,
    "social": """
        SELECT ct.id FROM contacts ct
        JOIN companies c ON ct.company_id = c.id
        WHERE ct.tenant_id = :tenant_id {contact_tag_clause}
          AND c.status = 'enriched_l2' AND NOT ct.processed_enrich
          {owner_clause}
        ORDER BY ct.last_name, ct.first_name
    """,
    "career": """
        SELECT ct.id FROM contacts ct
        JOIN companies c ON ct.company_id = c.id
        WHERE ct.tenant_id = :tenant_id {contact_tag_clause}
          AND c.status = 'enriched_l2' AND NOT ct.processed_enrich
          {owner_clause}
        ORDER BY ct.last_name, ct.first_name
    """,
    "contact_details": """
        SELECT ct.id FROM contacts ct
        JOIN companies c ON ct.company_id = c.id
        WHERE ct.tenant_id = :tenant_id {contact_tag_clause}
          AND c.status = 'enriched_l2' AND NOT ct.processed_enrich
          {owner_clause}
        ORDER BY ct.last_name, ct.first_name
    """,
    "qc": """
        SELECT c.id FROM companies c
        WHERE c.tenant_id = :tenant_id {tag_clause}
          AND c.status = 'enriched_l2'
          {owner_clause}
          {tier_clause}
        ORDER BY c.name
    """,
}


def _build_tag_clauses(tag_id, params):
    """Build tag filter clauses. When tag_id is None, no tag filter is applied."""
    if tag_id:
        params["tag_id"] = str(tag_id)
        return "AND c.tag_id = :tag_id", "AND ct.tag_id = :tag_id"
    return "", ""


def get_eligible_ids(tenant_id, tag_id, stage, owner_id=None, tier_filter=None):
    """Query PG for eligible company/contact IDs for a given stage."""
    stage = _LEGACY_STAGE_ALIASES.get(stage, stage)
    template = ELIGIBILITY_QUERIES.get(stage)
    if not template:
        return []

    params = {"tenant_id": str(tenant_id)}
    tag_clause, contact_tag_clause = _build_tag_clauses(tag_id, params)

    owner_clause = ""
    if owner_id:
        if stage in ("person", "social", "career", "contact_details"):
            owner_clause = "AND ct.owner_id = :owner_id"
        else:
            owner_clause = "AND c.owner_id = :owner_id"
        params["owner_id"] = str(owner_id)

    tier_clause = ""
    if tier_filter and stage not in ("person", "social", "career", "contact_details"):
        from ..display import tier_db_values

        tier_vals = tier_db_values(tier_filter)
        if tier_vals:
            placeholders = ", ".join(f":tier_{i}" for i in range(len(tier_vals)))
            tier_clause = f"AND c.tier IN ({placeholders})"
            for i, tv in enumerate(tier_vals):
                params[f"tier_{i}"] = tv

    sql = template.format(
        tag_clause=tag_clause,
        contact_tag_clause=contact_tag_clause,
        owner_clause=owner_clause,
        tier_clause=tier_clause,
    )
    rows = db.session.execute(text(sql), params).fetchall()
    return [str(row[0]) for row in rows]


def count_eligible(tenant_id, tag_id, stage, owner_id=None, tier_filter=None):
    """Count eligible entities for a stage without loading IDs into memory."""
    stage = _LEGACY_STAGE_ALIASES.get(stage, stage)
    template = ELIGIBILITY_QUERIES.get(stage)
    if not template:
        return 0

    params = {"tenant_id": str(tenant_id)}
    tag_clause, contact_tag_clause = _build_tag_clauses(tag_id, params)

    owner_clause = ""
    if owner_id:
        if stage in ("person", "social", "career", "contact_details"):
            owner_clause = "AND ct.owner_id = :owner_id"
        else:
            owner_clause = "AND c.owner_id = :owner_id"
        params["owner_id"] = str(owner_id)

    tier_clause = ""
    if tier_filter and stage not in ("person", "social", "career", "contact_details"):
        from ..display import tier_db_values

        tier_vals = tier_db_values(tier_filter)
        if tier_vals:
            placeholders = ", ".join(f":tier_{i}" for i in range(len(tier_vals)))
            tier_clause = f"AND c.tier IN ({placeholders})"
            for i, tv in enumerate(tier_vals):
                params[f"tier_{i}"] = tv

    # Wrap as COUNT(*)
    inner = template.format(
        tag_clause=tag_clause,
        contact_tag_clause=contact_tag_clause,
        owner_clause=owner_clause,
        tier_clause=tier_clause,
    )
    sql = f"SELECT COUNT(*) FROM ({inner}) sub"
    row = db.session.execute(text(sql), params).fetchone()
    return row[0] if row else 0


def call_n8n_webhook(stage, data, timeout=120):
    """Call n8n sub-workflow via webhook. Synchronous -- waits for result."""
    base_url = current_app.config.get("N8N_BASE_URL", "https://n8n.visionvolve.com")
    path = N8N_WEBHOOK_PATHS.get(stage)
    if not path:
        raise ValueError(f"No webhook path for stage: {stage}")

    url = base_url + path
    resp = requests.post(url, json=data, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def update_run(run_id, **kwargs):
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
        params["completed_at"] = datetime.now(timezone.utc).isoformat()

    if not set_parts:
        return

    sql = f"UPDATE stage_runs SET {', '.join(set_parts)} WHERE id = :id"
    db.session.execute(text(sql), params)
    db.session.commit()


def _check_stop_signal(run_id):
    """Check if this stage_run has been requested to stop."""
    row = db.session.execute(
        text("SELECT status FROM stage_runs WHERE id = :id"),
        {"id": str(run_id)},
    ).fetchone()
    return row and row[0] == "stopping"


def _extract_cost(result):
    """Extract enrichment cost from n8n webhook result."""
    if isinstance(result, list) and len(result) > 0:
        return float(result[0].get("enrichment_cost_usd", 0) or 0)
    elif isinstance(result, dict):
        return float(result.get("enrichment_cost_usd", 0) or 0)
    return 0


def _data_key_for_stage(stage):
    """Get the JSON key name for the entity ID sent to n8n."""
    return (
        "contact_id"
        if stage in ("person", "social", "career", "contact_details")
        else "company_id"
    )


def _get_entity_name(stage, entity_id, tenant_id):
    """Look up a display name for the entity being processed."""
    try:
        if stage in ("person", "social", "career", "contact_details"):
            row = db.session.execute(
                text(
                    "SELECT first_name, last_name FROM contacts WHERE id = :id AND tenant_id = :t"
                ),
                {"id": entity_id, "t": str(tenant_id)},
            ).fetchone()
            if row:
                return f"{row[0] or ''} {row[1] or ''}".strip() or entity_id
        else:
            row = db.session.execute(
                text("SELECT name FROM companies WHERE id = :id AND tenant_id = :t"),
                {"id": entity_id, "t": str(tenant_id)},
            ).fetchone()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    return entity_id


def _update_current_item(run_id, entity_name, status="processing", error_msg=None):
    """Store the current item being processed in the stage_run config."""
    try:
        row = db.session.execute(
            text("SELECT config FROM stage_runs WHERE id = :id"),
            {"id": str(run_id)},
        ).fetchone()
        if row:
            import json as _json

            config = _json.loads(row[0] or "{}")
            config["current_item"] = {"name": entity_name, "status": status}

            # Keep a rolling log of last 20 items
            recent = config.get("recent_items", [])
            if status != "processing":
                recent.append({"name": entity_name, "status": status})
                if len(recent) > 20:
                    recent = recent[-20:]
                config["recent_items"] = recent

            # Track failed items separately (keep all, capped at 100)
            if status == "failed":
                failed_items = config.get("failed_items", [])
                entry = {"name": entity_name}
                if error_msg:
                    entry["error"] = str(error_msg)[:200]
                failed_items.append(entry)
                if len(failed_items) > 100:
                    failed_items = failed_items[-100:]
                config["failed_items"] = failed_items

            db.session.execute(
                text("UPDATE stage_runs SET config = :config WHERE id = :id"),
                {"id": str(run_id), "config": _json.dumps(config)},
            )
            db.session.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Entity processing dispatch
# ---------------------------------------------------------------------------


def _process_registry_unified(company_id, tenant_id):
    """Process a company through the unified registry orchestrator."""
    from .registries.orchestrator import RegistryOrchestrator

    row = db.session.execute(
        text("""
            SELECT name, ico, hq_country, domain
            FROM companies WHERE id = :id AND tenant_id = :t
        """),
        {"id": company_id, "t": str(tenant_id)},
    ).fetchone()

    if not row:
        return {
            "status": "error",
            "error": "Company not found",
            "enrichment_cost_usd": 0,
        }

    orchestrator = RegistryOrchestrator()
    result = orchestrator.enrich_company(
        company_id=company_id,
        tenant_id=str(tenant_id),
        name=row[0],
        reg_id=row[1],
        hq_country=row[2],
        domain=row[3],
    )
    result.setdefault("enrichment_cost_usd", 0)
    return result


def _load_icp_triage_rules(tenant_id):
    """Load ICP-derived triage rules from the 'From GTM Strategy' EnrichmentConfig.

    Returns the rules dict or None if no ICP triage config exists.
    """
    import json as _json
    from ..models import EnrichmentConfig

    ec = EnrichmentConfig.query.filter_by(
        tenant_id=tenant_id, name="From GTM Strategy"
    ).first()
    if not ec or not ec.config:
        return None

    config = ec.config
    if isinstance(config, str):
        try:
            config = _json.loads(config)
        except (ValueError, TypeError):
            return None

    return config if isinstance(config, dict) else None


def _process_triage(company_id, tenant_id, triage_rules=None):
    """Run triage evaluation on a company using L1 enrichment data.

    Reads company fields + L1 raw_response to build the evaluation context,
    then calls evaluate_triage(). When no explicit triage_rules are provided,
    loads ICP-derived rules from the tenant's GTM Strategy config.

    Returns:
        dict with gate_passed, gate_reasons, enrichment_cost_usd
    """
    import json as _json
    from .triage_evaluator import evaluate_triage, DEFAULT_RULES

    row = db.session.execute(
        text("""
            SELECT c.tier, c.industry, c.geo_region,
                   c.verified_revenue_eur_m, c.verified_employees,
                   el.qc_flags, el.raw_response
            FROM companies c
            LEFT JOIN company_enrichment_l1 el ON el.company_id = c.id
            WHERE c.id = :id
        """),
        {"id": str(company_id)},
    ).fetchone()

    if not row:
        return {
            "gate_passed": False,
            "gate_reasons": ["company_not_found"],
            "enrichment_cost_usd": 0,
        }

    tier, industry, geo_region, revenue, employees, qc_flags_raw, raw_resp = row

    # Parse QC flags
    qc_flags = []
    if qc_flags_raw:
        try:
            qc_flags = (
                _json.loads(qc_flags_raw)
                if isinstance(qc_flags_raw, str)
                else (qc_flags_raw or [])
            )
        except (ValueError, TypeError):
            qc_flags = []

    # Parse B2B from raw response
    is_b2b = None
    if raw_resp:
        try:
            resp_data = (
                _json.loads(raw_resp) if isinstance(raw_resp, str) else (raw_resp or {})
            )
            is_b2b = resp_data.get("b2b")
        except (ValueError, TypeError):
            pass

    company_data = {
        "tier": tier,
        "industry": industry,
        "geo_region": geo_region,
        "revenue_eur_m": float(revenue) if revenue else None,
        "employees": int(employees) if employees else None,
        "is_b2b": is_b2b,
        "qc_flags": qc_flags,
    }

    # Priority: explicit rules > ICP-derived config > defaults
    if triage_rules:
        rules = triage_rules
    else:
        icp_rules = _load_icp_triage_rules(tenant_id) if tenant_id else None
        rules = icp_rules or DEFAULT_RULES
    result = evaluate_triage(company_data, rules)

    # Update company status based on triage result
    if result["passed"]:
        db.session.execute(
            text("UPDATE companies SET status = 'triage_passed' WHERE id = :id"),
            {"id": str(company_id)},
        )
    else:
        reasons_str = "; ".join(result["reasons"])[:500]
        db.session.execute(
            text("""UPDATE companies SET status = 'triage_disqualified',
                    triage_notes = :notes WHERE id = :id"""),
            {"id": str(company_id), "notes": reasons_str},
        )
    db.session.commit()

    return {
        "gate_passed": result["passed"],
        "gate_reasons": result["reasons"],
        "enrichment_cost_usd": 0,
    }


def _process_entity(
    stage, entity_id, tenant_id=None, previous_data=None, triage_rules=None
):
    """Dispatch entity processing to the right backend (n8n or direct Python)."""
    # Resolve legacy stage names
    stage = _LEGACY_STAGE_ALIASES.get(stage, stage)

    if stage in DIRECT_STAGES:
        if stage == "l1":
            from .l1_enricher import enrich_l1

            return enrich_l1(entity_id, tenant_id, previous_data=previous_data)
        if stage == "l2":
            from .l2_enricher import enrich_l2

            return enrich_l2(entity_id, tenant_id, previous_data=previous_data)
        if stage == "person":
            from .person_enricher import enrich_person

            return enrich_person(entity_id, tenant_id, previous_data=previous_data)
        if stage == "registry":
            return _process_registry_unified(entity_id, tenant_id)
        if stage == "triage":
            return _process_triage(entity_id, tenant_id, triage_rules)
        if stage == "qc":
            from .qc_checker import run_qc

            return run_qc(entity_id, tenant_id)
        if stage == "social":
            from .social_enricher import enrich_social

            return enrich_social(entity_id, tenant_id, previous_data=previous_data)
        if stage == "career":
            from .career_enricher import enrich_career

            return enrich_career(entity_id, tenant_id, previous_data=previous_data)
        if stage == "contact_details":
            from .contact_details_enricher import enrich_contact_details

            return enrich_contact_details(
                entity_id, tenant_id, previous_data=previous_data
            )
        if stage == "signals":
            from .signals_enricher import enrich_signals

            return enrich_signals(entity_id, tenant_id)
        if stage == "news":
            from .news_enricher import enrich_news

            return enrich_news(entity_id, tenant_id)
        raise ValueError(f"No direct processor for stage: {stage}")
    # For webhook stages, include previous_data in the payload if provided
    payload = {_data_key_for_stage(stage): entity_id}
    if previous_data:
        payload["previous_data"] = previous_data
    return call_n8n_webhook(stage, payload)


# ---------------------------------------------------------------------------
# Safe resume: skip recently enriched entities
# ---------------------------------------------------------------------------

# Rate limiter for external API calls (e.g. Perplexity)
_api_semaphore = threading.Semaphore(5)  # default; overridden by config at runtime


def _is_recently_enriched(entity_id, stage, hours=24):
    """Check if entity was enriched for this stage within the last N hours.

    Returns False when hours <= 0 (effectively disabling the skip).
    """
    if hours <= 0:
        return False

    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        result = db.session.execute(
            text("""
                SELECT 1 FROM entity_stage_completions
                WHERE entity_id = :eid AND stage = :stage
                  AND status = 'completed'
                  AND completed_at > :cutoff
                LIMIT 1
            """),
            {"eid": str(entity_id), "stage": stage, "cutoff": cutoff},
        ).fetchone()
        return result is not None
    except Exception:
        return False


def _record_completion(entity_id, stage, run_id, tenant_id):
    """Write a completion record after successful enrichment."""
    import uuid as _uuid

    entity_type = (
        "contact"
        if stage in ("person", "social", "career", "contact_details")
        else "company"
    )
    try:
        # Look up tag_id from the entity
        tag_id = None
        if entity_type == "company":
            row = db.session.execute(
                text("SELECT tag_id FROM companies WHERE id = :id"),
                {"id": str(entity_id)},
            ).fetchone()
            if row:
                tag_id = row[0]
        else:
            row = db.session.execute(
                text("SELECT tag_id FROM contacts WHERE id = :id"),
                {"id": str(entity_id)},
            ).fetchone()
            if row:
                tag_id = row[0]

        params = {
            "id": str(_uuid.uuid4()),
            "tid": str(tenant_id),
            "tag_id": str(tag_id) if tag_id else None,
            "prid": str(run_id),
            "eid": str(entity_id),
            "etype": entity_type,
            "stage": stage,
        }

        try:
            # PostgreSQL upsert
            db.session.execute(
                text("""
                    INSERT INTO entity_stage_completions
                        (id, tenant_id, tag_id, pipeline_run_id, entity_type,
                         entity_id, stage, status, cost_usd)
                    VALUES (:id, :tid, :tag_id, :prid, :etype,
                            :eid, :stage, 'completed', 0)
                    ON CONFLICT (pipeline_run_id, entity_id, stage) DO NOTHING
                """),
                params,
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            # SQLite fallback: plain INSERT (ignore duplicate errors)
            try:
                db.session.execute(
                    text("""
                        INSERT INTO entity_stage_completions
                            (id, tenant_id, tag_id, pipeline_run_id, entity_type,
                             entity_id, stage, status, cost_usd)
                        VALUES (:id, :tid, :tag_id, :prid, :etype,
                                :eid, :stage, 'completed', 0)
                    """),
                    params,
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
    except Exception as e:
        logger.warning("Failed to record completion for %s/%s: %s", entity_id, stage, e)
        try:
            db.session.rollback()
        except Exception:
            pass


def _process_entity_worker(entity_id, stage, tenant_id, app):
    """Process one entity with rate limiting. Each thread gets its own app context."""
    with app.app_context():
        with _api_semaphore:
            return _process_entity(stage, entity_id, tenant_id)


# ---------------------------------------------------------------------------
# Single-stage execution (existing — for individual stage buttons)
# ---------------------------------------------------------------------------


def run_stage(app, run_id, stage, entity_ids, tenant_id=None):
    """Background thread: process entities with safe resume + parallel execution."""
    with app.app_context():
        max_workers = current_app.config.get("ENRICHMENT_MAX_WORKERS", 5)
        skip_hours = current_app.config.get("ENRICHMENT_SKIP_RECENT_HOURS", 24)

        total_cost = 0.0
        failed = 0
        skipped = 0
        done = 0

        update_run(run_id, status="running")

        # Phase 1: Filter out recently enriched entities (safe resume)
        to_process = []
        for entity_id in entity_ids:
            if _is_recently_enriched(entity_id, stage, hours=skip_hours):
                skipped += 1
            else:
                to_process.append(entity_id)

        total_entities = len(entity_ids)
        logger.info(
            "[%s] Processing %d entities (%d workers, skipping %d recently enriched)",
            stage,
            len(to_process),
            max_workers,
            skipped,
        )

        if not to_process:
            update_run(
                run_id,
                status="completed",
                done=total_entities,
                failed=0,
                cost_usd=0,
            )
            logger.info(
                "Stage run %s completed: all %d entities already enriched",
                run_id,
                skipped,
            )
            return

        # Phase 2: Process entities in parallel
        if max_workers <= 1:
            # Serial fallback
            for i, entity_id in enumerate(to_process):
                if _check_stop_signal(run_id):
                    update_run(
                        run_id,
                        status="stopped",
                        done=skipped + done,
                        failed=failed,
                        cost_usd=total_cost,
                    )
                    logger.info(
                        "Stage run %s stopped at item %d/%d",
                        run_id,
                        done,
                        len(to_process),
                    )
                    return

                entity_name = _get_entity_name(stage, entity_id, tenant_id)
                _update_current_item(run_id, entity_name, "processing")

                try:
                    result = _process_entity(stage, entity_id, tenant_id)
                    total_cost += _extract_cost(result)
                    done += 1
                    _record_completion(entity_id, stage, run_id, tenant_id)
                    _update_current_item(run_id, entity_name, "ok")
                    update_run(
                        run_id,
                        done=skipped + done,
                        cost_usd=total_cost,
                        failed=failed,
                    )
                except Exception as e:
                    db.session.rollback()
                    failed += 1
                    _update_current_item(
                        run_id, entity_name, "failed", error_msg=str(e)
                    )
                    logger.warning("Stage %s item %s failed: %s", stage, entity_id, e)
                    update_run(
                        run_id,
                        done=skipped + done,
                        failed=failed,
                        cost_usd=total_cost,
                        error=str(e)[:500],
                    )
        else:
            # Parallel execution with ThreadPoolExecutor
            app_obj = current_app._get_current_object()

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for entity_id in to_process:
                    if _check_stop_signal(run_id):
                        break
                    future = executor.submit(
                        _process_entity_worker,
                        entity_id,
                        stage,
                        tenant_id,
                        app_obj,
                    )
                    futures[future] = entity_id

                for future in as_completed(futures):
                    entity_id = futures[future]
                    entity_name = _get_entity_name(stage, entity_id, tenant_id)

                    try:
                        result = future.result()
                        total_cost += _extract_cost(result)
                        done += 1
                        _record_completion(entity_id, stage, run_id, tenant_id)
                        _update_current_item(run_id, entity_name, "ok")
                        update_run(
                            run_id,
                            done=skipped + done,
                            cost_usd=total_cost,
                            failed=failed,
                        )
                        logger.info(
                            "[%s] Enriched %s (%d/%d)",
                            stage,
                            entity_name,
                            done,
                            len(to_process),
                        )
                    except Exception as e:
                        failed += 1
                        _update_current_item(
                            run_id, entity_name, "failed", error_msg=str(e)
                        )
                        logger.warning(
                            "Stage %s item %s failed: %s", stage, entity_id, e
                        )
                        update_run(
                            run_id,
                            done=skipped + done,
                            failed=failed,
                            cost_usd=total_cost,
                            error=str(e)[:500],
                        )

        final_status = (
            "completed"
            if failed == 0
            else "failed"
            if failed == len(to_process)
            else "completed"
        )
        update_run(
            run_id,
            status=final_status,
            done=total_entities,
            failed=failed,
            cost_usd=total_cost,
        )
        logger.info(
            "Stage run %s %s: %d done, %d skipped, %d failed, $%.4f cost",
            run_id,
            final_status,
            done,
            skipped,
            failed,
            total_cost,
        )


def start_stage_thread(app, run_id, stage, entity_ids, tenant_id=None):
    """Spawn a background thread to run a pipeline stage."""
    t = threading.Thread(
        target=run_stage,
        args=(app, run_id, stage, entity_ids),
        kwargs={"tenant_id": tenant_id},
        daemon=True,
        name=f"stage-{stage}-{run_id}",
    )
    t.start()
    return t


# ---------------------------------------------------------------------------
# Reactive stage execution (for run-all pipeline mode)
# ---------------------------------------------------------------------------


def _predecessors_terminal(predecessor_run_ids):
    """Check if all predecessor stage_runs are in a terminal state."""
    if not predecessor_run_ids:
        return True  # No predecessors = always ready

    placeholders = ", ".join(f":pred_{i}" for i in range(len(predecessor_run_ids)))
    params = {f"pred_{i}": str(rid) for i, rid in enumerate(predecessor_run_ids)}
    sql = f"""
        SELECT COUNT(*) FROM stage_runs
        WHERE id IN ({placeholders})
          AND status NOT IN ('completed', 'failed', 'stopped')
    """
    row = db.session.execute(text(sql), params).fetchone()
    return row[0] == 0


def run_stage_reactive(
    app,
    run_id,
    stage,
    tenant_id,
    tag_id,
    owner_id=None,
    tier_filter=None,
    predecessor_run_ids=None,
    sample_size=None,
):
    """Background thread: reactive stage that polls for new eligible IDs.

    - Polls eligible IDs every REACTIVE_POLL_INTERVAL seconds
    - Processes new ones (skipping already-processed IDs)
    - Terminates when predecessors are all terminal AND no new eligible IDs
    - L1 has no predecessors: processes initial set, then finishes
    - sample_size: limit total entities processed across all polls
    """
    with app.app_context():
        skip_hours = current_app.config.get("ENRICHMENT_SKIP_RECENT_HOURS", 24)
        processed_ids = set()
        total_cost = 0.0
        done_count = 0
        failed_count = 0
        skipped_count = 0
        sample_remaining = sample_size  # None means unlimited

        update_run(run_id, status="running")
        logger.info(
            "Reactive stage %s started (run %s, sample=%s)", stage, run_id, sample_size
        )

        while True:
            # Check stop signal
            if _check_stop_signal(run_id):
                update_run(
                    run_id,
                    status="stopped",
                    done=done_count,
                    failed=failed_count,
                    cost_usd=total_cost,
                )
                logger.info("Reactive stage %s stopped at %d done", stage, done_count)
                return

            # Sample limit reached — finish
            if sample_remaining is not None and sample_remaining <= 0:
                final_status = "completed"
                if failed_count > 0 and done_count == 0:
                    final_status = "failed"
                update_run(
                    run_id,
                    status=final_status,
                    done=done_count,
                    failed=failed_count,
                    cost_usd=total_cost,
                )
                logger.info(
                    "Reactive stage %s sample limit reached: %d done", stage, done_count
                )
                return

            # Query for eligible IDs
            try:
                all_eligible = get_eligible_ids(
                    tenant_id, tag_id, stage, owner_id, tier_filter
                )
            except Exception as e:
                logger.error("Reactive stage %s eligibility query failed: %s", stage, e)
                time.sleep(REACTIVE_POLL_INTERVAL)
                continue

            new_ids = [eid for eid in all_eligible if eid not in processed_ids]

            # Safe resume: filter out recently enriched
            filtered_ids = []
            for eid in new_ids:
                if _is_recently_enriched(eid, stage, hours=skip_hours):
                    processed_ids.add(eid)
                    skipped_count += 1
                else:
                    filtered_ids.append(eid)
            new_ids = filtered_ids

            # Trim to sample limit
            if sample_remaining is not None and len(new_ids) > sample_remaining:
                new_ids = new_ids[:sample_remaining]

            if new_ids:
                # Update total (dynamic: done + failed + new_eligible)
                new_total = done_count + failed_count + len(new_ids)
                update_run(run_id, total=new_total)

                for entity_id in new_ids:
                    # Check stop signal between items
                    if _check_stop_signal(run_id):
                        update_run(
                            run_id,
                            status="stopped",
                            done=done_count,
                            failed=failed_count,
                            cost_usd=total_cost,
                        )
                        logger.info(
                            "Reactive stage %s stopped at %d done", stage, done_count
                        )
                        return

                    processed_ids.add(entity_id)
                    entity_name = _get_entity_name(stage, entity_id, tenant_id)
                    _update_current_item(run_id, entity_name, "processing")

                    try:
                        result = _process_entity(stage, entity_id, tenant_id)
                        total_cost += _extract_cost(result)
                        done_count += 1
                        _record_completion(entity_id, stage, run_id, tenant_id)
                        _update_current_item(run_id, entity_name, "ok")
                        update_run(
                            run_id,
                            done=done_count,
                            cost_usd=total_cost,
                            failed=failed_count,
                        )
                    except Exception as e:
                        db.session.rollback()  # Reset aborted transaction
                        failed_count += 1
                        _update_current_item(
                            run_id, entity_name, "failed", error_msg=str(e)
                        )
                        logger.warning(
                            "Reactive stage %s item %s failed: %s", stage, entity_id, e
                        )
                        update_run(
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
                # No new items — check termination condition
                preds_done = _predecessors_terminal(predecessor_run_ids)
                if preds_done:
                    # All predecessors are done and no new eligible items
                    final_status = "completed"
                    if failed_count > 0 and done_count == 0:
                        final_status = "failed"
                    update_run(
                        run_id,
                        status=final_status,
                        done=done_count,
                        failed=failed_count,
                        cost_usd=total_cost,
                    )
                    logger.info(
                        "Reactive stage %s %s: %d done, %d skipped, %d failed, $%.4f cost",
                        stage,
                        final_status,
                        done_count,
                        skipped_count,
                        failed_count,
                        total_cost,
                    )
                    return

            # Sleep before next poll cycle
            time.sleep(REACTIVE_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Pipeline coordinator (for run-all)
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
        params["completed_at"] = datetime.now(timezone.utc).isoformat()

    if not set_parts:
        return

    sql = f"UPDATE pipeline_runs SET {', '.join(set_parts)} WHERE id = :id"
    db.session.execute(text(sql), params)
    db.session.commit()


def _update_pipeline_stages_json(pipeline_run_id, stage_run_map):
    """Update the stages JSONB column on pipeline_runs."""
    import json

    stages_json = json.dumps({k: str(v) for k, v in stage_run_map.items()})
    db.session.execute(
        text("UPDATE pipeline_runs SET stages = CAST(:stages AS jsonb) WHERE id = :id"),
        {"id": str(pipeline_run_id), "stages": stages_json},
    )
    db.session.commit()


def coordinate_pipeline(app, pipeline_run_id, stage_run_ids):
    """Coordinator thread: polls all stage statuses and marks pipeline complete.

    Args:
        pipeline_run_id: UUID of the pipeline_runs record
        stage_run_ids: dict of stage_name → stage_run_id
    """
    with app.app_context():
        logger.info("Pipeline coordinator started (run %s)", pipeline_run_id)

        while True:
            time.sleep(COORDINATOR_POLL_INTERVAL)

            try:
                # Check if pipeline was requested to stop
                prow = db.session.execute(
                    text("SELECT status FROM pipeline_runs WHERE id = :id"),
                    {"id": str(pipeline_run_id)},
                ).fetchone()

                if prow and prow[0] == "stopping":
                    # Signal all active stages to stop
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
                        "Pipeline %s %s, total cost $%.4f",
                        pipeline_run_id,
                        final_status,
                        total_cost,
                    )
                    return
                else:
                    # Update running cost
                    _update_pipeline_run(pipeline_run_id, cost_usd=total_cost)

            except Exception as e:
                logger.error("Pipeline coordinator error: %s", e)


def start_pipeline_threads(
    app,
    pipeline_run_id,
    stages_to_run,
    tenant_id,
    tag_id,
    owner_id=None,
    tier_filter=None,
    stage_run_ids=None,
    sample_size=None,
):
    """Spawn reactive stage threads for all stages + coordinator thread.

    Args:
        stages_to_run: list of stage names to run (e.g. ["l1", "l2", "person"])
        stage_run_ids: dict of stage_name → stage_run_id (pre-created)
        sample_size: optional limit on how many entities to process per stage
    """
    threads = {}

    for stage in stages_to_run:
        run_id = stage_run_ids[stage]
        predecessor_stages = STAGE_PREDECESSORS.get(stage, [])
        predecessor_run_ids = [
            stage_run_ids[ps] for ps in predecessor_stages if ps in stage_run_ids
        ]

        t = threading.Thread(
            target=run_stage_reactive,
            args=(app, run_id, stage, tenant_id, tag_id),
            kwargs={
                "owner_id": owner_id,
                "tier_filter": tier_filter,
                "predecessor_run_ids": predecessor_run_ids,
                "sample_size": sample_size,
            },
            daemon=True,
            name=f"reactive-{stage}-{run_id}",
        )
        t.start()
        threads[stage] = t

    # Coordinator thread
    coord = threading.Thread(
        target=coordinate_pipeline,
        args=(app, pipeline_run_id, stage_run_ids),
        daemon=True,
        name=f"coordinator-{pipeline_run_id}",
    )
    coord.start()

    return threads
