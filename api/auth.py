import logging
import time
from functools import wraps

import bcrypt
import jwt
from flask import current_app, g, jsonify, request
from jwt import PyJWKClient

from .models import Tenant, User, db

logger = logging.getLogger(__name__)

_jwks_client = None


def get_jwks_client():
    """Get or create a cached JWKS client for IAM RS256 token validation."""
    global _jwks_client
    if _jwks_client is None:
        jwks_url = current_app.config.get("IAM_JWKS_URL")
        if jwks_url:
            _jwks_client = PyJWKClient(
                jwks_url,
                cache_keys=True,
                max_cached_keys=4,
            )
    return _jwks_client


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, password_hash):
    if not password_hash:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user):
    roles = {}
    for r in user.roles:
        if r.tenant:
            roles[r.tenant.slug] = r.role

    payload = {
        "sub": user.id,
        "email": user.email,
        "name": user.display_name,
        "is_super_admin": user.is_super_admin,
        "roles": roles,
        "exp": int(time.time()) + current_app.config["JWT_ACCESS_EXPIRY"],
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm="HS256")


def create_refresh_token(user):
    payload = {
        "sub": user.id,
        "type": "refresh",
        "exp": int(time.time()) + current_app.config["JWT_REFRESH_EXPIRY"],
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm="HS256")


def decode_token(token):
    """Decode IAM RS256 token via JWKS, falling back to local HS256 for migration period."""
    # Try RS256 (IAM) first
    jwks_client = get_jwks_client()
    if jwks_client:
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except Exception:
            pass

    # Fallback: local HS256 (migration period only -- remove after full cutover)
    return jwt.decode(token, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"])


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401

        token = auth_header[7:]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        if payload.get("type") == "refresh":
            return jsonify({"error": "Cannot use refresh token for API access"}), 401

        # Resolve local user: try iam_user_id first, then legacy local ID
        user = None
        iam_user_id = payload.get("sub")

        # Check if this looks like an IAM token (has 'iss' from IAM or 'aud' claim)
        if payload.get("iss") == "visionvolve-iam" or payload.get("aud"):
            user = User.query.filter_by(iam_user_id=iam_user_id).first()

        if not user:
            # Legacy fallback: local token with local user ID
            user = db.session.get(User, payload.get("sub"))

        if not user or not user.is_active:
            return jsonify({"error": "User not found or inactive"}), 401

        g.current_user = user
        g.token_payload = payload
        return f(*args, **kwargs)

    return decorated


def resolve_tenant():
    """Get tenant_id from X-Namespace header. Validate user access."""
    slug = request.headers.get("X-Namespace", "").strip().lower()
    if not slug:
        # Read roles from DB (works with both IAM and legacy tokens)
        user_roles = {r.tenant.slug: r.role for r in g.current_user.roles if r.tenant}
        slug = next(iter(user_roles), None)
    if not slug:
        return None
    tenant = Tenant.query.filter_by(slug=slug, is_active=True).first()
    if not tenant:
        return None
    user = g.current_user
    if not user.is_super_admin:
        # Read roles from DB instead of token payload (IAM tokens don't have local roles)
        user_roles = {r.tenant.slug: r.role for r in user.roles if r.tenant}
        if slug not in user_roles:
            return None
    return tenant.id


def require_role(role):
    def decorator(f):
        @wraps(f)
        @require_auth
        def decorated(*args, **kwargs):
            user = g.current_user
            if user.is_super_admin:
                return f(*args, **kwargs)

            user_roles = {r.tenant.slug: r.role for r in user.roles if r.tenant}
            role_hierarchy = {"admin": 3, "editor": 2, "viewer": 1}
            required_level = role_hierarchy.get(role, 0)

            has_access = any(
                role_hierarchy.get(r, 0) >= required_level for r in user_roles.values()
            )
            if not has_access:
                return jsonify({"error": "Insufficient permissions"}), 403

            return f(*args, **kwargs)

        return decorated

    return decorator
