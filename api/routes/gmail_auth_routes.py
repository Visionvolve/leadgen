"""Gmail OAuth foundation (BL-1044).

Dedicated OAuth flow for the inbound Gmail integration that backs reply-rate
attribution. Separate from:

- `api/routes/oauth_routes.py` -- the generic multi-scope Google OAuth used
  for Google Contacts import, Gmail scan (preview), and outbound send.
- `api/routes/gmail_routes.py` -- Google Contacts fetch / Gmail scan import
  endpoints.

Tokens are encrypted with Fernet using `GMAIL_TOKEN_ENCRYPTION_KEY` (distinct
from `OAUTH_ENCRYPTION_KEY`) so Gmail connection tokens can be rotated
independently of the generic OAuth store.

CSRF: the OAuth `state` parameter is a JWT signed with the app's JWT secret
and carries `tenant_id`, `user_id`, and a return URL. State expires after
10 minutes. PKCE is not used here because the client_secret is held by the
backend -- PKCE protects public (native/SPA) clients; confidential web
clients rely on client_secret + signed state, which matches Google's
recommendation for this flow.

Follow-up sub-items (explicitly NOT in this PR):
  * BL-1044-b -- inbound Gmail polling worker that reads `last_synced_at`,
    fetches new messages, and feeds them into reply attribution.
  * BL-1044-c -- reply attribution + reply-rate KPI wiring.
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

import jwt
import requests
from flask import Blueprint, current_app, g, jsonify, redirect, request

from ..auth import require_auth, resolve_tenant
from ..models import GmailConnection, OAuthStateNonce, Tenant, db
from ..utils.crypto import decrypt_token, encrypt_token

gmail_auth_bp = Blueprint("gmail_auth", __name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# Readonly is sufficient for the inbound polling foundation (BL-1044-b).
# Additional scopes (gmail.modify, etc.) are explicitly out of scope here.
GMAIL_READONLY_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
    "email",
]

STATE_TTL_SECONDS = 600  # 10 minutes

# Whitelist of URL schemes permitted in return_url to prevent open-redirect abuse.
_SAFE_RETURN_SCHEMES = {"http", "https"}


# ---------------------------------------------------------------------------
# State (CSRF) helpers -- JWT signed with app's JWT_SECRET_KEY.
# ---------------------------------------------------------------------------


def _encode_state(user_id: str, tenant_id: str, return_url: str) -> str:
    """Issue a signed state JWT and persist its single-use nonce.

    The nonce row is consumed at callback time (_consume_nonce) to prevent
    replay of a leaked/captured state. Rows are deleted opportunistically
    when expired (see _consume_nonce) -- scheduled GC can be added later.
    """
    nonce = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS)
    payload = {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "return_url": return_url or "",
        "nonce": nonce,
        "exp": int(expires_at.timestamp()),
    }
    # Persist the nonce before returning the state so any concurrent callback
    # sees it. A failure here falls through the transaction and callers get
    # a 500, which is correct: without the nonce row the flow is unsafe.
    db.session.add(OAuthStateNonce(nonce=nonce, expires_at=expires_at))
    db.session.commit()
    return jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm="HS256")


def _decode_state(state: str) -> dict:
    return jwt.decode(state, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"])


def _consume_nonce(nonce: str | None) -> bool:
    """Atomically consume a state nonce. Returns True if valid and unused.

    Also opportunistically reaps expired rows so the table does not grow
    unbounded if no scheduled GC is wired up.
    """
    if not nonce:
        return False

    now = datetime.now(timezone.utc)
    # Opportunistic GC of expired rows. Cheap -- indexed on expires_at.
    try:
        OAuthStateNonce.query.filter(OAuthStateNonce.expires_at < now).delete(
            synchronize_session=False
        )
    except Exception:
        # GC failure must not block a valid callback.
        db.session.rollback()

    row = OAuthStateNonce.query.filter_by(nonce=nonce).first()
    if row is None:
        return False
    # Reject if expired (defence in depth; exp claim also enforced by JWT).
    # SQLite drops tz info on TIMESTAMP columns, so normalize before comparing.
    row_exp = row.expires_at
    if row_exp.tzinfo is None:
        row_exp = row_exp.replace(tzinfo=timezone.utc)
    if row_exp < now:
        db.session.delete(row)
        db.session.commit()
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def _redirect_uri() -> str:
    """Resolve the OAuth redirect URI.

    Prefers explicit env config; falls back to reconstructing from the request
    origin. Must match one of the URIs registered in the Google Cloud project.
    """
    configured = current_app.config.get("GMAIL_OAUTH_REDIRECT_URI")
    if configured:
        return configured
    # Fallback: derive from request host. Useful for local dev / staging.
    return f"{request.host_url.rstrip('/')}/api/auth/gmail/callback"


def _allowed_return_hosts() -> list[str]:
    """Hostnames (optionally with :port) permitted in return_url redirects.

    Pulled from FRONTEND_ORIGIN config. `request.host` is always accepted
    as a fallback so dev without explicit config still works.
    """
    raw = current_app.config.get("FRONTEND_ORIGIN") or ""
    allowed = [h.strip() for h in raw.split(",") if h.strip()]
    # Always trust the current request host (dev, same-origin cases).
    try:
        allowed.append(request.host)
    except RuntimeError:
        # Outside request context -- ignore.
        pass
    return allowed


def _safe_return_url(raw: str | None) -> str:
    """Return a safe return_url (same-origin relative path) or empty string.

    External absolute URLs are stripped to prevent open-redirect. Fragment-only
    values or same-origin relative paths are preserved verbatim.
    """
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme and not parsed.netloc:
        # Relative path -- safe.
        return raw
    # Absolute URL -- only allow same host and standard schemes.
    if parsed.scheme not in _SAFE_RETURN_SCHEMES:
        return ""
    if parsed.netloc not in _allowed_return_hosts():
        return ""
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def _is_safe_return_url(url: str | None) -> bool:
    """Strict same-origin / allowlist check for redirect targets.

    Used at callback time before performing the 302 so an attacker who leaks
    a state JWT cannot pivot the user off-site.
    """
    if not url:
        return False
    p = urlparse(url)
    if not p.scheme and not p.netloc:
        # Relative path -- safe.
        return True
    if p.scheme not in _SAFE_RETURN_SCHEMES:
        return False
    return p.netloc in _allowed_return_hosts()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@gmail_auth_bp.route("/api/auth/gmail/connect", methods=["GET"])
@require_auth
def gmail_connect():
    """Build the Google OAuth consent URL and redirect the user there.

    Query params:
        return: optional relative path to send the user to after callback.

    Response: 302 to Google consent screen.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    client_id = current_app.config.get("GOOGLE_GMAIL_CLIENT_ID")
    if not client_id:
        return jsonify(
            {"error": "Gmail OAuth not configured (GOOGLE_GMAIL_CLIENT_ID missing)"}
        ), 503

    return_url = _safe_return_url(request.args.get("return"))
    state = _encode_state(g.current_user.id, tenant_id, return_url)

    params = {
        "client_id": client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": " ".join(GMAIL_READONLY_SCOPES),
        "access_type": "offline",
        "prompt": "consent",  # Force refresh_token on every consent
        "include_granted_scopes": "true",
        "state": state,
    }
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    # SPA callers cannot attach an Authorization header to a top-level
    # navigation, so they request `?format=json` to fetch the URL and then
    # `window.location = auth_url`. Non-SPA callers get a 302 directly.
    if request.args.get("format") == "json":
        return jsonify({"auth_url": auth_url})
    return redirect(auth_url)


@gmail_auth_bp.route("/api/auth/gmail/callback", methods=["GET"])
def gmail_callback():
    """Handle Google's OAuth callback.

    Public (no @require_auth) because Google does the redirect -- trust is
    established via the signed `state` JWT.
    """
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

    # Single-use nonce check -- rejects replayed/leaked states.
    if not _consume_nonce(state_data.get("nonce")):
        return jsonify({"error": "Invalid or already-used OAuth state"}), 400

    user_id = state_data["user_id"]
    tenant_id = state_data["tenant_id"]
    return_url = state_data.get("return_url") or ""

    client_id = current_app.config.get("GOOGLE_GMAIL_CLIENT_ID")
    client_secret = current_app.config.get("GOOGLE_GMAIL_CLIENT_SECRET")
    enc_key = current_app.config.get("GMAIL_TOKEN_ENCRYPTION_KEY")
    if not client_id or not client_secret or not enc_key:
        return jsonify({"error": "Gmail OAuth not configured on server"}), 503

    # Exchange authorization code for tokens.
    try:
        token_resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()
    except Exception:
        # Log full context internally; return a generic message to avoid
        # leaking upstream provider responses (e.g. Google error bodies).
        current_app.logger.exception("Gmail OAuth token exchange failed")
        return jsonify({"error": "OAuth connection failed. Please try again."}), 400

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = int(tokens.get("expires_in", 3600))
    scope_granted = (tokens.get("scope") or "").split()

    if not access_token:
        current_app.logger.error("Gmail OAuth token response missing access_token")
        return jsonify({"error": "OAuth connection failed. Please try again."}), 400

    if not refresh_token:
        # Without refresh_token we cannot poll -- surface a clear, actionable
        # error. Google typically omits refresh_token when the user has
        # already granted consent to this client; revoking at
        # https://myaccount.google.com/permissions forces a fresh refresh
        # token on next consent.
        return jsonify(
            {
                "error": (
                    "Google did not issue a refresh token. Please revoke app "
                    "access at https://myaccount.google.com/permissions and "
                    "try connecting again."
                )
            }
        ), 400

    # Fetch user info to discover which Gmail address was authorized.
    try:
        userinfo_resp = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        userinfo_resp.raise_for_status()
        userinfo = userinfo_resp.json()
    except Exception:
        current_app.logger.exception("Gmail OAuth userinfo fetch failed")
        return jsonify({"error": "OAuth connection failed. Please try again."}), 400

    email_address = (userinfo.get("email") or "").lower()
    if not email_address:
        return jsonify({"error": "Google did not return an email address"}), 400

    now = datetime.now(timezone.utc)
    expires_at = datetime.fromtimestamp(time.time() + expires_in, tz=timezone.utc)

    access_enc = encrypt_token(access_token, enc_key)
    refresh_enc = encrypt_token(refresh_token, enc_key)

    # Upsert: (tenant_id, email_address) is unique. Reconnecting same inbox
    # refreshes tokens and clears any prior `disconnected_at`.
    existing = GmailConnection.query.filter_by(
        tenant_id=tenant_id, email_address=email_address
    ).first()

    if existing:
        existing.user_id = user_id
        existing.access_token_encrypted = access_enc
        existing.refresh_token_encrypted = refresh_enc
        existing.expires_at = expires_at
        existing.scopes = scope_granted or GMAIL_READONLY_SCOPES
        existing.disconnected_at = None
    else:
        db.session.add(
            GmailConnection(
                tenant_id=tenant_id,
                user_id=user_id,
                email_address=email_address,
                access_token_encrypted=access_enc,
                refresh_token_encrypted=refresh_enc,
                expires_at=expires_at,
                scopes=scope_granted or GMAIL_READONLY_SCOPES,
                created_at=now,
            )
        )
    db.session.commit()

    # Resolve the namespace for the post-callback redirect so we land back on
    # the settings page the user started from.
    tenant = db.session.get(Tenant, tenant_id)
    namespace = tenant.slug if tenant else ""

    # Defence in depth: re-validate return_url before the 302. Even though
    # connect() filters the value on input, the JWT signer could be abused
    # or the config could change between issue and redeem, so we re-check.
    if return_url and _is_safe_return_url(return_url):
        destination = return_url
    elif namespace:
        destination = f"/{namespace}/settings/gmail?connected=1"
    else:
        destination = "/?gmail_connected=1"

    frontend_base = current_app.config.get("FRONTEND_BASE_URL") or ""
    if frontend_base and destination.startswith("/"):
        destination = frontend_base.rstrip("/") + destination

    return redirect(destination)


@gmail_auth_bp.route("/api/auth/gmail/disconnect", methods=["POST"])
@require_auth
def gmail_disconnect():
    """Disconnect the current tenant's Gmail integration.

    Best-effort revokes the token at Google, marks the connection row as
    disconnected, and zeroes the stored ciphertext.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    conn = (
        GmailConnection.query.filter_by(tenant_id=tenant_id)
        .filter(GmailConnection.disconnected_at.is_(None))
        .first()
    )
    if not conn:
        return jsonify({"status": "not_connected"}), 200

    enc_key = current_app.config.get("GMAIL_TOKEN_ENCRYPTION_KEY")

    # Best-effort token revocation at Google. Failures must not block
    # disconnect (the account may have revoked access out-of-band).
    if enc_key and conn.refresh_token_encrypted:
        try:
            refresh_plain = decrypt_token(conn.refresh_token_encrypted, enc_key)
            requests.post(
                GOOGLE_REVOKE_URL,
                params={"token": refresh_plain},
                timeout=10,
            )
        except Exception:
            current_app.logger.warning(
                "Gmail token revoke failed for tenant %s; proceeding with local disconnect",
                tenant_id,
            )

    # Zero the ciphertext so tokens cannot be recovered if the row persists.
    # (We keep the row for audit/history -- `disconnected_at` marks the state.)
    conn.access_token_encrypted = b"\x00"
    conn.refresh_token_encrypted = b"\x00"
    conn.disconnected_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({"status": "disconnected"})


@gmail_auth_bp.route("/api/auth/gmail/status", methods=["GET"])
@require_auth
def gmail_status():
    """Return connection status for the current tenant."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    conn = (
        GmailConnection.query.filter_by(tenant_id=tenant_id)
        .filter(GmailConnection.disconnected_at.is_(None))
        .order_by(GmailConnection.created_at.desc())
        .first()
    )
    if not conn:
        return jsonify(
            {
                "connected": False,
                "email": None,
                "last_synced_at": None,
            }
        )

    return jsonify(
        {
            "connected": True,
            "email": conn.email_address,
            "last_synced_at": (
                conn.last_synced_at.isoformat() if conn.last_synced_at else None
            ),
            "scopes": conn.scopes if isinstance(conn.scopes, list) else [],
        }
    )


# TODO(BL-1044-b): inbound Gmail polling worker -- reads active connections,
# refreshes tokens, fetches messages via Gmail API, updates `last_synced_at`,
# feeds messages into reply-attribution pipeline.
#
# TODO(BL-1044-c): reply-rate KPI wiring -- reply attribution joins inbound
# messages to outbound campaign sends by thread id / Message-ID headers.
