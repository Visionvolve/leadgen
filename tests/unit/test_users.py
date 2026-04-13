"""Unit tests for user management API."""
from tests.conftest import auth_header


class TestListUsers:
    def test_super_admin_lists_all_users(self, client, seed_super_admin, seed_user_with_role):
        headers = auth_header(client)
        resp = client.get("/api/users", headers=headers)
        assert resp.status_code == 200
        emails = [u["email"] for u in resp.get_json()]
        assert "admin@test.com" in emails
        assert "user@test.com" in emails

    def test_filter_by_tenant(self, client, seed_super_admin, seed_user_with_role, seed_tenant):
        headers = auth_header(client)
        resp = client.get(f"/api/users?tenant_id={seed_tenant.id}", headers=headers)
        assert resp.status_code == 200
        emails = [u["email"] for u in resp.get_json()]
        assert "user@test.com" in emails


class TestCreateUser:
    def test_create_user_with_tenant(self, client, seed_super_admin, seed_tenant):
        headers = auth_header(client)
        resp = client.post("/api/users", headers=headers, json={
            "email": "new@test.com",
            "password": "newpassword123",
            "display_name": "New User",
            "tenant_id": str(seed_tenant.id),
            "role": "editor",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["email"] == "new@test.com"

    def test_create_user_without_password(self, client, seed_super_admin):
        """IAM-only: creating a user without password should succeed."""
        headers = auth_header(client)
        resp = client.post("/api/users", headers=headers, json={
            "email": "nopass@test.com",
            "display_name": "No Pass User",
        })
        assert resp.status_code == 201
        assert resp.get_json()["email"] == "nopass@test.com"

    def test_create_duplicate_email_no_tenant(self, client, seed_super_admin):
        """Duplicate email without tenant_id should still return 409."""
        headers = auth_header(client)
        resp = client.post("/api/users", headers=headers, json={
            "email": "admin@test.com",
            "password": "testpass123",
            "display_name": "Duplicate",
        })
        assert resp.status_code == 409

    def test_add_existing_user_to_new_tenant(self, client, seed_super_admin, seed_tenant):
        """Existing user should be granted access to a new tenant."""
        from api.models import Tenant, db as _db
        # Create a second tenant
        tenant2 = Tenant(name="Other Corp", slug="other-corp", is_active=True)
        _db.session.add(tenant2)
        _db.session.commit()

        headers = auth_header(client)
        # First create a user in seed_tenant
        resp = client.post("/api/users", headers=headers, json={
            "email": "crossuser@test.com",
            "display_name": "Cross User",
            "tenant_id": str(seed_tenant.id),
            "role": "viewer",
        })
        assert resp.status_code == 201

        # Now add the same user to tenant2 — should succeed
        resp = client.post("/api/users", headers=headers, json={
            "email": "crossuser@test.com",
            "tenant_id": str(tenant2.id),
            "role": "editor",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert "other-corp" in data["roles"]
        assert data["roles"]["other-corp"] == "editor"

    def test_add_existing_user_to_same_tenant_rejected(self, client, seed_super_admin, seed_user_with_role, seed_tenant):
        """Adding a user who already has a role in the tenant should return 409."""
        headers = auth_header(client)
        resp = client.post("/api/users", headers=headers, json={
            "email": "user@test.com",
            "tenant_id": str(seed_tenant.id),
            "role": "editor",
        })
        assert resp.status_code == 409
        assert "already has access" in resp.get_json()["error"]


class TestUpdateUser:
    def test_update_display_name(self, client, seed_super_admin, seed_user_with_role):
        headers = auth_header(client)
        resp = client.put(f"/api/users/{seed_user_with_role.id}", headers=headers, json={
            "display_name": "Updated Name",
        })
        assert resp.status_code == 200
        assert resp.get_json()["display_name"] == "Updated Name"

    def test_deactivate_user(self, client, seed_super_admin, seed_user_with_role):
        headers = auth_header(client)
        resp = client.put(f"/api/users/{seed_user_with_role.id}", headers=headers, json={
            "is_active": False,
        })
        assert resp.status_code == 200
        assert resp.get_json()["is_active"] is False


class TestDeleteUser:
    def test_delete_deactivates_user(self, client, seed_super_admin, seed_user_with_role):
        headers = auth_header(client)
        resp = client.delete(f"/api/users/{seed_user_with_role.id}", headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True


class TestChangePassword:
    def test_password_reset_endpoint_removed(self, client, seed_super_admin, seed_user_with_role):
        """IAM-only: password reset endpoint no longer exists."""
        headers = auth_header(client)
        resp = client.put(
            f"/api/users/{seed_user_with_role.id}/password",
            headers=headers,
            json={"new_password": "newpass12345"},
        )
        assert resp.status_code in (404, 405)


class TestRemoveUserRole:
    def test_remove_role(self, client, seed_super_admin, seed_user_with_role, seed_tenant):
        headers = auth_header(client)
        resp = client.delete(
            f"/api/users/{seed_user_with_role.id}/roles/{seed_tenant.id}",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
