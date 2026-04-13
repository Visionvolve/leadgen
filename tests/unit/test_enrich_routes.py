"""Tests for the enrich estimate + start API endpoints."""

import uuid
from unittest.mock import patch

import pytest

from tests.conftest import auth_header


def _uuid():
    return str(uuid.uuid4())


@pytest.fixture
def seed_enrich_data(db, seed_tenant, seed_super_admin):
    """Create tag, owner, companies, and contacts for enrich tests."""
    from api.models import Tag, Company, Contact, Owner

    owner = Owner(tenant_id=seed_tenant.id, name="Michal", is_active=True)
    db.session.add(owner)
    db.session.flush()

    tag = Tag(tenant_id=seed_tenant.id, name="enrich-batch", is_active=True)
    db.session.add(tag)
    db.session.flush()

    # 5 companies eligible for L1 (status=new)
    companies_new = []
    for i in range(5):
        c = Company(
            tenant_id=seed_tenant.id,
            name=f"New Co {i}",
            domain=f"newco{i}.com",
            tag_id=tag.id,
            owner_id=owner.id,
            status="new",
        )
        db.session.add(c)
        companies_new.append(c)

    # 2 companies eligible for L2 (status=triage_passed)
    companies_l2 = []
    for i in range(2):
        c = Company(
            tenant_id=seed_tenant.id,
            name=f"Passed Co {i}",
            domain=f"passed{i}.com",
            tag_id=tag.id,
            owner_id=owner.id,
            status="triage_passed",
        )
        db.session.add(c)
        companies_l2.append(c)

    # 1 company eligible for person stage (status=enriched_l2)
    c_enriched = Company(
        tenant_id=seed_tenant.id,
        name="Enriched Co",
        domain="enriched.com",
        tag_id=tag.id,
        owner_id=owner.id,
        status="enriched_l2",
    )
    db.session.add(c_enriched)
    db.session.flush()

    # 3 contacts eligible for person stage (unprocessed, enriched_l2 company)
    contacts_person = []
    for i in range(3):
        ct = Contact(
            tenant_id=seed_tenant.id,
            first_name=f"Person Contact {i}",
            company_id=c_enriched.id,
            tag_id=tag.id,
            owner_id=owner.id,
            processed_enrich=False,
        )
        db.session.add(ct)
        contacts_person.append(ct)

    # 1 additional contact (processed, scored)
    ct_gen = Contact(
        tenant_id=seed_tenant.id,
        first_name="Gen",
        last_name="Contact",
        company_id=c_enriched.id,
        tag_id=tag.id,
        owner_id=owner.id,
        processed_enrich=True,
        message_status="not_started",
        contact_score=85,
    )
    db.session.add(ct_gen)

    db.session.commit()
    return {
        "tenant": seed_tenant,
        "tag": tag,
        "owner": owner,
        "companies_new": companies_new,
        "companies_l2": companies_l2,
        "c_enriched": c_enriched,
        "contacts_person": contacts_person,
    }


class TestEnrichEstimate:
    def test_estimate_all_stages(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        resp = client.post(
            "/api/enrich/estimate",
            json={
                "tag_name": "enrich-batch",
                "stages": ["l1", "l2", "person"],
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "stages" in data
        assert "total_estimated_cost" in data

        # L1: 5 eligible at $0.02 = $0.10
        assert data["stages"]["l1"]["eligible_count"] == 5
        assert data["stages"]["l1"]["cost_per_item"] == 0.02
        assert data["stages"]["l1"]["estimated_cost"] == 0.10
        assert "fields" in data["stages"]["l1"]
        assert "Industry" in data["stages"]["l1"]["fields"]

        # L2: 2 eligible at $0.08 = $0.16
        assert data["stages"]["l2"]["eligible_count"] == 2
        assert data["stages"]["l2"]["cost_per_item"] == 0.08
        assert data["stages"]["l2"]["estimated_cost"] == 0.16
        assert "fields" in data["stages"]["l2"]

        # Person: 3 eligible at $0.04 = $0.12
        assert data["stages"]["person"]["eligible_count"] == 3
        assert data["stages"]["person"]["cost_per_item"] == 0.04
        assert data["stages"]["person"]["estimated_cost"] == 0.12

        # Total: 0.10 + 0.16 + 0.12 = 0.38
        assert data["total_estimated_cost"] == pytest.approx(0.38, abs=0.01)

    def test_estimate_single_stage(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        resp = client.post(
            "/api/enrich/estimate",
            json={
                "tag_name": "enrich-batch",
                "stages": ["l1"],
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["stages"]) == 1
        assert data["stages"]["l1"]["eligible_count"] == 5

    def test_estimate_with_owner_filter(self, client, db, seed_enrich_data):
        """Owner filter should narrow eligible counts."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        resp = client.post(
            "/api/enrich/estimate",
            json={
                "tag_name": "enrich-batch",
                "owner_name": "Michal",
                "stages": ["l1"],
            },
            headers=headers,
        )
        assert resp.status_code == 200
        # All 5 belong to Michal
        assert resp.get_json()["stages"]["l1"]["eligible_count"] == 5

    def test_estimate_missing_batch(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        resp = client.post(
            "/api/enrich/estimate",
            json={"stages": ["l1"]},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "tag_name" in resp.get_json()["error"]

    def test_estimate_missing_stages(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        resp = client.post(
            "/api/enrich/estimate",
            json={"tag_name": "enrich-batch"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "stages" in resp.get_json()["error"]

    def test_estimate_invalid_stage(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        resp = client.post(
            "/api/enrich/estimate",
            json={"tag_name": "enrich-batch", "stages": ["bogus"]},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Invalid stages" in resp.get_json()["error"]

    def test_estimate_nonexistent_batch(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        resp = client.post(
            "/api/enrich/estimate",
            json={"tag_name": "no-such-batch", "stages": ["l1"]},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_estimate_unauthenticated(self, client):
        resp = client.post(
            "/api/enrich/estimate",
            json={"tag_name": "test", "stages": ["l1"]},
        )
        assert resp.status_code == 401

    def test_estimate_uses_historical_cost(self, client, db, seed_enrich_data):
        """When historical stage_runs exist, use average cost instead of static default."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        # Insert 5 completed stage_runs with known cost (threshold for historical avg)
        for _ in range(5):
            db.session.execute(
                db.text("""
                    INSERT INTO stage_runs (id, tenant_id, tag_id, stage, status, total, done, cost_usd)
                    VALUES (:id, :t, :b, 'l1', 'completed', 10, 10, 0.50)
                """),
                {
                    "id": _uuid(),
                    "t": str(seed_enrich_data["tenant"].id),
                    "b": str(seed_enrich_data["tag"].id),
                },
            )
        db.session.commit()

        resp = client.post(
            "/api/enrich/estimate",
            json={"tag_name": "enrich-batch", "stages": ["l1"]},
            headers=headers,
        )
        assert resp.status_code == 200
        # Historical average: $0.50 / 10 = $0.05 per item
        assert resp.get_json()["stages"]["l1"]["cost_per_item"] == 0.05


class TestEnrichStart:
    def test_start_success(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        with patch("api.routes.enrich_routes.start_pipeline_threads") as mock_threads:
            resp = client.post(
                "/api/enrich/start",
                json={
                    "tag_name": "enrich-batch",
                    "owner_name": "Michal",
                    "stages": ["l1", "l2"],
                },
                headers=headers,
            )

        assert resp.status_code == 201
        data = resp.get_json()
        assert "pipeline_run_id" in data
        assert "stage_run_ids" in data
        assert set(data["stage_run_ids"].keys()) == {"l1", "l2"}
        mock_threads.assert_called_once()

    def test_start_all_stages(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        with patch("api.routes.enrich_routes.start_pipeline_threads") as mock_threads:
            resp = client.post(
                "/api/enrich/start",
                json={
                    "tag_name": "enrich-batch",
                    "stages": ["l1", "l2", "person", "registry"],
                },
                headers=headers,
            )

        assert resp.status_code == 201
        data = resp.get_json()
        assert set(data["stage_run_ids"].keys()) == {"l1", "l2", "person", "registry"}

    def test_start_with_sample_size(self, client, db, seed_enrich_data):
        """Sample size should be stored in config."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        with patch("api.routes.enrich_routes.start_pipeline_threads"):
            resp = client.post(
                "/api/enrich/start",
                json={
                    "tag_name": "enrich-batch",
                    "stages": ["l1"],
                    "sample_size": 10,
                },
                headers=headers,
            )

        assert resp.status_code == 201
        pipeline_run_id = resp.get_json()["pipeline_run_id"]

        # Verify sample_size stored in config
        import json
        row = db.session.execute(
            db.text("SELECT config FROM pipeline_runs WHERE id = :id"),
            {"id": pipeline_run_id},
        ).fetchone()
        config = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert config["sample_size"] == 10

    def test_start_duplicate_blocked(self, client, db, seed_enrich_data):
        """Cannot start when a pipeline is already running for this batch."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        db.session.execute(
            db.text("""
                INSERT INTO pipeline_runs (id, tenant_id, tag_id, status)
                VALUES (:id, :t, :b, 'running')
            """),
            {
                "id": _uuid(),
                "t": str(seed_enrich_data["tenant"].id),
                "b": str(seed_enrich_data["tag"].id),
            },
        )
        db.session.commit()

        resp = client.post(
            "/api/enrich/start",
            json={"tag_name": "enrich-batch", "stages": ["l1"]},
            headers=headers,
        )
        assert resp.status_code == 409
        assert "already running" in resp.get_json()["error"]

    def test_start_missing_batch(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        resp = client.post(
            "/api/enrich/start",
            json={"stages": ["l1"]},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_start_missing_stages(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        resp = client.post(
            "/api/enrich/start",
            json={"tag_name": "enrich-batch"},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_start_invalid_stage(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        resp = client.post(
            "/api/enrich/start",
            json={"tag_name": "enrich-batch", "stages": ["review"]},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Invalid stages" in resp.get_json()["error"]

    def test_start_nonexistent_batch(self, client, seed_enrich_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        resp = client.post(
            "/api/enrich/start",
            json={"tag_name": "no-such-batch", "stages": ["l1"]},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_start_unauthenticated(self, client):
        resp = client.post(
            "/api/enrich/start",
            json={"tag_name": "test", "stages": ["l1"]},
        )
        assert resp.status_code == 401

    def test_start_with_entity_ids(self, client, db, seed_enrich_data):
        """entity_ids should be validated, stored in config, and passed to threads."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        company_ids = [str(c.id) for c in seed_enrich_data["companies_new"][:2]]

        with patch("api.routes.enrich_routes.start_pipeline_threads") as mock_threads:
            resp = client.post(
                "/api/enrich/start",
                json={
                    "stages": ["l1"],
                    "entity_ids": company_ids,
                },
                headers=headers,
            )

        assert resp.status_code == 201
        data = resp.get_json()
        assert "pipeline_run_id" in data

        # Verify entity_ids stored in config
        import json

        row = db.session.execute(
            db.text("SELECT config FROM pipeline_runs WHERE id = :id"),
            {"id": data["pipeline_run_id"]},
        ).fetchone()
        config = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert sorted(config["entity_ids"]) == sorted(company_ids)

        # Verify entity_ids passed to start_pipeline_threads
        mock_threads.assert_called_once()
        call_kwargs = mock_threads.call_args
        assert sorted(call_kwargs.kwargs["entity_ids"]) == sorted(company_ids)

    def test_start_entity_ids_tenant_validation(self, client, db, seed_enrich_data):
        """entity_ids from another tenant should be silently excluded."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        real_id = str(seed_enrich_data["companies_new"][0].id)
        fake_id = _uuid()  # does not exist in any tenant

        with patch("api.routes.enrich_routes.start_pipeline_threads") as mock_threads:
            resp = client.post(
                "/api/enrich/start",
                json={
                    "stages": ["l1"],
                    "entity_ids": [real_id, fake_id],
                },
                headers=headers,
            )

        assert resp.status_code == 201
        # Only the real ID should be in the config
        import json

        row = db.session.execute(
            db.text("SELECT config FROM pipeline_runs WHERE id = :id"),
            {"id": resp.get_json()["pipeline_run_id"]},
        ).fetchone()
        config = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert config["entity_ids"] == [real_id]
        assert mock_threads.call_args.kwargs["entity_ids"] == [real_id]

    def test_start_entity_ids_with_re_enrich(self, client, db, seed_enrich_data):
        """re_enrich config should be parsed and forwarded."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        company_ids = [str(c.id) for c in seed_enrich_data["companies_new"][:1]]

        with patch("api.routes.enrich_routes.start_pipeline_threads") as mock_threads:
            resp = client.post(
                "/api/enrich/start",
                json={
                    "stages": ["l1"],
                    "entity_ids": company_ids,
                    "re_enrich": {"l1": {"enabled": True, "horizon": "30"}},
                },
                headers=headers,
            )

        assert resp.status_code == 201
        call_kwargs = mock_threads.call_args.kwargs
        assert call_kwargs["re_enrich"] == {"l1": {"enabled": True, "horizon": "30"}}

    def test_start_entity_ids_with_boost(self, client, db, seed_enrich_data):
        """boost config should be parsed and forwarded."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        company_ids = [str(c.id) for c in seed_enrich_data["companies_new"][:1]]

        with patch("api.routes.enrich_routes.start_pipeline_threads") as mock_threads:
            resp = client.post(
                "/api/enrich/start",
                json={
                    "stages": ["l1"],
                    "entity_ids": company_ids,
                    "boost": {"l1": True},
                },
                headers=headers,
            )

        assert resp.status_code == 201
        import json

        row = db.session.execute(
            db.text("SELECT config FROM pipeline_runs WHERE id = :id"),
            {"id": resp.get_json()["pipeline_run_id"]},
        ).fetchone()
        config = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert config["boost"] == {"l1": True}
        assert mock_threads.call_args.kwargs["boost"] == {"l1": True}

    def test_start_empty_entity_ids_ignored(self, client, db, seed_enrich_data):
        """Empty entity_ids array should fall back to tag/owner mode."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        with patch("api.routes.enrich_routes.start_pipeline_threads") as mock_threads:
            resp = client.post(
                "/api/enrich/start",
                json={
                    "tag_name": "enrich-batch",
                    "stages": ["l1"],
                    "entity_ids": [],
                },
                headers=headers,
            )

        assert resp.status_code == 201
        # entity_ids should not be in config or call kwargs
        import json

        row = db.session.execute(
            db.text("SELECT config FROM pipeline_runs WHERE id = :id"),
            {"id": resp.get_json()["pipeline_run_id"]},
        ).fetchone()
        config = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert "entity_ids" not in config
        assert mock_threads.call_args.kwargs["entity_ids"] is None

    def test_start_invalid_uuid_entity_ids_dropped(self, client, seed_enrich_data):
        """Non-UUID entity_ids should be silently dropped."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        real_id = str(seed_enrich_data["companies_new"][0].id)

        with patch("api.routes.enrich_routes.start_pipeline_threads") as mock_threads:
            resp = client.post(
                "/api/enrich/start",
                json={
                    "stages": ["l1"],
                    "entity_ids": [real_id, "not-a-uuid", "also-bad"],
                },
                headers=headers,
            )

        assert resp.status_code == 201
        assert mock_threads.call_args.kwargs["entity_ids"] == [real_id]

    def test_start_with_re_enrich_horizon_days(self, client, db, seed_enrich_data):
        """re_enrich_horizon_days should be stored in config."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_enrich_data["tenant"].slug

        company_ids = [str(c.id) for c in seed_enrich_data["companies_new"][:1]]

        with patch("api.routes.enrich_routes.start_pipeline_threads") as mock_threads:
            resp = client.post(
                "/api/enrich/start",
                json={
                    "stages": ["l1"],
                    "entity_ids": company_ids,
                    "re_enrich_horizon_days": 30,
                },
                headers=headers,
            )

        assert resp.status_code == 201
        import json

        row = db.session.execute(
            db.text("SELECT config FROM pipeline_runs WHERE id = :id"),
            {"id": resp.get_json()["pipeline_run_id"]},
        ).fetchone()
        config = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert config["re_enrich_horizon_days"] == 30
        assert mock_threads.call_args.kwargs["re_enrich_horizon_days"] == 30


@pytest.fixture
def seed_review_data(db, seed_tenant, seed_super_admin):
    """Create tag with companies in various review states."""
    from api.models import Tag, Company, Owner
    import json

    owner = Owner(tenant_id=seed_tenant.id, name="Tester", is_active=True)
    db.session.add(owner)
    db.session.flush()

    tag = Tag(tenant_id=seed_tenant.id, name="review-batch", is_active=True)
    db.session.add(tag)
    db.session.flush()

    # Company needing review (QC flags)
    c_review = Company(
        tenant_id=seed_tenant.id,
        name="Flagged Co",
        domain="flagged.com",
        tag_id=tag.id,
        owner_id=owner.id,
        status="needs_review",
        error_message=json.dumps(["name_mismatch", "low_confidence"]),
        enrichment_cost_usd=0.01,
    )
    db.session.add(c_review)

    # Company with enrichment failure
    c_failed = Company(
        tenant_id=seed_tenant.id,
        name="Failed Co",
        domain="failed.com",
        tag_id=tag.id,
        owner_id=owner.id,
        status="enrichment_failed",
        error_message="API timeout",
        enrichment_cost_usd=0,
    )
    db.session.add(c_failed)

    # Normal company (should NOT appear in review)
    c_ok = Company(
        tenant_id=seed_tenant.id,
        name="OK Co",
        domain="ok.com",
        tag_id=tag.id,
        owner_id=owner.id,
        status="triage_passed",
    )
    db.session.add(c_ok)

    db.session.commit()
    return {
        "tenant": seed_tenant,
        "tag": tag,
        "c_review": c_review,
        "c_failed": c_failed,
        "c_ok": c_ok,
    }


class TestEnrichReview:
    def test_review_returns_flagged_companies(self, client, seed_review_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug

        resp = client.get(
            "/api/enrich/review?tag_name=review-batch&stage=l1",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 2

        names = {item["name"] for item in data["items"]}
        assert "Flagged Co" in names
        assert "Failed Co" in names
        assert "OK Co" not in names

    def test_review_parses_json_flags(self, client, seed_review_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug

        resp = client.get(
            "/api/enrich/review?tag_name=review-batch",
            headers=headers,
        )
        data = resp.get_json()
        flagged = next(i for i in data["items"] if i["name"] == "Flagged Co")
        assert flagged["flags"] == ["name_mismatch", "low_confidence"]

    def test_review_non_json_error_as_single_flag(self, client, seed_review_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug

        resp = client.get(
            "/api/enrich/review?tag_name=review-batch",
            headers=headers,
        )
        data = resp.get_json()
        failed = next(i for i in data["items"] if i["name"] == "Failed Co")
        assert failed["flags"] == ["API timeout"]

    def test_review_missing_batch(self, client, seed_review_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug

        resp = client.get("/api/enrich/review", headers=headers)
        assert resp.status_code == 400

    def test_review_nonexistent_batch(self, client, seed_review_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug

        resp = client.get(
            "/api/enrich/review?tag_name=no-such-batch",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_review_unauthenticated(self, client):
        resp = client.get("/api/enrich/review?tag_name=test")
        assert resp.status_code == 401


class TestEnrichResolve:
    def test_approve_sets_triage_passed(self, client, db, seed_review_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug
        company_id = str(seed_review_data["c_review"].id)

        resp = client.post(
            "/api/enrich/resolve",
            json={"company_id": company_id, "action": "approve"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["new_status"] == "triage_passed"

        # Verify in DB
        row = db.session.execute(
            db.text("SELECT status, error_message FROM companies WHERE id = :id"),
            {"id": company_id},
        ).fetchone()
        assert row[0] == "triage_passed"
        assert row[1] is None

    def test_skip_sets_triage_disqualified(self, client, db, seed_review_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug
        company_id = str(seed_review_data["c_review"].id)

        resp = client.post(
            "/api/enrich/resolve",
            json={"company_id": company_id, "action": "skip"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["new_status"] == "triage_disqualified"

    def test_retry_resets_and_re_enriches(self, client, db, seed_review_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug
        company_id = str(seed_review_data["c_failed"].id)

        with patch("api.routes.enrich_routes._process_entity") as mock_proc:
            mock_proc.return_value = {"enrichment_cost_usd": 0.02, "qc_flags": []}
            resp = client.post(
                "/api/enrich/resolve",
                json={"company_id": company_id, "action": "retry"},
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        mock_proc.assert_called_once()

    def test_resolve_invalid_action(self, client, seed_review_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug

        resp = client.post(
            "/api/enrich/resolve",
            json={"company_id": str(seed_review_data["c_review"].id), "action": "delete"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "action" in resp.get_json()["error"]

    def test_resolve_missing_company_id(self, client, seed_review_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug

        resp = client.post(
            "/api/enrich/resolve",
            json={"action": "approve"},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_resolve_nonexistent_company(self, client, seed_review_data):
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug

        resp = client.post(
            "/api/enrich/resolve",
            json={"company_id": _uuid(), "action": "approve"},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_resolve_non_reviewable_status(self, client, seed_review_data):
        """Cannot resolve a company that's not in needs_review or enrichment_failed."""
        headers = auth_header(client)
        headers["X-Namespace"] = seed_review_data["tenant"].slug

        resp = client.post(
            "/api/enrich/resolve",
            json={"company_id": str(seed_review_data["c_ok"].id), "action": "approve"},
            headers=headers,
        )
        assert resp.status_code == 409
        assert "not reviewable" in resp.get_json()["error"]

    def test_resolve_unauthenticated(self, client):
        resp = client.post(
            "/api/enrich/resolve",
            json={"company_id": _uuid(), "action": "approve"},
        )
        assert resp.status_code == 401
