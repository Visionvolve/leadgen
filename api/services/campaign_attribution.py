"""Campaign attribution URL parameter helpers.

Every microsite link embedded in outbound campaign emails carries
``?c=<campaign_id>&r=<recipient_id>`` so the microsite can forward
those values to PostHog as super-properties. That makes backend
analytics queries (see ``api/routes/campaign_routes.py`` analytics
endpoints and BL-1035) able to filter ``events`` by
``properties.campaign_id`` and ``properties.recipient_id``.

Design notes:

- **Idempotent**: if the URL already carries ``c``/``r`` query keys,
  the existing values are preserved (first-write-wins). This keeps
  re-renders stable and avoids surprising the recipient with changing
  links.
- **Preserves existing query strings**: we use ``urllib.parse`` so a
  URL like ``https://demo.visionvolve.com/invite/abc?lang=cs`` becomes
  ``https://demo.visionvolve.com/invite/abc?lang=cs&c=<id>&r=<id>``.
- **Preserves fragments**: ``#section`` is kept intact.
- **Bail out for non-microsite URLs**: unsubscribe / mailto / tel links
  are never decorated with campaign params (would leak tenant IDs into
  unrelated domains).

The ``campaign_id`` and ``recipient_id`` are **opaque identifiers**
from our database (typically UUID strings). Their values are treated
as tenant-scoped secrets in the sense that they should only appear on
links we explicitly create — callers must ensure they originate from a
tenant-scoped query before passing them in.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

__all__ = [
    "add_campaign_attribution",
    "is_microsite_url",
]


def is_microsite_url(url: str, microsite_base_url: str) -> bool:
    """Return True when ``url`` is a microsite link we should tag.

    A URL matches when its scheme + host match the configured
    ``UA_MICROSITE_URL`` base. Anything else (mailto:, tel:, external
    CTAs, unsubscribe links pointing at our API, etc.) is rejected so
    campaign IDs never leak outside the microsite domain.

    Empty/None inputs return False. Malformed URLs return False.
    """
    if not url or not microsite_base_url:
        return False
    try:
        parsed = urlparse(url)
        base = urlparse(microsite_base_url)
    except (ValueError, TypeError):
        return False
    if not parsed.scheme or not parsed.netloc:
        return False
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    return (
        parsed.scheme.lower() == base.scheme.lower()
        and parsed.netloc.lower() == base.netloc.lower()
    )


def add_campaign_attribution(
    url: str,
    *,
    campaign_id: str | None,
    recipient_id: str | None,
    microsite_base_url: str | None = None,
) -> str:
    """Append ``?c=<campaign_id>&r=<recipient_id>`` to ``url``.

    Idempotent: if ``c`` / ``r`` keys are already present on the URL,
    the existing values win and the URL is returned unchanged (modulo
    re-encoding of other params).

    When ``microsite_base_url`` is provided, URLs that don't point at
    the microsite host are returned unchanged — we never attach
    campaign IDs to unsubscribe, mailto, or external links.

    Args:
        url: Full URL to decorate (typically from
            ``get_or_create_invite`` or ``UA_MICROSITE_URL``).
        campaign_id: Campaign identifier (UUID string). ``None`` or
            empty means "skip the ``c`` param".
        recipient_id: Recipient identifier (``CampaignContact.id`` UUID
            string — durable across re-sends). ``None`` or empty means
            "skip the ``r`` param".
        microsite_base_url: Optional base URL (e.g.
            ``https://demo.visionvolve.com``). When provided, non-
            microsite URLs are returned unchanged.

    Returns:
        URL with ``c``/``r`` params merged into the query string.
        Returns ``url`` unchanged if it's empty, malformed, or not a
        microsite URL (when base is supplied).
    """
    if not url:
        return url

    if microsite_base_url and not is_microsite_url(url, microsite_base_url):
        return url

    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return url

    # Reject things that parsed but don't look like tagged URLs (e.g.
    # mailto:, tel:, relative URLs without scheme).
    if not parsed.scheme or not parsed.netloc:
        return url
    if parsed.scheme.lower() not in ("http", "https"):
        return url

    # Parse the existing query string preserving multi-value params.
    existing = parse_qsl(parsed.query, keep_blank_values=True)
    existing_keys = {k for k, _ in existing}

    extras: list[tuple[str, str]] = []
    if campaign_id and "c" not in existing_keys:
        extras.append(("c", str(campaign_id)))
    if recipient_id and "r" not in existing_keys:
        extras.append(("r", str(recipient_id)))

    if not extras:
        # Nothing to add — return original URL untouched.
        return url

    merged_query = urlencode(existing + extras, doseq=True, safe="")
    return urlunparse(parsed._replace(query=merged_query))
