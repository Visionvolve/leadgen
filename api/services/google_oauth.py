"""Google OAuth service: token encryption, auth flow, refresh, revocation."""

import time
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet
from flask import current_app

from ..models import db

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# Gmail send scope — separate from read-only scopes so users explicitly grant
GOOGLE_GMAIL_SEND_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _get_fernet():
    key = current_app.config["OAUTH_ENCRYPTION_KEY"]
    if not key:
        raise ValueError("OAUTH_ENCRYPTION_KEY not configured")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext):
    """Encrypt a token string using Fernet symmetric encryption."""
    if not plaintext:
        return None
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext):
    """Decrypt a Fernet-encrypted token string."""
    if not ciphertext:
        return None
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()


def get_google_auth_url(state, scopes):
    """Build the Google OAuth consent URL.

    Args:
        state: opaque string (JWT-encoded user_id + tenant_id + return_url)
        scopes: list of OAuth scopes

    Returns:
        Full Google consent URL string.
    """
    params = {
        "client_id": current_app.config["GOOGLE_CLIENT_ID"],
        "redirect_uri": current_app.config["GOOGLE_REDIRECT_URI"],
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return GOOGLE_AUTH_URL + "?" + urlencode(params)


def exchange_code(code):
    """Exchange authorization code for tokens.

    Returns:
        dict with access_token, refresh_token, expires_in, email, sub
    """
    resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": current_app.config["GOOGLE_CLIENT_ID"],
            "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": current_app.config["GOOGLE_REDIRECT_URI"],
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    token_data = resp.json()

    # Fetch user info to get email + sub
    userinfo_resp = requests.get(
        GOOGLE_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {token_data['access_token']}",
        },
        timeout=10,
    )
    userinfo_resp.raise_for_status()
    userinfo = userinfo_resp.json()

    return {
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": token_data.get("expires_in", 3600),
        "email": userinfo.get("email"),
        "sub": userinfo.get("sub"),
    }


def refresh_access_token(refresh_token_enc):
    """Refresh an expired access token.

    Args:
        refresh_token_enc: Fernet-encrypted refresh token

    Returns:
        dict with new access_token and expires_in
    """
    refresh_token = decrypt_token(refresh_token_enc)
    resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": current_app.config["GOOGLE_CLIENT_ID"],
            "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "expires_in": data.get("expires_in", 3600),
    }


def get_valid_token(oauth_connection):
    """Return a fresh access token, auto-refreshing if expired.

    Updates the connection in-place and flushes to DB.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    if oauth_connection.token_expiry and oauth_connection.token_expiry > now:
        return decrypt_token(oauth_connection.access_token_enc)

    # Token expired — refresh
    result = refresh_access_token(oauth_connection.refresh_token_enc)
    oauth_connection.access_token_enc = encrypt_token(result["access_token"])
    oauth_connection.token_expiry = datetime.fromtimestamp(
        time.time() + result["expires_in"],
        tz=timezone.utc,
    )
    oauth_connection.updated_at = now
    db.session.flush()
    return result["access_token"]


def revoke_connection(oauth_connection):
    """Revoke Google tokens and mark connection as revoked."""
    from datetime import datetime, timezone

    try:
        token = decrypt_token(oauth_connection.access_token_enc)
        if token:
            requests.post(GOOGLE_REVOKE_URL, params={"token": token}, timeout=10)
    except Exception:
        pass  # Best-effort revocation

    oauth_connection.status = "revoked"
    oauth_connection.access_token_enc = None
    oauth_connection.refresh_token_enc = None
    oauth_connection.updated_at = datetime.now(timezone.utc)
    db.session.flush()


def has_send_scope(oauth_connection) -> bool:
    """Check if an OAuth connection has the gmail.send scope granted."""
    scopes = oauth_connection.scopes
    if not scopes or not isinstance(scopes, list):
        return False
    return "https://www.googleapis.com/auth/gmail.send" in scopes
