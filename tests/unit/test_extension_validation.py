"""Tests for LinkedIn validation extension API routes."""

import uuid

from tests.conftest import auth_header


class TestValidateContact:
    """GET /api/extension/validate-contact"""

    def test_matches_by_linkedin_url(self, client, seed_companies_contacts):
        """Given a LinkedIn URL that exists in CRM, returns match with contact data."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get(
            "/api/extension/validate-contact?linkedin_url=https://www.linkedin.com/in/johndoe",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is True
        assert data["contact"]["full_name"] == "John Doe"
        assert data["contact"]["job_title"] == "CEO"
        assert "id" in data["contact"]

    def test_matches_by_linkedin_url_trailing_slash(
        self, client, seed_companies_contacts
    ):
        """Given a LinkedIn URL with trailing slash, still matches."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get(
            "/api/extension/validate-contact?linkedin_url=https://www.linkedin.com/in/johndoe/",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is True
        assert data["contact"]["full_name"] == "John Doe"

    def test_matches_by_name_and_company(self, client, seed_companies_contacts):
        """Given name + company that exists in CRM, returns fuzzy match."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get(
            "/api/extension/validate-contact?name=John+Doe&company=Acme",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is True
        assert data["contact"]["full_name"] == "John Doe"
        assert data["contact"]["company_name"] == "Acme Corp"

    def test_no_match_returns_false(self, client, seed_companies_contacts):
        """Given a URL not in CRM, returns match: false."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get(
            "/api/extension/validate-contact?linkedin_url=https://www.linkedin.com/in/nonexistent",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is False
        assert "contact" not in data

    def test_detects_title_mismatch(self, client, seed_companies_contacts):
        """Given LinkedIn title different from CRM, returns mismatch."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        # John Doe is CEO in CRM, but we pass headline=CTO
        resp = client.get(
            "/api/extension/validate-contact"
            "?linkedin_url=https://www.linkedin.com/in/johndoe"
            "&headline=CTO",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is True
        assert len(data["mismatches"]) >= 1
        title_mismatch = next(
            (m for m in data["mismatches"] if m["field"] == "Title"), None
        )
        assert title_mismatch is not None
        assert title_mismatch["linkedin_value"] == "CTO"
        assert title_mismatch["crm_value"] == "CEO"

    def test_returns_enrichment_quality(self, client, seed_companies_contacts):
        """Given a contact with enrichment data, returns enrichment_quality."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        # John Doe has ContactEnrichment seeded
        resp = client.get(
            "/api/extension/validate-contact?linkedin_url=https://www.linkedin.com/in/johndoe",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is True
        assert "enrichment_quality" in data
        assert data["enrichment_quality"]["has_enrichment"] is True
        assert data["enrichment_quality"]["score"] > 0

    def test_requires_param(self, client, seed_companies_contacts):
        """Given no linkedin_url or name, returns 400."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/extension/validate-contact", headers=headers)
        assert resp.status_code == 400

    def test_requires_auth(self, client, db):
        """Given no auth header, returns 401."""
        resp = client.get(
            "/api/extension/validate-contact?linkedin_url=https://www.linkedin.com/in/test"
        )
        assert resp.status_code == 401

    def test_cross_tenant_isolation(self, client, db, seed_companies_contacts):
        """Given auth for a different tenant, contacts from another tenant are not visible."""
        from api.models import Tenant, User, UserTenantRole

        # Create a second tenant + user
        other_tenant = Tenant(name="Other Corp", slug="other-corp", is_active=True)
        db.session.add(other_tenant)
        db.session.flush()

        other_user = User(
            email="other@test.com",
            password_hash=None,
            display_name="Other User",
            is_super_admin=False,
            is_active=True,
            iam_user_id=str(uuid.uuid4()),
        )
        db.session.add(other_user)
        db.session.flush()

        role = UserTenantRole(
            user_id=other_user.id,
            tenant_id=other_tenant.id,
            role="admin",
            granted_by=other_user.id,
        )
        db.session.add(role)
        db.session.commit()

        # Auth as other tenant user, search for contact that exists in test-corp
        headers = auth_header(client, email="other@test.com")
        headers["X-Namespace"] = "other-corp"
        resp = client.get(
            "/api/extension/validate-contact"
            "?linkedin_url=https://www.linkedin.com/in/johndoe",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is False


class TestValidateCompany:
    """GET /api/extension/validate-company"""

    def test_matches_by_name_exact(self, client, seed_companies_contacts):
        """Given exact company name, returns match."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get(
            "/api/extension/validate-company?name=Acme+Corp",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is True
        assert data["company"]["name"] == "Acme Corp"
        assert "id" in data["company"]

    def test_matches_by_name_fuzzy(self, client, seed_companies_contacts):
        """Given partial company name, returns fuzzy match."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get(
            "/api/extension/validate-company?name=Acme",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is True
        assert "Acme" in data["company"]["name"]

    def test_matches_by_linkedin_url_slug(self, client, seed_companies_contacts):
        """Given LinkedIn company URL, extracts slug and matches."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        # Beta Inc -> slug "beta-inc" -> fuzzy matches "Beta"
        resp = client.get(
            "/api/extension/validate-company?linkedin_url=https://www.linkedin.com/company/beta-inc",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is True
        assert "Beta" in data["company"]["name"]

    def test_no_match_returns_false(self, client, seed_companies_contacts):
        """Given unknown company, returns match: false."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get(
            "/api/extension/validate-company?name=NonexistentCompanyXYZ",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is False

    def test_detects_industry_mismatch(self, client, seed_companies_contacts):
        """Given LinkedIn industry different from CRM, returns mismatch."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        # Acme Corp has industry "software_saas" in CRM
        resp = client.get(
            "/api/extension/validate-company?name=Acme+Corp&industry=Financial+Services",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["match"] is True
        industry_mismatch = next(
            (m for m in data.get("mismatches", []) if m["field"] == "Industry"), None
        )
        assert industry_mismatch is not None
        assert industry_mismatch["linkedin_value"] == "Financial Services"

    def test_requires_param(self, client, seed_companies_contacts):
        """Given no linkedin_url or name, returns 400."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/extension/validate-company", headers=headers)
        assert resp.status_code == 400

    def test_requires_auth(self, client, db):
        """Given no auth header, returns 401."""
        resp = client.get("/api/extension/validate-company?name=Test")
        assert resp.status_code == 401
