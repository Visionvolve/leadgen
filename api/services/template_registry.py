"""Template registry for multilingual email rendering.

Maps ``(template_key, language)`` to a renderer callable so that the send
pipeline can pick the correct language variant based on
``contact.language``. Falls back to :data:`DEFAULT_LANGUAGE` (Czech) when
the requested variant is not registered, and logs a warning so operators
can see which contacts received the fallback.

Typical usage::

    from api.services import template_registry

    payload = template_registry.render(
        "eventfest_invitation",
        contact.language,
        vocative_name="Jano",
        microsite_link="https://demo.visionvolve.com/invite/abc",
    )
    subject = payload["subject"]
    html = payload["html"]
    text = payload["text"]
    language_used = payload["language_used"]  # 'cs' | 'en' | ...
    fallback_used = payload["fallback_used"]  # True when no variant matched

Templates register themselves at import time::

    from .template_registry import register
    register("eventfest_invitation", "cs", render_eventfest_cs)
    register("eventfest_invitation", "en", render_eventfest_en)
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "cs"
"""Default language used when a requested variant does not exist or the
contact has no language set."""

SUPPORTED_LANGUAGES: tuple[str, ...] = ("cs", "en")
"""Languages the system actively supports today. Extend this tuple as
additional translations ship. Languages outside this tuple are treated
as the default language."""


_REGISTRY: dict[tuple[str, str], Callable[..., dict]] = {}


def register(template_key: str, language: str, renderer: Callable[..., dict]) -> None:
    """Register a renderer for a ``(template_key, language)`` pair.

    The renderer must return a ``dict`` with at minimum the keys
    ``subject``, ``html`` and ``text``. :func:`render` adds the
    ``language_used`` and ``fallback_used`` keys based on resolution.
    """
    if not template_key:
        raise ValueError("template_key is required")
    if not language:
        raise ValueError("language is required")
    _REGISTRY[(template_key, language.lower())] = renderer


def is_registered(template_key: str, language: str) -> bool:
    """Return True if a renderer is registered for this exact pair."""
    return (template_key, (language or "").lower()) in _REGISTRY


def registered_languages(template_key: str) -> list[str]:
    """Return all registered language codes for a given template key."""
    return sorted(lang for (key, lang) in _REGISTRY if key == template_key)


def render(template_key: str, language: str | None, **ctx) -> dict:
    """Render a template by (key, language) with graceful fallback.

    Args:
        template_key: registry key (e.g. ``"eventfest_invitation"``).
        language: requested language code (e.g. ``"en"`` or ``"cs"``).
            ``None``, empty string, or unsupported codes fall back to
            :data:`DEFAULT_LANGUAGE`.
        **ctx: forwarded to the renderer.

    Returns:
        ``dict`` from the renderer with two extra keys merged in:

        - ``language_used``: the actual language code rendered.
        - ``fallback_used``: ``True`` iff the requested variant was not
          registered and we fell back to :data:`DEFAULT_LANGUAGE`.

    Raises:
        KeyError: if no renderer is registered for ``template_key`` in
        any supported language (defensive — indicates a missing
        registration, never a normal runtime condition).
    """
    requested = (language or DEFAULT_LANGUAGE).lower()
    if requested not in SUPPORTED_LANGUAGES:
        # Unsupported language → behave like a missing variant: try the
        # requested code (it won't be registered), then fall back.
        requested_for_lookup = requested
    else:
        requested_for_lookup = requested

    renderer = _REGISTRY.get((template_key, requested_for_lookup))
    fallback = False
    language_used = requested_for_lookup

    if renderer is None:
        renderer = _REGISTRY.get((template_key, DEFAULT_LANGUAGE))
        fallback = True
        language_used = DEFAULT_LANGUAGE
        if renderer is None:
            raise KeyError(
                f"No template registered for key={template_key!r} "
                f"in any supported language. Registered keys: "
                f"{sorted({k for k, _ in _REGISTRY})}"
            )
        logger.warning(
            "template_registry fallback: key=%s requested_lang=%s -> %s",
            template_key,
            requested,
            DEFAULT_LANGUAGE,
        )

    out = renderer(**ctx)
    if not isinstance(out, dict):
        raise TypeError(
            f"template renderer for ({template_key!r}, {language_used!r}) "
            f"must return a dict, got {type(out).__name__}"
        )
    for required_key in ("subject", "html", "text"):
        if required_key not in out:
            raise KeyError(
                f"template renderer for ({template_key!r}, {language_used!r}) "
                f"missing required key {required_key!r}"
            )

    out["language_used"] = language_used
    out["fallback_used"] = fallback
    return out


def clear_registry_for_tests() -> None:
    """Test-only helper to reset the registry. Not for production use."""
    _REGISTRY.clear()
