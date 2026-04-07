"""OAuth routes: Google auth flow, connection management."""

import time
from datetime import datetime, timezone

import jwt
from flask import Blueprint, current_app, g, jsonify, redirect, request

from ..auth import require_auth, resolve_tenant
from ..models import OAuthConnection, db
from ..services.google_oauth import (
    encrypt_token,
    exchange_code,
    get_google_auth_url,
    revoke_connection,
)

oauth_bp = Blueprint("oauth", __name__)

# Scopes for Google Contacts + Gmail read
GOOGLE_CONTACTS_SCOPES = [
    "https://www.googleapis.com/auth/contacts.readonly",
]
GOOGLE_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
]
GOOGLE_GMAIL_SEND_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _encode_state(user_id, tenant_id, return_url=None, scopes=None):
    """JWT-encode OAuth state parameter."""
    payload = {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "return_url": return_url or "",
        "scopes": scopes or [],
        "exp": int(time.time()) + 600,  # 10 minute expiry
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm="HS256")


def _decode_state(state):
    """Decode and validate OAuth state JWT."""
    return jwt.decode(state, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"])


@oauth_bp.route("/api/oauth/google/auth-url", methods=["GET"])
@require_auth
def google_auth_url():
    """Return Google OAuth consent URL.

    Query params:
        scopes: comma-separated scope names ('contacts', 'gmail', 'both')
        return_url: dashboard URL to redirect after connection
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    scope_param = request.args.get("scopes", "contacts")
    return_url = request.args.get("return_url", "")

    scopes = []
    if scope_param == "both" or "contacts" in scope_param:
        scopes.extend(GOOGLE_CONTACTS_SCOPES)
    if "gmail_send" in scope_param:
        # Gmail send includes read + send scopes
        scopes.extend(GOOGLE_GMAIL_SEND_SCOPES)
    elif scope_param == "both" or "gmail" in scope_param:
        scopes.extend(GOOGLE_GMAIL_SCOPES)
    if not scopes:
        scopes = GOOGLE_CONTACTS_SCOPES

    # Always request email scope for identification
    scopes.append("openid")
    scopes.append("email")

    # Deduplicate
    scopes = list(dict.fromkeys(scopes))

    state = _encode_state(g.current_user.id, tenant_id, return_url, scopes=scopes)
    auth_url = get_google_auth_url(state, scopes)

    return jsonify({"auth_url": auth_url})


@oauth_bp.route("/api/oauth/google/callback", methods=["GET"])
def google_callback():
    """Handle Google OAuth callback — exchanges code, stores tokens, redirects."""
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return jsonify({"error": f"Google OAuth error: {error}"}), 400

    if not code or not state:
        return jsonify({"error": "Missing code or state parameter"}), 400

    try:
        state_data = _decode_state(state)
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "OAuth state expired, please try again"}), 400
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid OAuth state"}), 400

    user_id = state_data["user_id"]
    tenant_id = state_data["tenant_id"]
    return_url = state_data.get("return_url", "")
    requested_scopes = state_data.get("scopes", [])

    try:
        token_data = exchange_code(code)
    except Exception as e:
        return jsonify({"error": f"Token exchange failed: {str(e)}"}), 400

    now = datetime.now(timezone.utc)

    # Upsert connection — update if same provider account already exists
    existing = OAuthConnection.query.filter_by(
        user_id=user_id,
        tenant_id=tenant_id,
        provider="google",
        provider_account_id=token_data["sub"],
    ).first()

    if existing:
        existing.access_token_enc = encrypt_token(token_data["access_token"])
        if token_data.get("refresh_token"):
            existing.refresh_token_enc = encrypt_token(token_data["refresh_token"])
        existing.token_expiry = datetime.fromtimestamp(
            time.time() + token_data["expires_in"],
            tz=timezone.utc,
        )
        existing.provider_email = token_data["email"]
        existing.status = "active"
        existing.updated_at = now
        # Merge scopes: keep existing + add newly requested
        old_scopes = set(existing.scopes or [])
        new_scopes = set(requested_scopes)
        existing.scopes = list(old_scopes | new_scopes)
    else:
        conn = OAuthConnection(
            user_id=user_id,
            tenant_id=tenant_id,
            provider="google",
            provider_account_id=token_data["sub"],
            provider_email=token_data["email"],
            access_token_enc=encrypt_token(token_data["access_token"]),
            refresh_token_enc=encrypt_token(token_data.get("refresh_token")),
            token_expiry=datetime.fromtimestamp(
                time.time() + token_data["expires_in"],
                tz=timezone.utc,
            ),
            scopes=requested_scopes,
            status="active",
        )
        db.session.add(conn)

    db.session.commit()

    # Redirect back to dashboard
    if return_url:
        return redirect(return_url)
    return jsonify({"status": "connected", "email": token_data["email"]})


@oauth_bp.route("/api/oauth/connections", methods=["GET"])
@require_auth
def list_connections():
    """List current user's OAuth connections."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    connections = (
        OAuthConnection.query.filter(
            OAuthConnection.user_id == g.current_user.id,
            OAuthConnection.tenant_id == str(tenant_id),
            OAuthConnection.status != "revoked",
        )
        .order_by(OAuthConnection.created_at.desc())
        .all()
    )

    return jsonify(
        {
            "connections": [c.to_dict() for c in connections],
        }
    )


@oauth_bp.route("/api/oauth/connections/<connection_id>", methods=["DELETE"])
@require_auth
def delete_connection(connection_id):
    """Disconnect an OAuth connection (revoke tokens + delete)."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    conn = OAuthConnection.query.filter_by(
        id=connection_id,
        user_id=g.current_user.id,
        tenant_id=str(tenant_id),
    ).first()
    if not conn:
        return jsonify({"error": "Connection not found"}), 404

    revoke_connection(conn)
    db.session.commit()

    return jsonify({"status": "disconnected"})
