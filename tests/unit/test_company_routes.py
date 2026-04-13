"""Unit tests for company routes."""
from tests.conftest import auth_header


class TestListCompanies:
    def test_list_returns_paginated(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?page_size=3", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "companies" in data
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 3
        assert data["pages"] == 2
        assert len(data["companies"]) == 3

    def test_list_page_2(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?page=2&page_size=3", headers=headers)
        data = resp.get_json()
        assert data["page"] == 2
        assert len(data["companies"]) == 2

    def test_search_by_name(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?search=acme", headers=headers)
        data = resp.get_json()
        assert data["total"] == 1
        assert data["companies"][0]["name"] == "Acme Corp"

    def test_search_by_domain(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?search=delta.de", headers=headers)
        data = resp.get_json()
        assert data["total"] == 1
        assert data["companies"][0]["domain"] == "delta.de"

    def test_filter_by_status(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?status=triage_passed", headers=headers)
        data = resp.get_json()
        assert data["total"] == 2
        for c in data["companies"]:
            assert c["status"] == "Triage: Passed"

    def test_filter_by_tier(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?tier=tier_1_platinum", headers=headers)
        data = resp.get_json()
        assert data["total"] == 2
        for c in data["companies"]:
            assert "Tier 1" in c["tier"]

    def test_filter_by_batch(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?tag_name=batch-2", headers=headers)
        data = resp.get_json()
        assert data["total"] == 2

    def test_filter_by_owner(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?owner_name=Bob", headers=headers)
        data = resp.get_json()
        assert data["total"] == 2
        for c in data["companies"]:
            assert c["owner_name"] == "Bob"

    def test_sort_by_triage_score_desc(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?sort=triage_score&sort_dir=desc", headers=headers)
        data = resp.get_json()
        scores = [c["triage_score"] for c in data["companies"]]
        assert scores == sorted(scores, reverse=True)

    def test_sort_by_name_asc(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?sort=name&sort_dir=asc", headers=headers)
        data = resp.get_json()
        names = [c["name"] for c in data["companies"]]
        assert names == sorted(names)

    def test_invalid_sort_falls_back(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?sort=INVALID_COL", headers=headers)
        assert resp.status_code == 200

    def test_display_values(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?search=beta", headers=headers)
        data = resp.get_json()
        c = data["companies"][0]
        assert c["status"] == "Triage: Passed"
        assert c["tier"] == "Tier 1 - Platinum"
        assert c["industry"] == "IT"

    def test_contact_count(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies?search=acme", headers=headers)
        data = resp.get_json()
        assert data["companies"][0]["contact_count"] == 2

    def test_no_auth_returns_401(self, client, seed_companies_contacts):
        resp = client.get("/api/companies")
        assert resp.status_code == 401

    def test_tenant_isolation(self, client, db, seed_companies_contacts):
        """Companies from another tenant should not be visible."""
        from api.models import Company, Tenant
        other = Tenant(name="Other Corp", slug="other-corp", is_active=True)
        db.session.add(other)
        db.session.flush()
        co = Company(tenant_id=other.id, name="Other Co", status="new")
        db.session.add(co)
        db.session.commit()

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies", headers=headers)
        data = resp.get_json()
        names = [c["name"] for c in data["companies"]]
        assert "Other Co" not in names


class TestGetCompany:
    def test_get_detail(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = seed_companies_contacts["companies"][0].id
        resp = client.get(f"/api/companies/{company_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Acme Corp"
        assert data["summary"] == "Summary for Acme Corp"
        assert data["notes"] == "Notes for Acme Corp"
        assert isinstance(data["contacts"], list)
        assert len(data["contacts"]) == 2
        # John Doe (CEO) has contact enrichment — verify expanded fields
        john = next(c for c in data["contacts"] if c["first_name"] == "John")
        assert john["linkedin_url"] == "https://www.linkedin.com/in/johndoe"
        assert john["seniority_level"] == "c_level"
        assert john["department"] == "executive"
        assert john["person_summary"] == "Experienced CEO with AI background"
        assert john["career_trajectory"] is None  # not set in seed
        # Jane Smith has no contact enrichment — fields should be None
        jane = next(c for c in data["contacts"] if c["first_name"] == "Jane")
        assert jane["person_summary"] is None

    def test_get_with_l2_enrichment(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = seed_companies_contacts["companies"][3].id  # Delta GmbH
        resp = client.get(f"/api/companies/{company_id}", headers=headers)
        data = resp.get_json()
        assert data["enrichment_l2"] is not None
        assert data["enrichment_l2"]["modules"]["profile"]["company_intel"] == "Leading manufacturer in DACH region"

    def test_get_with_tags(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = seed_companies_contacts["companies"][1].id  # Beta Inc
        resp = client.get(f"/api/companies/{company_id}", headers=headers)
        data = resp.get_json()
        assert len(data["tags"]) == 2
        categories = [t["category"] for t in data["tags"]]
        assert "ai_use_case" in categories

    def test_get_not_found(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies/00000000-0000-0000-0000-000000000000", headers=headers)
        assert resp.status_code == 404


class TestPatchCompany:
    def test_update_notes(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = seed_companies_contacts["companies"][0].id
        resp = client.patch(
            f"/api/companies/{company_id}",
            json={"notes": "Updated notes"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_update_status(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = seed_companies_contacts["companies"][0].id
        resp = client.patch(
            f"/api/companies/{company_id}",
            json={"status": "triage_passed"},
            headers=headers,
        )
        assert resp.status_code == 200

    def test_disallowed_field_ignored(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = seed_companies_contacts["companies"][0].id
        resp = client.patch(
            f"/api/companies/{company_id}",
            json={"tenant_id": "hacked"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "No valid fields" in resp.get_json()["error"]

    def test_update_not_found(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.patch(
            "/api/companies/00000000-0000-0000-0000-000000000000",
            json={"notes": "test"},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_no_auth_returns_401(self, client, seed_companies_contacts):
        company_id = seed_companies_contacts["companies"][0].id
        resp = client.patch(f"/api/companies/{company_id}", json={"notes": "x"})
        assert resp.status_code == 401
