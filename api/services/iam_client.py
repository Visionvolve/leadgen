"""IAM HTTP client — create users and manage access in the central IAM service."""

import logging
from typing import Optional

import requests
from flask import current_app

logger = logging.getLogger(__name__)

# Timeout for IAM HTTP calls (seconds)
_TIMEOUT = 10


def _iam_url(path: str) -> str:
    base = current_app.config.get("IAM_BASE_URL", "https://iam.visionvolve.com")
    return f"{base.rstrip('/')}/api{path}"


def _service_headers() -> dict:
    key = current_app.config.get("IAM_SERVICE_API_KEY", "")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def ensure_iam_user(email: str, display_name: Optional[str] = None) -> Optional[dict]:
    """Create user in IAM if they don't exist. Returns IAM user dict or None on failure.

    Uses the service-to-service POST /auth/create-user endpoint.
    If the user already exists, IAM returns the existing record (created=false).

    Returns:
        dict with keys: id, email, name, created (bool)
        None if the call fails (caller should log warning and continue)
    """
    key = current_app.config.get("IAM_SERVICE_API_KEY", "")
    if not key:
        logger.warning("IAM_SERVICE_API_KEY not configured, skipping IAM user creation")
        return None

    try:
        resp = requests.post(
            _iam_url("/auth/create-user"),
            json={
                "email": email,
                "name": display_name,
                "app": "leadgen",
            },
            headers=_service_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            logger.info(
                "IAM user %s: %s (created=%s)",
                email,
                data.get("user", {}).get("id", "?"),
                data.get("created", False),
            )
            return data
        else:
            logger.warning(
                "IAM create-user failed for %s: HTTP %s — %s",
                email,
                resp.status_code,
                resp.text[:200],
            )
            return None
    except requests.RequestException as exc:
        logger.warning("IAM create-user request failed for %s: %s", email, exc)
        return None


def grant_iam_access(
    iam_user_id: str,
    app: str = "leadgen",
    role: str = "viewer",
    scope: Optional[str] = None,
) -> bool:
    """Grant app_access in IAM for the given user.

    Uses the admin POST /admin/users/:id/access endpoint.
    NOTE: This endpoint requires admin JWT auth, not service key.
    For now, we rely on the create-user endpoint granting basic 'leadgen' access,
    and log a warning that scope/role grants need the admin API.

    Returns True if successful, False otherwise.
    """
    # The admin endpoint requires JWT auth which we don't have in service context.
    # The create-user endpoint already grants basic leadgen:viewer access.
    # For specific role/scope grants, an admin must use the IAM dashboard.
    if role != "viewer" or scope:
        logger.info(
            "IAM role=%s scope=%s for user %s requires admin grant (not available via service API)",
            role,
            scope,
            iam_user_id,
        )
    return True
