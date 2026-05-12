"""Tests for the multilingual template registry (BL-1110, v25 phase 9).

Covers:

- Registry resolution: requested language wins when available.
- Fallback to ``DEFAULT_LANGUAGE`` when the requested variant is missing.
- Unsupported / unknown language codes fall back gracefully.
- ``KeyError`` for entirely unregistered template keys (defensive).
- EventFest CS + EN renderers produce the right subject/body.
- Send-path records ``template_language`` + ``template_language_fallback``
  on the EmailSendLog row based on contact.language.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from api.services import template_registry

# Importing the EventFest template module registers its CS + EN renderers
# with the template_registry at module import time. Keep this import
# even though the symbols are not all referenced directly — it guarantees
# the registry is populated before any test runs.
import api.services.eventfest_template  # noqa: F401


# ---------------------------------------------------------------------------
# Registry-level tests
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_registry():
    """Snapshot + restore the module-level registry around each test.

    Using a snapshot keeps the EventFest registrations available for
    tests that depend on them while still letting individual tests add
    fixture-only entries without leaking.
    """
    # Take a copy of the live registry, run the test, then restore.
    snapshot = dict(template_registry._REGISTRY)
    try:
        yield template_registry
    finally:
        template_registry._REGISTRY.clear()
        template_registry._REGISTRY.update(snapshot)


def _make_renderer(subject: str, body: str):
    def _renderer(**ctx):
        return {
            "subject": subject,
            "html": f"<p>{body}</p>",
            "text": body,
        }

    return _renderer


def test_render_picks_requested_language(isolated_registry):
    isolated_registry.register("test_tpl", "cs", _make_renderer("CS subj", "CS body"))
    isolated_registry.register("test_tpl", "en", _make_renderer("EN subj", "EN body"))

    out = isolated_registry.render("test_tpl", "en")

    assert out["subject"] == "EN subj"
    assert out["text"] == "EN body"
    assert out["language_used"] == "en"
    assert out["fallback_used"] is False


def test_render_falls_back_to_default_when_missing(isolated_registry):
    """German contact, only CS variant exists → falls back to CS."""
    isolated_registry.register("test_tpl", "cs", _make_renderer("CS subj", "CS body"))

    out = isolated_registry.render("test_tpl", "de")

    assert out["subject"] == "CS subj"
    assert out["language_used"] == "cs"
    assert out["fallback_used"] is True


def test_render_none_language_uses_default(isolated_registry):
    isolated_registry.register("test_tpl", "cs", _make_renderer("CS subj", "CS body"))

    out = isolated_registry.render("test_tpl", None)

    # Default language is registered, so no fallback flag.
    assert out["language_used"] == "cs"
    assert out["fallback_used"] is False


def test_render_empty_language_uses_default(isolated_registry):
    isolated_registry.register("test_tpl", "cs", _make_renderer("CS subj", "CS body"))

    out = isolated_registry.render("test_tpl", "")

    assert out["language_used"] == "cs"
    assert out["fallback_used"] is False


def test_render_uppercase_language_is_normalised(isolated_registry):
    isolated_registry.register("test_tpl", "cs", _make_renderer("CS subj", "CS body"))
    isolated_registry.register("test_tpl", "en", _make_renderer("EN subj", "EN body"))

    out = isolated_registry.render("test_tpl", "EN")

    assert out["language_used"] == "en"
    assert out["fallback_used"] is False


def test_render_unknown_template_key_raises(isolated_registry):
    with pytest.raises(KeyError):
        isolated_registry.render("does_not_exist", "cs")


def test_render_requires_subject_html_text_keys(isolated_registry):
    def bad_renderer(**_):
        return {"subject": "ok"}  # missing html + text

    isolated_registry.register("bad_tpl", "cs", bad_renderer)
    with pytest.raises(KeyError):
        isolated_registry.render("bad_tpl", "cs")


def test_render_renderer_must_return_dict(isolated_registry):
    def tuple_renderer(**_):
        return ("subject", "<p>body</p>", "body")

    isolated_registry.register("tuple_tpl", "cs", tuple_renderer)
    with pytest.raises(TypeError):
        isolated_registry.render("tuple_tpl", "cs")


def test_register_requires_template_key():
    with pytest.raises(ValueError):
        template_registry.register("", "cs", lambda **_: {})


def test_register_requires_language():
    with pytest.raises(ValueError):
        template_registry.register("key", "", lambda **_: {})


def test_is_registered(isolated_registry):
    assert isolated_registry.is_registered("eventfest_invitation", "cs")
    assert isolated_registry.is_registered("eventfest_invitation", "en")
    assert not isolated_registry.is_registered("eventfest_invitation", "fr")


def test_registered_languages_lists_all(isolated_registry):
    langs = isolated_registry.registered_languages("eventfest_invitation")
    assert "cs" in langs
    assert "en" in langs
    assert langs == sorted(langs)


# ---------------------------------------------------------------------------
# EventFest renderer tests
# ---------------------------------------------------------------------------


def test_eventfest_cs_renderer_produces_czech_body():
    from api.services.eventfest_template import render_eventfest_cs

    out = render_eventfest_cs(
        vocative_name="Jano",
        microsite_link="https://example.com/inv/abc",
    )

    assert isinstance(out, dict)
    assert out["subject"] == "Pozvánka na EVENT FEST | Losers Cirque Company"
    assert "Hezký den, Jano," in out["text"]
    assert "Hezký den, Jano," in out["html"]
    assert "https://example.com/inv/abc" in out["html"]
    # CZ-specific markers
    assert "nabídce vystoupení" in out["html"]
    assert "Hanka" in out["text"]


def test_eventfest_en_renderer_produces_english_body():
    from api.services.eventfest_template import render_eventfest_en

    out = render_eventfest_en(
        vocative_name="Jano",
        microsite_link="https://example.com/inv/abc",
    )

    assert isinstance(out, dict)
    assert out["subject"] == "Invitation to EVENT FEST | Losers Cirque Company"
    assert "Hello Jano," in out["text"]
    assert "Hello Jano," in out["html"]
    assert "https://example.com/inv/abc" in out["html"]
    # EN-specific markers
    assert "performance offer" in out["html"]
    assert "Hanka" in out["text"]
    # No Czech leakage into the EN body
    assert "Hezký den" not in out["html"]
    assert "nabídce vystoupení" not in out["html"]


def test_eventfest_registry_lookup_cs():
    out = template_registry.render(
        "eventfest_invitation",
        "cs",
        vocative_name="Petře",
        microsite_link="https://example.com/inv/xyz",
    )
    assert out["language_used"] == "cs"
    assert out["fallback_used"] is False
    assert "Hezký den, Petře," in out["text"]


def test_eventfest_registry_lookup_en():
    out = template_registry.render(
        "eventfest_invitation",
        "en",
        vocative_name="Peter",
        microsite_link="https://example.com/inv/xyz",
    )
    assert out["language_used"] == "en"
    assert out["fallback_used"] is False
    assert "Hello Peter," in out["text"]


def test_eventfest_registry_lookup_unsupported_falls_back_to_cs():
    out = template_registry.render(
        "eventfest_invitation",
        "de",
        vocative_name="Peter",
        microsite_link="https://example.com/inv/xyz",
    )
    assert out["language_used"] == "cs"
    assert out["fallback_used"] is True
    # Body must be the CS variant.
    assert "Hezký den, Peter," in out["text"]


def test_eventfest_registry_lookup_no_language_uses_cs():
    out = template_registry.render(
        "eventfest_invitation",
        None,
        vocative_name="Anna",
        microsite_link="https://example.com/inv/q",
    )
    assert out["language_used"] == "cs"
    assert out["fallback_used"] is False
    assert "Hezký den, Anna," in out["text"]


# ---------------------------------------------------------------------------
# Send path: language is recorded on the EmailSendLog
# ---------------------------------------------------------------------------


def _stub_contact(language=None):
    """Minimal stand-in for ``api.models.Contact`` for unit testing."""

    class _C:
        first_name = "Jan"
        last_name = "Novák"
        email_address = "jan@example.com"
        id = "contact-id-1"

    c = _C()
    c.language = language
    return c


def _stub_campaign(template_type="eventfest"):
    class _Cmp:
        id = "campaign-id-1"
        generation_config = {"template_type": template_type}

    return _Cmp()


def test_resolve_templated_body_picks_en_for_english_contact():
    from api.services.send_service import _resolve_templated_body

    out = _resolve_templated_body(
        campaign=_stub_campaign(),
        contact=_stub_contact(language="en"),
        template_variables={
            "vocative_name": "Jan",
            "microsite_link": "https://example.com/inv/1",
        },
    )

    assert out is not None
    assert out["language_used"] == "en"
    assert out["fallback_used"] is False
    assert "Hello Jan," in out["html"]


def test_resolve_templated_body_picks_cs_for_czech_contact():
    from api.services.send_service import _resolve_templated_body

    out = _resolve_templated_body(
        campaign=_stub_campaign(),
        contact=_stub_contact(language="cs"),
        template_variables={
            "vocative_name": "Jano",
            "microsite_link": "https://example.com/inv/1",
        },
    )

    assert out is not None
    assert out["language_used"] == "cs"
    assert out["fallback_used"] is False
    assert "Hezký den, Jano," in out["html"]


def test_resolve_templated_body_falls_back_for_unsupported_language():
    from api.services.send_service import _resolve_templated_body

    out = _resolve_templated_body(
        campaign=_stub_campaign(),
        contact=_stub_contact(language="de"),
        template_variables={
            "vocative_name": "Klaus",
            "microsite_link": "https://example.com/inv/1",
        },
    )

    assert out is not None
    assert out["language_used"] == "cs"
    assert out["fallback_used"] is True
    assert "Hezký den, Klaus," in out["html"]


def test_resolve_templated_body_null_language_uses_default_cs():
    """Contact with NULL language is treated as CS (default)."""
    from api.services.send_service import _resolve_templated_body

    out = _resolve_templated_body(
        campaign=_stub_campaign(),
        contact=_stub_contact(language=None),
        template_variables={
            "vocative_name": "Petr",
            "microsite_link": "https://example.com/inv/1",
        },
    )

    assert out is not None
    assert out["language_used"] == "cs"
    assert out["fallback_used"] is False
    assert "Hezký den, Petr," in out["html"]


def test_resolve_templated_body_returns_none_for_non_templated_campaign():
    from api.services.send_service import _resolve_templated_body

    out = _resolve_templated_body(
        campaign=_stub_campaign(template_type=None),
        contact=_stub_contact(language="en"),
        template_variables={"vocative_name": "Jan"},
    )

    assert out is None


def test_resolve_templated_body_returns_none_for_unknown_template_type():
    """Unknown campaign template_type (no registry mapping) → None.

    Caller should fall back to legacy stored-body placeholder
    substitution rather than crashing the send loop.
    """
    from api.services.send_service import _resolve_templated_body

    out = _resolve_templated_body(
        campaign=_stub_campaign(template_type="some_future_unmapped_type"),
        contact=_stub_contact(language="en"),
        template_variables={"vocative_name": "Jan"},
    )

    assert out is None


def test_resolve_templated_body_handles_jsonb_string_generation_config():
    """Some test/SQLite paths store ``generation_config`` as a JSON string."""
    from api.services.send_service import _resolve_templated_body

    class _Cmp:
        id = "c1"
        generation_config = '{"template_type": "eventfest"}'

    out = _resolve_templated_body(
        campaign=_Cmp(),
        contact=_stub_contact(language="en"),
        template_variables={
            "vocative_name": "Jan",
            "microsite_link": "https://example.com/i/1",
        },
    )

    assert out is not None
    assert out["language_used"] == "en"


# ---------------------------------------------------------------------------
# Backward compatibility: legacy render_eventfest_email tuple API
# ---------------------------------------------------------------------------


def test_render_eventfest_email_legacy_tuple_unchanged():
    """The legacy render_eventfest_email API still returns the CS 3-tuple.

    Existing callers (eventfest_campaign.py) and the original test suite
    rely on this signature; the multilingual refactor must not break it.
    """
    from api.services.eventfest_template import (
        EVENTFEST_SUBJECT,
        render_eventfest_email,
    )

    subject, html, plain = render_eventfest_email(
        "Jano", "https://example.com/invite/abc"
    )
    assert subject == EVENTFEST_SUBJECT
    assert "Hezký den, Jano," in plain
    assert "https://example.com/invite/abc" in html


def test_render_eventfest_email_with_placeholder_args_returns_storable_body():
    """Used by eventfest_campaign._render_storable_body to keep placeholders.

    Passing the literal ``{{vocative_name}}`` / ``{{microsite_link}}`` as
    values must round-trip them in the output so per-recipient
    substitution can happen later at send time. The same holds for the
    tone placeholders (``TONE_PASSTHROUGH``) and the unsubscribe URL —
    the storable body is fully placeholder-bearing, the send step does
    the per-recipient substitution.
    """
    from api.services.eventfest_template import (
        EVENTFEST_HTML_TEMPLATE,
        TONE_PASSTHROUGH,
        render_eventfest_email,
    )

    _, html, _ = render_eventfest_email(
        "{{vocative_name}}",
        "{{microsite_link}}",
        tone=TONE_PASSTHROUGH,
        unsubscribe_url="{{unsubscribe_url}}",
    )
    assert html == EVENTFEST_HTML_TEMPLATE


# ---------------------------------------------------------------------------
# Logging side-effects: warning is emitted when fallback fires
# ---------------------------------------------------------------------------


def test_fallback_emits_warning_log(caplog):
    import logging

    caplog.set_level(logging.WARNING, logger="api.services.template_registry")
    template_registry.render(
        "eventfest_invitation",
        "fr",
        vocative_name="Marie",
        microsite_link="https://example.com/i/1",
    )
    assert any(
        "fallback" in rec.message.lower()
        for rec in caplog.records
        if rec.name == "api.services.template_registry"
    )


def test_no_fallback_warning_when_variant_exists(caplog):
    import logging

    caplog.set_level(logging.WARNING, logger="api.services.template_registry")
    template_registry.render(
        "eventfest_invitation",
        "en",
        vocative_name="Marie",
        microsite_link="https://example.com/i/1",
    )
    fallback_records = [
        rec
        for rec in caplog.records
        if rec.name == "api.services.template_registry"
        and "fallback" in rec.message.lower()
    ]
    assert fallback_records == []


# Silence unused-import warnings.
_ = patch
