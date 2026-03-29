"""Tests for safe resume (skip recently enriched) + parallel execution."""

import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def seed_data(db):
    """Create tenant, tag, stage_run, and company for testing."""
    from api.models import Tenant, Tag, Company, StageRun

    tenant = Tenant(name="Test Corp", slug="test-resume", is_active=True)
    db.session.add(tenant)
    db.session.flush()

    tag = Tag(name="test-tag", tenant_id=tenant.id)
    db.session.add(tag)
    db.session.flush()

    # Create a stage_run record using the ORM model
    stage_run = StageRun(
        tenant_id=tenant.id,
        tag_id=tag.id,
        stage="l1",
        status="pending",
        total=0,
        done=0,
        failed=0,
        cost_usd=0,
    )
    db.session.add(stage_run)
    db.session.flush()

    # Create test companies
    companies = []
    for i in range(5):
        c = Company(
            name=f"Company {i}",
            tenant_id=tenant.id,
            tag_id=tag.id,
            status="new",
        )
        db.session.add(c)
        db.session.flush()
        companies.append(c)

    db.session.commit()

    return {
        "tenant": tenant,
        "tag": tag,
        "run_id": str(stage_run.id),
        "companies": companies,
    }


class TestIsRecentlyEnriched:
    """Tests for the _is_recently_enriched function."""

    def test_returns_true_for_recent_completion(self, app, db, seed_data):
        """Entity enriched within the last 24h should be skipped."""
        from api.services.pipeline_engine import _is_recently_enriched

        company = seed_data["companies"][0]
        tenant = seed_data["tenant"]
        tag = seed_data["tag"]

        # Insert a recent completion record
        db.session.execute(
            db.text("""
                INSERT INTO entity_stage_completions
                    (id, tenant_id, tag_id, entity_type, entity_id, stage, status, completed_at)
                VALUES (:id, :tid, :tag_id, 'company', :eid, 'l1', 'completed', :now)
            """),
            {
                "id": str(uuid.uuid4()),
                "tid": str(tenant.id),
                "tag_id": str(tag.id),
                "eid": str(company.id),
                "now": datetime.now(timezone.utc).isoformat(),
            },
        )
        db.session.commit()

        with app.app_context():
            assert _is_recently_enriched(company.id, "l1", hours=24) is True

    def test_returns_false_for_old_completion(self, app, db, seed_data):
        """Entity enriched more than 24h ago should not be skipped."""
        from api.services.pipeline_engine import _is_recently_enriched

        company = seed_data["companies"][1]
        tenant = seed_data["tenant"]
        tag = seed_data["tag"]

        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        db.session.execute(
            db.text("""
                INSERT INTO entity_stage_completions
                    (id, tenant_id, tag_id, entity_type, entity_id, stage, status, completed_at)
                VALUES (:id, :tid, :tag_id, 'company', :eid, 'l1', 'completed', :old)
            """),
            {
                "id": str(uuid.uuid4()),
                "tid": str(tenant.id),
                "tag_id": str(tag.id),
                "eid": str(company.id),
                "old": old_time,
            },
        )
        db.session.commit()

        with app.app_context():
            assert _is_recently_enriched(company.id, "l1", hours=24) is False

    def test_returns_false_for_no_completion(self, app, db, seed_data):
        """Entity with no completion record should not be skipped."""
        from api.services.pipeline_engine import _is_recently_enriched

        company = seed_data["companies"][2]

        with app.app_context():
            assert _is_recently_enriched(company.id, "l1", hours=24) is False

    def test_returns_false_for_failed_completion(self, app, db, seed_data):
        """Failed completions should not count as recently enriched."""
        from api.services.pipeline_engine import _is_recently_enriched

        company = seed_data["companies"][3]
        tenant = seed_data["tenant"]
        tag = seed_data["tag"]

        db.session.execute(
            db.text("""
                INSERT INTO entity_stage_completions
                    (id, tenant_id, tag_id, entity_type, entity_id, stage, status, completed_at)
                VALUES (:id, :tid, :tag_id, 'company', :eid, 'l1', 'failed', :now)
            """),
            {
                "id": str(uuid.uuid4()),
                "tid": str(tenant.id),
                "tag_id": str(tag.id),
                "eid": str(company.id),
                "now": datetime.now(timezone.utc).isoformat(),
            },
        )
        db.session.commit()

        with app.app_context():
            assert _is_recently_enriched(company.id, "l1", hours=24) is False


class TestRunStageResume:
    """Tests for run_stage with safe resume behavior."""

    @patch("api.services.pipeline_engine._process_entity")
    def test_skips_recently_enriched_entities(self, mock_process, app, db, seed_data):
        """run_stage should skip entities that were recently enriched."""
        from api.services.pipeline_engine import run_stage

        tenant = seed_data["tenant"]
        tag = seed_data["tag"]
        run_id = seed_data["run_id"]
        companies = seed_data["companies"]

        # Mark first 2 companies as recently enriched
        for c in companies[:2]:
            db.session.execute(
                db.text("""
                    INSERT INTO entity_stage_completions
                        (id, tenant_id, tag_id, entity_type, entity_id, stage, status, completed_at)
                    VALUES (:id, :tid, :tag_id, 'company', :eid, 'l1', 'completed', :now)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "tid": str(tenant.id),
                    "tag_id": str(tag.id),
                    "eid": str(c.id),
                    "now": datetime.now(timezone.utc).isoformat(),
                },
            )
        db.session.commit()

        mock_process.return_value = {"enrichment_cost_usd": 0.01}

        entity_ids = [str(c.id) for c in companies]

        # Force serial execution for predictable test
        app.config["ENRICHMENT_MAX_WORKERS"] = 1
        app.config["ENRICHMENT_SKIP_RECENT_HOURS"] = 24

        run_stage(app, run_id, "l1", entity_ids, tenant_id=tenant.id)

        # Should only process 3 entities (5 total - 2 skipped)
        assert mock_process.call_count == 3

    @patch("api.services.pipeline_engine._process_entity")
    def test_records_completion_after_success(self, mock_process, app, db, seed_data):
        """run_stage should write completion records after successful enrichment."""
        from api.services.pipeline_engine import run_stage

        tenant = seed_data["tenant"]
        run_id = seed_data["run_id"]
        company = seed_data["companies"][0]

        mock_process.return_value = {"enrichment_cost_usd": 0.02}

        app.config["ENRICHMENT_MAX_WORKERS"] = 1
        app.config["ENRICHMENT_SKIP_RECENT_HOURS"] = 24

        run_stage(app, run_id, "l1", [str(company.id)], tenant_id=tenant.id)

        # Check that a completion record was written
        with app.app_context():
            row = db.session.execute(
                db.text("""
                    SELECT status FROM entity_stage_completions
                    WHERE entity_id = :eid AND stage = 'l1'
                """),
                {"eid": str(company.id)},
            ).fetchone()
            assert row is not None
            assert row[0] == "completed"


class TestParallelExecution:
    """Tests for parallel execution with ThreadPoolExecutor."""

    @patch("api.services.pipeline_engine._process_entity")
    def test_parallel_processes_multiple_entities(
        self, mock_process, app, db, seed_data
    ):
        """Parallel execution should process all entities."""
        from api.services.pipeline_engine import run_stage

        tenant = seed_data["tenant"]
        run_id = seed_data["run_id"]
        companies = seed_data["companies"]

        mock_process.return_value = {"enrichment_cost_usd": 0.01}

        entity_ids = [str(c.id) for c in companies]

        app.config["ENRICHMENT_MAX_WORKERS"] = 3
        app.config["ENRICHMENT_SKIP_RECENT_HOURS"] = 24

        run_stage(app, run_id, "l1", entity_ids, tenant_id=tenant.id)

        # All 5 should be processed
        assert mock_process.call_count == 5

    @patch("api.services.pipeline_engine._process_entity")
    def test_parallel_handles_failures_gracefully(
        self, mock_process, app, db, seed_data
    ):
        """Parallel execution should continue processing after individual failures."""
        from api.services.pipeline_engine import run_stage

        tenant = seed_data["tenant"]
        run_id = seed_data["run_id"]
        companies = seed_data["companies"][:3]

        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("Enrichment API error")
            return {"enrichment_cost_usd": 0.01}

        mock_process.side_effect = side_effect

        entity_ids = [str(c.id) for c in companies]

        # Use serial to get deterministic failure ordering
        app.config["ENRICHMENT_MAX_WORKERS"] = 1
        app.config["ENRICHMENT_SKIP_RECENT_HOURS"] = 24

        run_stage(app, run_id, "l1", entity_ids, tenant_id=tenant.id)

        # All 3 should be attempted
        assert mock_process.call_count == 3

        # Check final stage_run status
        with app.app_context():
            row = db.session.execute(
                db.text("SELECT status, failed FROM stage_runs WHERE id = :id"),
                {"id": run_id},
            ).fetchone()
            # completed (not all failed)
            assert row[0] == "completed"
            assert row[1] == 1

    @patch("api.services.pipeline_engine._process_entity")
    def test_parallel_concurrent_timing(self, mock_process, app, db, seed_data):
        """With parallel execution, N entities should complete faster than serial."""
        from api.services.pipeline_engine import run_stage

        tenant = seed_data["tenant"]
        run_id = seed_data["run_id"]
        companies = seed_data["companies"]

        def slow_process(*args, **kwargs):
            time.sleep(0.1)  # 100ms per entity
            return {"enrichment_cost_usd": 0}

        mock_process.side_effect = slow_process

        entity_ids = [str(c.id) for c in companies]

        app.config["ENRICHMENT_MAX_WORKERS"] = 5
        app.config["ENRICHMENT_SKIP_RECENT_HOURS"] = 24

        start = time.time()
        run_stage(app, run_id, "l1", entity_ids, tenant_id=tenant.id)
        elapsed = time.time() - start

        # 5 entities at 100ms each: serial = 500ms, parallel with 5 workers ~ 100-200ms
        # Use generous upper bound (400ms) to avoid flaky tests
        assert elapsed < 0.4, f"Parallel execution took {elapsed:.2f}s, expected < 0.4s"
        assert mock_process.call_count == 5


class TestConfigurableParallelism:
    """Tests for ENRICHMENT_MAX_WORKERS and ENRICHMENT_SKIP_RECENT_HOURS config."""

    def test_config_defaults(self, app):
        """Config should have sensible defaults."""
        assert app.config.get("ENRICHMENT_MAX_WORKERS", 5) >= 1
        assert app.config.get("ENRICHMENT_SKIP_RECENT_HOURS", 24) >= 1

    @patch("api.services.pipeline_engine._process_entity")
    def test_skip_hours_zero_processes_all(self, mock_process, app, db, seed_data):
        """Setting skip hours to 0 should process all entities even if recently enriched."""
        from api.services.pipeline_engine import run_stage

        tenant = seed_data["tenant"]
        tag = seed_data["tag"]
        run_id = seed_data["run_id"]
        company = seed_data["companies"][0]

        # Add a recent completion
        db.session.execute(
            db.text("""
                INSERT INTO entity_stage_completions
                    (id, tenant_id, tag_id, entity_type, entity_id, stage, status, completed_at)
                VALUES (:id, :tid, :tag_id, 'company', :eid, 'l1', 'completed', :now)
            """),
            {
                "id": str(uuid.uuid4()),
                "tid": str(tenant.id),
                "tag_id": str(tag.id),
                "eid": str(company.id),
                "now": datetime.now(timezone.utc).isoformat(),
            },
        )
        db.session.commit()

        mock_process.return_value = {"enrichment_cost_usd": 0}

        app.config["ENRICHMENT_MAX_WORKERS"] = 1
        app.config["ENRICHMENT_SKIP_RECENT_HOURS"] = 0

        run_stage(app, run_id, "l1", [str(company.id)], tenant_id=tenant.id)

        # With 0 hours, nothing is "recently" enriched
        assert mock_process.call_count == 1
