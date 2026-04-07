"""Unit tests for ARES-related routes (company detail, enrich-registry, confirm-registry, estimate)."""

from unittest.mock import patch

from tests.conftest import auth_header


class TestCompanyDetailRegistryData:
    """Company detail endpoint should include registry_data section."""

    def test_no_registry_data(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = seed_companies_contacts["companies"][0].id
        resp = client.get(f"/api/companies/{company_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["registry_data"] is None

    def test_with_registry_data(self, client, db, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = str(seed_companies_contacts["companies"][0].id)

        db.session.execute(
            db.text("""
                INSERT INTO company_registry_data (
                    company_id, ico, dic, official_name, legal_form, legal_form_name,
                    date_established, registered_address, address_city, address_postal_code,
                    registration_status, insolvency_flag, match_confidence, match_method
                ) VALUES (
                    :cid, '12345678', 'CZ12345678', 'Acme Corp s.r.o.', '112', 's.r.o.',
                    '2010-01-01', 'Hlavni 1, Praha', 'Praha', '11000',
                    'active', 0, 1.0, 'ico_direct'
                )
            """),
            {"cid": company_id},
        )
        db.session.commit()

        resp = client.get(f"/api/companies/{company_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        reg = data["registry_data"]
        assert reg is not None
        assert reg["ico"] == "12345678"
        assert reg["dic"] == "CZ12345678"
        assert reg["official_name"] == "Acme Corp s.r.o."
        assert reg["legal_form"] == "112"
        assert reg["registration_status"] == "active"
        assert reg["match_confidence"] == 1.0
        assert reg["match_method"] == "ico_direct"

    def test_ico_field_via_registry_data(self, client, db, seed_companies_contacts):
        """ico is served via registry_data, not as a top-level company column."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = str(seed_companies_contacts["companies"][0].id)

        db.session.execute(
            db.text("""
                INSERT INTO company_registry_data (
                    company_id, ico, match_confidence, match_method,
                    registration_status, insolvency_flag
                ) VALUES (
                    :cid, '99887766', 1.0, 'ico_direct', 'active', 0
                )
            """),
            {"cid": company_id},
        )
        db.session.commit()

        resp = client.get(f"/api/companies/{company_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["registry_data"]["ico"] == "99887766"


class TestEnrichRegistry:
    """POST /api/companies/<id>/enrich-registry endpoint tests."""

    @patch("api.services.registries.orchestrator.RegistryOrchestrator.enrich_company")
    def test_success_with_ico(self, mock_enrich, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = str(seed_companies_contacts["companies"][0].id)

        mock_enrich.return_value = {
            "status": "enriched",
            "registration_id": "27074358",
            "official_name": "Test s.r.o.",
            "credibility_score": 85,
            "adapters_run": ["CZ"],
            "enrichment_cost_usd": 0,
        }

        resp = client.post(
            f"/api/companies/{company_id}/enrich-registry",
            json={"ico": "27074358"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "enriched"
        mock_enrich.assert_called_once()

    @patch("api.services.registries.orchestrator.RegistryOrchestrator.enrich_company")
    def test_success_without_ico(self, mock_enrich, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = str(seed_companies_contacts["companies"][0].id)

        mock_enrich.return_value = {
            "status": "enriched",
            "registration_id": "11111111",
            "credibility_score": 70,
            "adapters_run": ["CZ"],
            "enrichment_cost_usd": 0,
        }

        resp = client.post(
            f"/api/companies/{company_id}/enrich-registry",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "enriched"

    @patch("api.services.registries.orchestrator.RegistryOrchestrator.enrich_company")
    def test_ambiguous_result(self, mock_enrich, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = str(seed_companies_contacts["companies"][0].id)

        mock_enrich.return_value = {
            "status": "ambiguous",
            "candidates": [
                {
                    "ico": "11111111",
                    "official_name": "Acme A s.r.o.",
                    "similarity": 0.75,
                },
                {"ico": "22222222", "official_name": "Acme B a.s.", "similarity": 0.70},
            ],
        }

        resp = client.post(
            f"/api/companies/{company_id}/enrich-registry",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ambiguous"
        assert len(data["candidates"]) == 2

    @patch("api.services.registries.orchestrator.RegistryOrchestrator.enrich_company")
    def test_no_applicable_registry(self, mock_enrich, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        # Epsilon SA is French
        company_id = str(seed_companies_contacts["companies"][4].id)

        mock_enrich.return_value = {
            "status": "skipped",
            "reason": "no_applicable_registry",
            "enrichment_cost_usd": 0,
        }

        resp = client.post(
            f"/api/companies/{company_id}/enrich-registry",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "skipped"

    def test_company_not_found(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            "/api/companies/00000000-0000-0000-0000-000000000000/enrich-registry",
            json={},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_unauthenticated(self, client, seed_companies_contacts):
        company_id = str(seed_companies_contacts["companies"][0].id)
        resp = client.post(f"/api/companies/{company_id}/enrich-registry", json={})
        assert resp.status_code == 401


class TestConfirmRegistry:
    """POST /api/companies/<id>/confirm-registry endpoint tests."""

    @patch("api.services.ares.enrich_company")
    def test_confirm_success(self, mock_enrich, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = str(seed_companies_contacts["companies"][0].id)

        mock_enrich.return_value = {
            "status": "enriched",
            "ico": "12345678",
            "method": "ico_direct",
            "confidence": 1.0,
        }

        resp = client.post(
            f"/api/companies/{company_id}/confirm-registry",
            json={"ico": "12345678"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "enriched"
        assert data["confidence"] == 1.0

    def test_missing_ico(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = str(seed_companies_contacts["companies"][0].id)

        resp = client.post(
            f"/api/companies/{company_id}/confirm-registry",
            json={},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "ico is required" in resp.get_json()["error"]

    def test_company_not_found(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            "/api/companies/00000000-0000-0000-0000-000000000000/confirm-registry",
            json={"ico": "12345678"},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_unauthenticated(self, client, seed_companies_contacts):
        company_id = str(seed_companies_contacts["companies"][0].id)
        resp = client.post(
            f"/api/companies/{company_id}/confirm-registry",
            json={"ico": "12345678"},
        )
        assert resp.status_code == 401


class TestRegistryInEnrichEstimate:
    """Registry (legacy alias 'ares') should appear in estimate with $0.00 cost."""

    def test_registry_estimate_via_legacy_alias(
        self, client, db, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tag_name = seed_companies_contacts["tags"][0].name

        resp = client.post(
            "/api/enrich/estimate",
            json={"tag_name": tag_name, "stages": ["ares"]},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # Legacy "ares" is resolved to "registry"
        assert "registry" in data["stages"]
        assert data["stages"]["registry"]["cost_per_item"] == 0.00
        assert data["stages"]["registry"]["estimated_cost"] == 0.00

    def test_registry_in_multi_stage_estimate(
        self, client, db, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tag_name = seed_companies_contacts["tags"][0].name

        resp = client.post(
            "/api/enrich/estimate",
            json={"tag_name": tag_name, "stages": ["l1", "ares"]},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "l1" in data["stages"]
        assert "registry" in data["stages"]
        assert data["stages"]["registry"]["cost_per_item"] == 0.00
