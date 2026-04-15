"""Microsite invite link generation service.

Creates unique partner invite links via the ua-microsite ``/api/invites``
endpoint.  Idempotent by email — returns existing invite if one already
exists for that address.

Usage::

    from api.services.microsite_invites import get_or_create_invite

    url = get_or_create_invite(
        "jana@example.com", "Jana Nováková",
        "https://demo.visionvolve.com", "secret-key",
    )
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


def get_or_create_invite(
    email: str,
    name: str,
    microsite_url: str,
    api_key: str,
) -> str | None:
    """Call ua-microsite ``POST /api/invites`` to get or create a partner invite.

    The microsite API is idempotent by email — returns the existing invite
    if one already exists for that address.

    Args:
        email: Contact email address.
        name: Contact full name.
        microsite_url: Base URL of the microsite (e.g. ``https://demo.visionvolve.com``).
        api_key: API key for the microsite invite endpoint.

    Returns:
        Full invite URL (e.g. ``https://demo.visionvolve.com/invite/abc123``),
        or ``None`` if the API is unreachable after one retry.
    """
    base_url = (microsite_url or "").rstrip("/")
    if not base_url or not api_key:
        logger.warning("Microsite URL or API key not configured")
        return None

    endpoint = f"{base_url}/api/invites"
    payload = {"email": email, "name": name, "type": "partner"}
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    last_error: Exception | None = None
    for attempt in range(2):  # one retry
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            token = data.get("token") or ""
            invite_url = data.get("url") or ""

            if invite_url.startswith("/"):
                invite_url = f"{base_url}{invite_url}"
            elif not invite_url and token:
                invite_url = f"{base_url}/invite/{token}"

            return invite_url
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Microsite invite request failed (attempt %d): %s",
                attempt + 1,
                exc,
            )

    logger.error(
        "Microsite invite creation failed for %s after retries: %s",
        email,
        last_error,
    )
    return None
