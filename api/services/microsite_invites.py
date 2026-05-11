"""Microsite invite link generation service.

Creates unique partner invite links via the ua-microsite
``/api/invites/bulk`` endpoint. Idempotent by email — returns the existing
invite if one already exists for that address.

The bulk endpoint is used (rather than the singular ``/api/invites``)
because only the bulk endpoint applies EventFest preference defaults
(``preferences.recommended`` etc.) via the ``applyEventFestDefaults``
top-level flag. Without those defaults the microsite homepage's
``RecommendedSection`` stays hidden (it is gated on
``session.isPartner && recommended.length > 0``), which silently breaks
the core personalization value prop.

Usage::

    from api.services.microsite_invites import get_or_create_invite

    url = get_or_create_invite(
        "jana@example.com", "Jana Nováková",
        "https://booking.loserscirque.cz", "secret-key",
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
    *,
    company: str | None = None,
    apply_eventfest_defaults: bool = True,
) -> str | None:
    """Call ua-microsite ``POST /api/invites/bulk`` to get or create a partner invite.

    The microsite API is idempotent by email — returns the existing invite
    if one already exists for that address (``status: "reused"``).

    Args:
        email: Contact email address.
        name: Contact full name.
        microsite_url: Base URL of the microsite
            (e.g. ``https://booking.loserscirque.cz``).
        api_key: API key for the microsite invite endpoint.
        company: Optional company/organization name; surfaced in the
            invite's ``preferences.notes`` for admin visibility.
        apply_eventfest_defaults: When ``True`` (default), the request body
            includes ``applyEventFestDefaults: true`` at the TOP LEVEL of
            the body (NOT inside a contact) so the microsite seeds
            EventFest preference defaults on new invites. Set to ``False``
            for non-EventFest invites that should start with empty
            preferences.

    Returns:
        Full invite URL (e.g. ``https://booking.loserscirque.cz/invite/abc123``),
        or ``None`` if the API is unreachable after one retry or if the
        per-contact result returned ``status: "error"``.
    """
    base_url = (microsite_url or "").rstrip("/")
    if not base_url or not api_key:
        logger.warning("Microsite URL or API key not configured")
        return None

    endpoint = f"{base_url}/api/invites/bulk"
    contact: dict[str, str] = {"email": email, "name": name}
    if company:
        contact["company"] = company

    payload: dict[str, object] = {"contacts": [contact]}
    # NOTE: applyEventFestDefaults MUST be at the TOP LEVEL of the body,
    # NOT inside a contact. Nesting it produces a 400 from the microsite.
    if apply_eventfest_defaults:
        payload["applyEventFestDefaults"] = True

    headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    last_error: Exception | None = None
    for attempt in range(2):  # one retry
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results") or []
            if not results:
                raise ValueError(
                    f"bulk response missing 'results' for {email}: {data!r}"
                )

            result = results[0]
            status = result.get("status")
            if status == "error":
                # Per-contact error (e.g. missing email) — do not retry;
                # retries would repeat the same failure.
                logger.error(
                    "Microsite bulk invite returned error for %s: %s",
                    email,
                    result.get("error"),
                )
                return None

            token = result.get("token") or ""
            invite_url = result.get("url") or ""

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
