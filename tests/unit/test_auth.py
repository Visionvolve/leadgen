"""Unit tests for IAM-only authentication module."""
import json
import time
import uuid
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import jwt as pyjwt

from tests.conftest import auth_header


class TestAuthLogin:
    """Test /api/auth/login — IAM proxy only, no local fallback."""

    def test_login_success_via_iam(self, client, app, seed_super_admin):
        """IAM returns 200 — user is synced and IAM tokens are returned."""
        iam_user_id = str(uuid.uuid4())
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "iam-access-token",
            "refresh_token": "iam-refresh-token",
            "user": {
                "id": iam_user_id,
                "email": "admin@test.com",
                "name": "Admin User",
                "permissions": [],
            },
        }

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch("api.routes.auth_routes.requests.post", return_value=mock_resp):
            resp = client.post("/api/auth/login", json={
                "email": "admin@test.com",
                "password": "somepassword",
            })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["access_token"] == "iam-access-token"
        assert data["refresh_token"] == "iam-refresh-token"
        assert data["user"]["email"] == "admin@test.com"

    def test_login_iam_returns_401(self, client, app, seed_super_admin):
        """IAM returns 401 — no local fallback, return 401."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch("api.routes.auth_routes.requests.post", return_value=mock_resp):
            resp = client.post("/api/auth/login", json={
                "email": "admin@test.com",
                "password": "wrongpassword",
            })

        assert resp.status_code == 401
        assert "Invalid" in resp.get_json()["error"]

    def test_login_iam_unreachable(self, client, app, seed_super_admin):
        """IAM is unreachable — return 503, no local fallback."""
        import requests as req_lib

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch(
            "api.routes.auth_routes.requests.post",
            side_effect=req_lib.ConnectionError("refused"),
        ):
            resp = client.post("/api/auth/login", json={
                "email": "admin@test.com",
                "password": "testpass123",
            })

        assert resp.status_code == 503
        assert "unavailable" in resp.get_json()["error"].lower()

    def test_login_no_iam_configured(self, client, app, db):
        """IAM_BASE_URL not set — return 503."""
        with app.app_context():
            app.config.pop("IAM_BASE_URL", None)

        resp = client.post("/api/auth/login", json={
            "email": "nobody@test.com",
            "password": "testpass123",
        })
        assert resp.status_code == 503

    def test_login_missing_fields(self, client, db):
        resp = client.post("/api/auth/login", json={"email": "a@b.com"})
        assert resp.status_code == 400

    def test_login_no_body(self, client, db):
        resp = client.post("/api/auth/login")
        assert resp.status_code == 400


class TestAuthRefresh:
    """Test /api/auth/refresh — IAM proxy only."""

    def test_refresh_success(self, client, app, db):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "new-iam-access-token"}

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch("api.routes.auth_routes.requests.post", return_value=mock_resp):
            resp = client.post("/api/auth/refresh", json={
                "refresh_token": "some-iam-refresh-token",
            })

        assert resp.status_code == 200
        assert resp.get_json()["access_token"] == "new-iam-access-token"

    def test_refresh_iam_failure(self, client, app, db):
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch("api.routes.auth_routes.requests.post", return_value=mock_resp):
            resp = client.post("/api/auth/refresh", json={
                "refresh_token": "expired-token",
            })

        assert resp.status_code == 401

    def test_refresh_missing_token(self, client, db):
        resp = client.post("/api/auth/refresh", json={})
        assert resp.status_code == 400

    def test_refresh_no_iam_configured(self, client, app, db):
        with app.app_context():
            app.config.pop("IAM_BASE_URL", None)

        resp = client.post("/api/auth/refresh", json={
            "refresh_token": "some-token",
        })
        assert resp.status_code == 503


class TestAuthMe:
    def test_me_returns_user(self, client, seed_super_admin):
        headers = auth_header(client)
        resp = client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["email"] == "admin@test.com"

    def test_me_no_token(self, client, db):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_invalid_token(self, client, db):
        resp = client.get("/api/auth/me", headers={
            "Authorization": "Bearer invalid.token.here"
        })
        assert resp.status_code == 401


def _make_iam_access_token(sub, email, name, permissions=None):
    """Build a fake IAM JWT (unsigned) for testing the callback decode path."""
    payload = {
        "sub": sub,
        "email": email,
        "name": name,
        "permissions": permissions or [],
        "aud": "leadgen",
        "exp": int(time.time()) + 3600,
    }
    return pyjwt.encode(payload, "fake-secret", algorithm="HS256")


class TestIAMCallback:
    """Test /api/auth/iam/callback — OAuth code exchange + user sync + redirect."""

    def _mock_exchange_response(self, access_token, refresh_token="iam-refresh"):
        """Build a MagicMock for a successful IAM /token/exchange response."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
        }
        return mock_resp

    def test_happy_path_redirects_with_tokens(self, client, app, seed_super_admin):
        """Successful code exchange → redirect to /auth/callback# with tokens + user JSON."""
        iam_user_id = seed_super_admin.iam_user_id
        access_token = _make_iam_access_token(
            iam_user_id, "admin@test.com", "Admin User",
        )
        mock_resp = self._mock_exchange_response(access_token, "refresh-tok-123")

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch("api.routes.auth_routes.requests.post", return_value=mock_resp) as mock_post:
            resp = client.get("/api/auth/iam/callback?code=AUTH_CODE_ABC")

        # Should POST to IAM /token/exchange with the code
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://iam.test.local/token/exchange"
        assert call_args[1]["json"] == {"code": "AUTH_CODE_ABC"}

        # Should redirect (302) to /auth/callback#...
        assert resp.status_code == 302
        location = resp.headers["Location"]
        assert location.startswith("/auth/callback#")

        # Parse the fragment
        fragment = location.split("#", 1)[1]
        params = parse_qs(fragment)
        assert params["access_token"][0] == access_token
        assert params["refresh_token"][0] == "refresh-tok-123"

        # User JSON should be parseable and contain email
        user_data = json.loads(params["user"][0])
        assert user_data["email"] == "admin@test.com"

    def test_error_query_param_redirects(self, client, app, db):
        """IAM redirects with ?error=access_denied → redirect to /?error=access_denied."""
        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        resp = client.get("/api/auth/iam/callback?error=access_denied")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/?error=access_denied"

    def test_login_required_param_redirects(self, client, app, db):
        """IAM redirects with ?login_required=true → redirect to /?login_required=true."""
        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        resp = client.get("/api/auth/iam/callback?login_required=true")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/?login_required=true"

    def test_missing_code_redirects_with_error(self, client, app, db):
        """No code param → redirect to /?error=missing_code."""
        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        resp = client.get("/api/auth/iam/callback")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/?error=missing_code"

    def test_iam_not_configured(self, client, app, db):
        """IAM_BASE_URL not set → redirect to /?error=iam_not_configured."""
        with app.app_context():
            app.config.pop("IAM_BASE_URL", None)

        resp = client.get("/api/auth/iam/callback?code=SOME_CODE")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/?error=iam_not_configured"

    def test_token_exchange_non_200(self, client, app, db):
        """IAM /token/exchange returns 400 → redirect to /?error=token_exchange_failed."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch("api.routes.auth_routes.requests.post", return_value=mock_resp):
            resp = client.get("/api/auth/iam/callback?code=BAD_CODE")

        assert resp.status_code == 302
        assert resp.headers["Location"] == "/?error=token_exchange_failed"

    def test_token_exchange_network_error(self, client, app, db):
        """IAM unreachable → redirect to /?error=iam_unreachable."""
        import requests as req_lib

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch(
            "api.routes.auth_routes.requests.post",
            side_effect=req_lib.ConnectionError("refused"),
        ):
            resp = client.get("/api/auth/iam/callback?code=SOME_CODE")

        assert resp.status_code == 302
        assert resp.headers["Location"] == "/?error=iam_unreachable"

    def test_no_access_token_in_response(self, client, app, db):
        """Exchange succeeds but no accessToken in body → redirect to /?error=no_access_token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"refreshToken": "some-refresh"}

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch("api.routes.auth_routes.requests.post", return_value=mock_resp):
            resp = client.get("/api/auth/iam/callback?code=SOME_CODE")

        assert resp.status_code == 302
        assert resp.headers["Location"] == "/?error=no_access_token"

    def test_invalid_jwt_in_access_token(self, client, app, db):
        """Access token is garbage (not a valid JWT) → redirect to /?error=invalid_token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "accessToken": "not-a-valid-jwt",
            "refreshToken": "some-refresh",
        }

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch("api.routes.auth_routes.requests.post", return_value=mock_resp):
            resp = client.get("/api/auth/iam/callback?code=SOME_CODE")

        assert resp.status_code == 302
        assert resp.headers["Location"] == "/?error=invalid_token"

    def test_find_or_create_local_user_called_with_iam_data(
        self, client, app, seed_super_admin,
    ):
        """Verify find_or_create_local_user receives the decoded IAM user data."""
        iam_user_id = str(uuid.uuid4())
        access_token = _make_iam_access_token(
            iam_user_id, "oauth@example.com", "OAuth User",
        )
        mock_resp = self._mock_exchange_response(access_token)

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch("api.routes.auth_routes.requests.post", return_value=mock_resp), \
             patch("api.routes.auth_routes.find_or_create_local_user") as mock_sync, \
             patch("api.routes.auth_routes.sync_iam_roles"):
            # find_or_create_local_user must return a user-like object
            mock_user = MagicMock()
            mock_user.to_dict.return_value = {
                "id": "local-id",
                "email": "oauth@example.com",
            }
            mock_sync.return_value = mock_user

            resp = client.get("/api/auth/iam/callback?code=VALID_CODE")

        assert resp.status_code == 302
        mock_sync.assert_called_once()
        call_arg = mock_sync.call_args[0][0]
        assert call_arg["id"] == iam_user_id
        assert call_arg["email"] == "oauth@example.com"
        assert call_arg["name"] == "OAuth User"

    def test_user_sync_failure_redirects(self, client, app, db):
        """find_or_create_local_user raises → redirect to /?error=user_sync_failed."""
        iam_user_id = str(uuid.uuid4())
        access_token = _make_iam_access_token(iam_user_id, "fail@test.com", "Fail")
        mock_resp = self._mock_exchange_response(access_token)

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch("api.routes.auth_routes.requests.post", return_value=mock_resp), \
             patch(
                 "api.routes.auth_routes.find_or_create_local_user",
                 side_effect=Exception("DB exploded"),
             ):
            resp = client.get("/api/auth/iam/callback?code=SOME_CODE")

        assert resp.status_code == 302
        assert resp.headers["Location"] == "/?error=user_sync_failed"

    def test_happy_path_creates_new_user(self, client, app, db):
        """Full integration: new IAM user → local user created → redirect with tokens."""
        from api.models import User

        iam_user_id = str(uuid.uuid4())
        access_token = _make_iam_access_token(
            iam_user_id, "newuser@example.com", "New User",
        )
        mock_resp = self._mock_exchange_response(access_token, "refresh-new")

        with app.app_context():
            app.config["IAM_BASE_URL"] = "https://iam.test.local"

        with patch("api.routes.auth_routes.requests.post", return_value=mock_resp):
            resp = client.get("/api/auth/iam/callback?code=FRESH_CODE")

        assert resp.status_code == 302
        location = resp.headers["Location"]
        assert "/auth/callback#" in location

        # Verify user was persisted
        with app.app_context():
            user = User.query.filter_by(email="newuser@example.com").first()
            assert user is not None
            assert user.iam_user_id == iam_user_id
            assert user.display_name == "New User"
            assert user.last_login_at is not None
