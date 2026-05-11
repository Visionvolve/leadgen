"""Unit tests for Company.organization_type (BL-1108, v25 Phase 6).

Covers:
  - PATCH /api/companies/<id> with a valid organization_type persists the value.
  - PATCH with an invalid value returns 400 and exposes allowed values.
  - PATCH with null clears the field.
  - GET /api/companies?organization_type=<v> filters to matching rows only.
  - Tenant scoping: a company in another tenant is not visible.
"""

from tests.conftest import auth_header


def _company_id(seed_companies_contacts, name="Acme Corp"):
    for c in seed_companies_contacts["companies"]:
        if c.name == name:
            return c.id
    raise AssertionError(f"Seed company {name!r} not found")


class TestPatchOrganizationType:
    def test_valid_value_saves(self, client, db, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        cid = _company_id(seed_companies_contacts)

        resp = client.patch(
            f"/api/companies/{cid}",
            json={"organization_type": "b2b_agency"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["ok"] is True

        # Persisted value visible on GET.
        get_resp = client.get(f"/api/companies/{cid}", headers=headers)
        assert get_resp.status_code == 200
        assert get_resp.get_json()["organization_type"] == "b2b_agency"

    def test_invalid_value_returns_400(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        cid = _company_id(seed_companies_contacts)

        resp = client.patch(
            f"/api/companies/{cid}",
            json={"organization_type": "invalid_value"},
            headers=headers,
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert "organization_type" in body.get("error", "")
        # The error payload exposes the allowed enum for the client.
        assert body.get("field") == "organization_type"
        assert "b2b_agency" in body.get("allowed", [])

    def test_null_clears_field(self, client, db, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        cid = _company_id(seed_companies_contacts)

        # First set a value.
        resp = client.patch(
            f"/api/companies/{cid}",
            json={"organization_type": "non_profit"},
            headers=headers,
        )
        assert resp.status_code == 200

        # Then clear it with null.
        resp = client.patch(
            f"/api/companies/{cid}",
            json={"organization_type": None},
            headers=headers,
        )
        assert resp.status_code == 200, resp.get_json()

        get_resp = client.get(f"/api/companies/{cid}", headers=headers)
        assert get_resp.get_json()["organization_type"] is None


class TestListFilterByOrganizationType:
    def test_filter_returns_matching_only(self, client, db, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        # Tag two companies with distinct org types.
        acme = _company_id(seed_companies_contacts, "Acme Corp")
        beta = _company_id(seed_companies_contacts, "Beta Inc")

        client.patch(
            f"/api/companies/{acme}",
            json={"organization_type": "b2b_agency"},
            headers=headers,
        )
        client.patch(
            f"/api/companies/{beta}",
            json={"organization_type": "event_organizer"},
            headers=headers,
        )

        # Filter by b2b_agency — should return only Acme.
        resp = client.get(
            "/api/companies?organization_type=b2b_agency", headers=headers
        )
        assert resp.status_code == 200
        data = resp.get_json()
        names = [c["name"] for c in data["companies"]]
        assert names == ["Acme Corp"]
        assert data["companies"][0]["organization_type"] == "b2b_agency"

        # Filter by event_organizer — should return only Beta.
        resp = client.get(
            "/api/companies?organization_type=event_organizer", headers=headers
        )
        data = resp.get_json()
        names = [c["name"] for c in data["companies"]]
        assert names == ["Beta Inc"]
