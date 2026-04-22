"""Tests for the BL-1044 Gmail OAuth foundation routes."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet

from api.models import GmailConnection, UserTenantRole
from api.utils.crypto import decrypt_token, encrypt_token
from tests.conftest import auth_header

TEST_FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _configure_gmail_oauth(app):
    app.config["GOOGLE_GMAIL_CLIENT_ID"] = "gmail-client"
    app.config["GOOGLE_GMAIL_CLIENT_SECRET"] = "gmail-secret"
    app.config["GMAIL_OAUTH_REDIRECT_URI"] = (
        "http://localhost:5001/api/auth/gmail/callback"
    )
    app.config["GMAIL_TOKEN_ENCRYPTION_KEY"] = TEST_FERNET_KEY
    app.config["FRONTEND_BASE_URL"] = ""
    yield


@pytest.fixture
def seed_admin_on_tenant(db, seed_tenant, seed_super_admin):
    """Grant the seeded admin user an admin role on the test tenant so
    resolve_tenant() permits access via X-Namespace header."""
    role = UserTenantRole(
        user_id=seed_super_admin.id,
        tenant_id=seed_tenant.id,
        role="admin",
        granted_by=seed_super_admin.id,
    )
    db.session.add(role)
    db.session.commit()
    return seed_super_admin


def _ns_headers(client, slug="test-corp"):
    h = auth_header(client)
    h["X-Namespace"] = slug
    return h


class TestConnect:
    def test_connect_json_returns_auth_url(
        self, client, seed_tenant, seed_admin_on_tenant
    ):
        resp = client.get(
            "/api/auth/gmail/connect?format=json",
            headers=_ns_headers(client),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "auth_url" in data
        url = data["auth_url"]
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "gmail.readonly" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert "state=" in url

    def test_connect_redirects_by_default(
        self, client, seed_tenant, seed_admin_on_tenant
    ):
        resp = client.get(
            "/api/auth/gmail/connect",
            headers=_ns_headers(client),
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.location.startswith("https://accounts.google.com/o/oauth2/v2/auth")

    def test_connect_requires_auth(self, client):
        resp = client.get("/api/auth/gmail/connect?format=json")
        assert resp.status_code == 401

    def test_connect_rejects_unknown_tenant(self, client, seed_admin_on_tenant):
        h = auth_header(client)
        h["X-Namespace"] = "no-such-tenant"
        resp = client.get("/api/auth/gmail/connect?format=json", headers=h)
        assert resp.status_code == 404

    def test_connect_503_when_unconfigured(
        self, client, app, seed_tenant, seed_admin_on_tenant
    ):
        app.config["GOOGLE_GMAIL_CLIENT_ID"] = ""
        resp = client.get(
            "/api/auth/gmail/connect?format=json",
            headers=_ns_headers(client),
        )
        assert resp.status_code == 503


class TestCallback:
    def _mock_google_responses(self, monkeypatch):
        token_resp = MagicMock()
        token_resp.raise_for_status = MagicMock()
        token_resp.json.return_value = {
            "access_token": "ya29.fresh-access",
            "refresh_token": "1//refresh-val",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.readonly openid email",
        }

        user_resp = MagicMock()
        user_resp.raise_for_status = MagicMock()
        user_resp.json.return_value = {
            "email": "Founder@Example.COM",
            "sub": "g-123",
        }

        from api.routes import gmail_auth_routes

        monkeypatch.setattr(
            gmail_auth_routes.requests, "post", lambda *a, **kw: token_resp
        )
        monkeypatch.setattr(
            gmail_auth_routes.requests, "get", lambda *a, **kw: user_resp
        )

    def _make_state(self, app, user_id, tenant_id, return_url=""):
        import time as _time

        payload = {
            "user_id": str(user_id),
            "tenant_id": str(tenant_id),
            "return_url": return_url,
            "nonce": 1,
            "exp": int(_time.time()) + 600,
        }
        return pyjwt.encode(payload, app.config["JWT_SECRET_KEY"], algorithm="HS256")

    def test_callback_stores_encrypted_tokens(
        self, client, app, db, seed_tenant, seed_admin_on_tenant, monkeypatch
    ):
        self._mock_google_responses(monkeypatch)
        state = self._make_state(app, seed_admin_on_tenant.id, seed_tenant.id)

        resp = client.get(
            f"/api/auth/gmail/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/settings/gmail" in resp.location

        conn = GmailConnection.query.filter_by(tenant_id=seed_tenant.id).first()
        assert conn is not None
        assert conn.email_address == "founder@example.com"  # normalized lowercase
        assert conn.disconnected_at is None
        # Ciphertext must not be the plaintext
        assert conn.access_token_encrypted not in (
            b"ya29.fresh-access",
            "ya29.fresh-access",
        )
        # Round-trip decrypt
        key = app.config["GMAIL_TOKEN_ENCRYPTION_KEY"]
        assert decrypt_token(conn.access_token_encrypted, key) == "ya29.fresh-access"
        assert decrypt_token(conn.refresh_token_encrypted, key) == "1//refresh-val"

    def test_callback_rejects_invalid_state(self, client):
        resp = client.get(
            "/api/auth/gmail/callback?code=abc&state=not-a-jwt",
            follow_redirects=False,
        )
        assert resp.status_code == 400

    def test_callback_rejects_expired_state(self, client, app):
        import time as _time

        payload = {
            "user_id": "u",
            "tenant_id": "t",
            "return_url": "",
            "nonce": 1,
            "exp": int(_time.time()) - 10,
        }
        expired = pyjwt.encode(payload, app.config["JWT_SECRET_KEY"], algorithm="HS256")
        resp = client.get(
            f"/api/auth/gmail/callback?code=abc&state={expired}",
            follow_redirects=False,
        )
        assert resp.status_code == 400

    def test_callback_requires_refresh_token(
        self, client, app, seed_tenant, seed_admin_on_tenant, monkeypatch
    ):
        token_resp = MagicMock()
        token_resp.raise_for_status = MagicMock()
        token_resp.json.return_value = {
            "access_token": "ya29.access-only",
            "expires_in": 3600,
            # No refresh_token!
        }
        from api.routes import gmail_auth_routes

        monkeypatch.setattr(
            gmail_auth_routes.requests, "post", lambda *a, **kw: token_resp
        )
        state = self._make_state(app, seed_admin_on_tenant.id, seed_tenant.id)
        resp = client.get(
            f"/api/auth/gmail/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 400

    def test_callback_upsert_reconnects(
        self, client, app, db, seed_tenant, seed_admin_on_tenant, monkeypatch
    ):
        """Calling callback a second time for the same inbox should refresh
        tokens and clear any prior disconnected_at."""
        self._mock_google_responses(monkeypatch)
        # Pre-seed an existing connection marked disconnected
        key = app.config["GMAIL_TOKEN_ENCRYPTION_KEY"]
        prior = GmailConnection(
            tenant_id=seed_tenant.id,
            user_id=seed_admin_on_tenant.id,
            email_address="founder@example.com",
            access_token_encrypted=encrypt_token("old", key),
            refresh_token_encrypted=encrypt_token("old-refresh", key),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            scopes=["foo"],
            disconnected_at=datetime.now(timezone.utc),
        )
        db.session.add(prior)
        db.session.commit()

        state = self._make_state(app, seed_admin_on_tenant.id, seed_tenant.id)
        resp = client.get(
            f"/api/auth/gmail/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 302

        db.session.refresh(prior)
        assert prior.disconnected_at is None
        assert decrypt_token(prior.access_token_encrypted, key) == "ya29.fresh-access"


class TestStatus:
    def test_status_when_not_connected(self, client, seed_tenant, seed_admin_on_tenant):
        resp = client.get("/api/auth/gmail/status", headers=_ns_headers(client))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["connected"] is False
        assert data["email"] is None
        assert data["last_synced_at"] is None

    def test_status_when_connected(
        self, client, app, db, seed_tenant, seed_admin_on_tenant
    ):
        key = app.config["GMAIL_TOKEN_ENCRYPTION_KEY"]
        conn = GmailConnection(
            tenant_id=seed_tenant.id,
            user_id=seed_admin_on_tenant.id,
            email_address="owner@corp.com",
            access_token_encrypted=encrypt_token("a", key),
            refresh_token_encrypted=encrypt_token("r", key),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=["gmail.readonly"],
        )
        db.session.add(conn)
        db.session.commit()

        resp = client.get("/api/auth/gmail/status", headers=_ns_headers(client))
        data = resp.get_json()
        assert data["connected"] is True
        assert data["email"] == "owner@corp.com"

    def test_status_hides_disconnected(
        self, client, app, db, seed_tenant, seed_admin_on_tenant
    ):
        key = app.config["GMAIL_TOKEN_ENCRYPTION_KEY"]
        conn = GmailConnection(
            tenant_id=seed_tenant.id,
            user_id=seed_admin_on_tenant.id,
            email_address="disc@corp.com",
            access_token_encrypted=encrypt_token("a", key),
            refresh_token_encrypted=encrypt_token("r", key),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=["gmail.readonly"],
            disconnected_at=datetime.now(timezone.utc),
        )
        db.session.add(conn)
        db.session.commit()

        resp = client.get("/api/auth/gmail/status", headers=_ns_headers(client))
        assert resp.get_json()["connected"] is False


class TestDisconnect:
    def test_disconnect_clears_tokens_and_marks_row(
        self, client, app, db, seed_tenant, seed_admin_on_tenant, monkeypatch
    ):
        # Stub revoke POST so we don't hit the network
        from api.routes import gmail_auth_routes

        monkeypatch.setattr(
            gmail_auth_routes.requests, "post", lambda *a, **kw: MagicMock()
        )

        key = app.config["GMAIL_TOKEN_ENCRYPTION_KEY"]
        conn = GmailConnection(
            tenant_id=seed_tenant.id,
            user_id=seed_admin_on_tenant.id,
            email_address="own@corp.com",
            access_token_encrypted=encrypt_token("a", key),
            refresh_token_encrypted=encrypt_token("r", key),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=["gmail.readonly"],
        )
        db.session.add(conn)
        db.session.commit()

        resp = client.post("/api/auth/gmail/disconnect", headers=_ns_headers(client))
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "disconnected"

        db.session.refresh(conn)
        assert conn.disconnected_at is not None
        # Ciphertext was zeroed
        assert bytes(conn.access_token_encrypted) == b"\x00"
        assert bytes(conn.refresh_token_encrypted) == b"\x00"

    def test_disconnect_when_not_connected(
        self, client, seed_tenant, seed_admin_on_tenant
    ):
        resp = client.post("/api/auth/gmail/disconnect", headers=_ns_headers(client))
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "not_connected"


class TestTenantIsolation:
    """Different tenants must not see each other's Gmail connections."""

    def test_status_only_returns_current_tenant(
        self, client, app, db, seed_tenant, seed_admin_on_tenant
    ):
        from api.models import Tenant

        # Second tenant with a connection that should not leak
        other = Tenant(name="Other", slug="other-corp", is_active=True)
        db.session.add(other)
        db.session.flush()
        key = app.config["GMAIL_TOKEN_ENCRYPTION_KEY"]
        foreign = GmailConnection(
            tenant_id=other.id,
            user_id=seed_admin_on_tenant.id,
            email_address="secret@other.com",
            access_token_encrypted=encrypt_token("a", key),
            refresh_token_encrypted=encrypt_token("r", key),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=["gmail.readonly"],
        )
        db.session.add(foreign)
        db.session.commit()

        # Request with seed_tenant's namespace -- must NOT see 'secret@other.com'
        resp = client.get(
            "/api/auth/gmail/status",
            headers=_ns_headers(client, slug="test-corp"),
        )
        data = resp.get_json()
        assert data["connected"] is False
        assert data["email"] is None
