"""Unit tests for saved smart lists (BL-1111 / BL-1112 / BL-1113, v25 Phase 10).

Exercises CRUD, run, preview, tenant isolation, unique-name constraint, and
the LCC seed script.
"""

from __future__ import annotations

import pytest

from tests.conftest import auth_header


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #


def _headers(client):
    headers = auth_header(client)
    headers["X-Namespace"] = "test-corp"
    return headers


@pytest.fixture
def seed_org_types(db, seed_tenant, seed_super_admin):
    """Seed three companies with organization_type set, plus a UserTenantRole
    so the super-admin user has editor access through the tenant role path.
    """
    from api.models import Company, UserTenantRole

    # Give super_admin a real role (super_admin bypasses role checks anyway,
    # but resolve_tenant() walks roles when no header is set).
    role = UserTenantRole(
        user_id=seed_super_admin.id,
        tenant_id=seed_tenant.id,
        role="admin",
        granted_by=seed_super_admin.id,
    )
    db.session.add(role)

    cz_agency = Company(
        tenant_id=seed_tenant.id,
        name="Czech Agency 1",
        domain="cz1.cz",
        organization_type="b2b_agency",
        geo_region="cee",
        engagement_status="cold",
        hq_country="CZ",
    )
    dach_agency = Company(
        tenant_id=seed_tenant.id,
        name="DACH Agency",
        domain="dach.de",
        organization_type="b2b_agency",
        geo_region="dach",
        engagement_status="warm",
        hq_country="DE",
    )
    cultural = Company(
        tenant_id=seed_tenant.id,
        name="Cultural Org",
        domain="culture.cz",
        organization_type="b2g_cultural",
        geo_region="cee",
        engagement_status="cold",
        hq_country="CZ",
    )
    db.session.add_all([cz_agency, dach_agency, cultural])
    db.session.commit()
    return {
        "tenant": seed_tenant,
        "cz_agency": cz_agency,
        "dach_agency": dach_agency,
        "cultural": cultural,
    }


# --------------------------------------------------------------------------- #
#  CRUD
# --------------------------------------------------------------------------- #


class TestSmartListCRUD:
    def test_create_and_list(self, client, seed_org_types):
        headers = _headers(client)
        resp = client.post(
            "/api/smart-lists",
            headers=headers,
            json={
                "name": "CZ Agencies",
                "description": "Cold Czech B2B agencies.",
                "target": "company",
                "filters": {
                    "organization_type": ["b2b_agency"],
                    "geo_region": ["cee"],
                    "engagement_status": ["cold"],
                },
            },
        )
        assert resp.status_code == 201, resp.get_json()
        body = resp.get_json()
        assert body["name"] == "CZ Agencies"
        assert body["target"] == "company"
        assert body["filters"]["organization_type"] == ["b2b_agency"]
        assert body["last_run_count"] is None

        # List
        resp = client.get("/api/smart-lists", headers=headers)
        assert resp.status_code == 200
        items = resp.get_json()["smart_lists"]
        assert len(items) == 1
        assert items[0]["name"] == "CZ Agencies"

    def test_get_by_id(self, client, seed_org_types):
        headers = _headers(client)
        created = client.post(
            "/api/smart-lists",
            headers=headers,
            json={
                "name": "DACH Agencies",
                "target": "company",
                "filters": {
                    "organization_type": ["b2b_agency"],
                    "geo_region": ["dach"],
                },
            },
        ).get_json()
        list_id = created["id"]
        resp = client.get(f"/api/smart-lists/{list_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "DACH Agencies"

    def test_update(self, client, seed_org_types):
        headers = _headers(client)
        created = client.post(
            "/api/smart-lists",
            headers=headers,
            json={
                "name": "Original",
                "target": "company",
                "filters": {"organization_type": ["b2b_agency"]},
            },
        ).get_json()
        list_id = created["id"]

        resp = client.patch(
            f"/api/smart-lists/{list_id}",
            headers=headers,
            json={
                "name": "Renamed",
                "description": "updated",
                "filters": {"organization_type": ["b2g_cultural"]},
            },
        )
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["name"] == "Renamed"
        assert body["description"] == "updated"
        assert body["filters"]["organization_type"] == ["b2g_cultural"]

    def test_delete(self, client, seed_org_types):
        headers = _headers(client)
        created = client.post(
            "/api/smart-lists",
            headers=headers,
            json={"name": "Temp", "target": "company", "filters": {}},
        ).get_json()
        list_id = created["id"]
        resp = client.delete(f"/api/smart-lists/{list_id}", headers=headers)
        assert resp.status_code == 200
        # Confirm gone
        resp = client.get(f"/api/smart-lists/{list_id}", headers=headers)
        assert resp.status_code == 404

    def test_unique_name_per_tenant(self, client, seed_org_types):
        headers = _headers(client)
        client.post(
            "/api/smart-lists",
            headers=headers,
            json={"name": "Dup", "target": "company", "filters": {}},
        )
        # Second create with same name → 409
        resp = client.post(
            "/api/smart-lists",
            headers=headers,
            json={"name": "Dup", "target": "company", "filters": {}},
        )
        assert resp.status_code == 409

    def test_invalid_target(self, client, seed_org_types):
        headers = _headers(client)
        resp = client.post(
            "/api/smart-lists",
            headers=headers,
            json={"name": "Bad", "target": "garbage", "filters": {}},
        )
        assert resp.status_code == 400

    def test_missing_name(self, client, seed_org_types):
        headers = _headers(client)
        resp = client.post(
            "/api/smart-lists",
            headers=headers,
            json={"target": "company", "filters": {}},
        )
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
#  Run / preview
# --------------------------------------------------------------------------- #


class TestSmartListRun:
    def test_run_company_target(self, client, seed_org_types):
        """Saved 'CZ B2B agencies, cold' list returns exactly one match."""
        headers = _headers(client)
        created = client.post(
            "/api/smart-lists",
            headers=headers,
            json={
                "name": "CZ cold agencies",
                "target": "company",
                "filters": {
                    "organization_type": ["b2b_agency"],
                    "geo_region": ["cee"],
                    "engagement_status": ["cold"],
                },
            },
        ).get_json()
        list_id = created["id"]
        resp = client.post(f"/api/smart-lists/{list_id}/run", headers=headers)
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["total"] == 1
        assert body["companies"][0]["name"] == "Czech Agency 1"
        # last_run_count updated
        get_resp = client.get(f"/api/smart-lists/{list_id}", headers=headers)
        assert get_resp.get_json()["last_run_count"] == 1
        assert get_resp.get_json()["last_run_at"] is not None

    def test_run_dach_filter(self, client, seed_org_types):
        headers = _headers(client)
        created = client.post(
            "/api/smart-lists",
            headers=headers,
            json={
                "name": "DACH agencies",
                "target": "company",
                "filters": {
                    "organization_type": ["b2b_agency"],
                    "geo_region": ["dach"],
                },
            },
        ).get_json()
        resp = client.post(f"/api/smart-lists/{created['id']}/run", headers=headers)
        body = resp.get_json()
        assert body["total"] == 1
        assert body["companies"][0]["name"] == "DACH Agency"

    def test_run_cultural_multi_org_type(self, client, seed_org_types):
        """Cultural filter accepts multiple org_type values via IN."""
        headers = _headers(client)
        created = client.post(
            "/api/smart-lists",
            headers=headers,
            json={
                "name": "Cultural orgs",
                "target": "company",
                "filters": {
                    "organization_type": [
                        "event_organizer",
                        "b2g_cultural",
                        "b2g_municipal",
                    ],
                    "geo_region": ["cee"],
                },
            },
        ).get_json()
        body = client.post(
            f"/api/smart-lists/{created['id']}/run", headers=headers
        ).get_json()
        assert body["total"] == 1
        assert body["companies"][0]["name"] == "Cultural Org"

    def test_preview_no_persist(self, client, seed_org_types):
        """Preview returns matches without saving a smart list."""
        headers = _headers(client)
        resp = client.post(
            "/api/smart-lists/preview",
            headers=headers,
            json={
                "target": "company",
                "filters": {
                    "organization_type": ["b2b_agency"],
                    "geo_region": ["cee"],
                },
            },
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total"] == 1
        # Nothing persisted
        items = client.get("/api/smart-lists", headers=headers).get_json()[
            "smart_lists"
        ]
        assert items == []


# --------------------------------------------------------------------------- #
#  Tenant isolation
# --------------------------------------------------------------------------- #


class TestSmartListTenantIsolation:
    def test_other_tenant_cannot_see_list(
        self, client, db, seed_org_types, seed_super_admin
    ):
        """A smart list in tenant A is not visible when querying tenant B."""
        from api.models import Tenant, UserTenantRole

        headers = _headers(client)
        created = client.post(
            "/api/smart-lists",
            headers=headers,
            json={"name": "TenantA only", "target": "company", "filters": {}},
        )
        assert created.status_code == 201, created.get_json()

        # Create a second tenant and give the super-admin a role on it.
        other = Tenant(name="Other Corp", slug="other-corp", is_active=True)
        db.session.add(other)
        db.session.flush()
        db.session.add(
            UserTenantRole(
                user_id=seed_super_admin.id,
                tenant_id=other.id,
                role="admin",
                granted_by=seed_super_admin.id,
            )
        )
        db.session.commit()

        other_headers = auth_header(client)
        other_headers["X-Namespace"] = "other-corp"
        resp = client.get("/api/smart-lists", headers=other_headers)
        assert resp.status_code == 200
        assert resp.get_json()["smart_lists"] == []


# --------------------------------------------------------------------------- #
#  Filter validation: unknown keys are dropped
# --------------------------------------------------------------------------- #


class TestFilterNormalization:
    def test_unknown_keys_dropped(self, client, seed_org_types):
        headers = _headers(client)
        resp = client.post(
            "/api/smart-lists",
            headers=headers,
            json={
                "name": "With unknown key",
                "target": "company",
                "filters": {
                    "organization_type": ["b2b_agency"],
                    "definitely_not_a_column": ["x"],
                    "; DROP TABLE companies": ["y"],
                },
            },
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert "organization_type" in body["filters"]
        assert "definitely_not_a_column" not in body["filters"]
        assert "; DROP TABLE companies" not in body["filters"]


class TestSmartListBadInputHardening:
    """Hotfix v25 — endpoints must NOT 500 on malformed list_id path params."""

    def test_get_smart_list_bad_format_returns_400(self, client, seed_org_types):
        resp = client.get("/api/smart-lists/not-a-uuid", headers=_headers(client))
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "invalid_list_id"}

    def test_get_smart_list_unknown_id_returns_404(self, client, seed_org_types):
        unknown_uuid = "00000000-0000-0000-0000-000000000000"
        resp = client.get(f"/api/smart-lists/{unknown_uuid}", headers=_headers(client))
        assert resp.status_code == 404

    def test_patch_smart_list_bad_format_returns_400(self, client, seed_org_types):
        resp = client.patch(
            "/api/smart-lists/not-a-uuid",
            json={"name": "new"},
            headers=_headers(client),
        )
        assert resp.status_code == 400

    def test_delete_smart_list_bad_format_returns_400(self, client, seed_org_types):
        resp = client.delete("/api/smart-lists/not-a-uuid", headers=_headers(client))
        assert resp.status_code == 400

    def test_run_smart_list_bad_format_returns_400(self, client, seed_org_types):
        resp = client.post("/api/smart-lists/not-a-uuid/run", headers=_headers(client))
        assert resp.status_code == 400
