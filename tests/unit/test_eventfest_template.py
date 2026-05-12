"""Tests for EventFest HTML email template rendering."""

from api.services.eventfest_template import (
    render_eventfest_email,
    _replace_template_variables,
    EVENTFEST_HTML_TEMPLATE,
    EVENTFEST_PLAIN_TEMPLATE,
    EVENTFEST_SUBJECT,
)


class TestReplaceTemplateVariables:
    """Unit tests for the low-level variable replacement."""

    def test_single_variable(self):
        result = _replace_template_variables("Hello {{name}}", {"name": "World"})
        assert result == "Hello World"

    def test_multiple_variables(self):
        result = _replace_template_variables(
            "{{greeting}}, {{name}}!",
            {"greeting": "Hi", "name": "Jana"},
        )
        assert result == "Hi, Jana!"

    def test_missing_variable_left_as_is(self):
        result = _replace_template_variables(
            "Hello {{name}}, visit {{link}}",
            {"name": "Jana"},
        )
        assert "Jana" in result
        assert "{{link}}" in result

    def test_empty_value_replaces_with_empty(self):
        result = _replace_template_variables("Hello {{name}}", {"name": ""})
        assert result == "Hello "

    def test_none_value_replaces_with_empty(self):
        result = _replace_template_variables("Hello {{name}}", {"name": None})
        assert result == "Hello "


class TestRenderEventfestEmail:
    """Template rendering with vocative name and microsite link."""

    def test_returns_three_tuple(self):
        result = render_eventfest_email("Jano", "https://example.com/invite/abc")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_subject_correct(self):
        subject, _, _ = render_eventfest_email("Jano", "https://example.com/invite/abc")
        assert subject == "Pozvánka na EVENT FEST | Losers Cirque Company"

    def test_basic_rendering_with_name(self):
        subject, html, plain = render_eventfest_email(
            "Jano", "https://example.com/invite/abc"
        )
        assert "Jano" in html
        assert "Jano" in plain
        assert "https://example.com/invite/abc" in html
        assert "https://example.com/invite/abc" in plain

    def test_html_is_valid_structure(self):
        _, html, _ = render_eventfest_email("Petře", "https://example.com/invite/xyz")
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "<body" in html
        assert "</body>" in html

    def test_html_has_inline_css(self):
        _, html, _ = render_eventfest_email("Evo", "https://example.com/invite/123")
        assert "style=" in html

    def test_html_max_width_600(self):
        _, html, _ = render_eventfest_email("Evo", "https://example.com/invite/123")
        assert "max-width:600px" in html

    def test_html_has_unsubscribe_link(self):
        """BL-1103: footer link is now the per-contact one-click unsubscribe URL.

        Without an explicit ``unsubscribe_url`` argument the renderer
        substitutes a mailto fallback so the footer is always actionable.
        The footer label "odhlašte se" (Czech for "unsubscribe") must
        remain in either case (case-insensitive match — the v4 template
        renders it mid-sentence with a lower-case lead, the earlier copy
        used a sentence-initial capital).
        """
        _, html, _ = render_eventfest_email("Evo", "https://example.com/invite/123")
        assert "odhl" in html.lower()  # "odhlašte se" footer label still present
        assert "unsubscribe" in html.lower()  # mailto fallback

    def test_html_uses_provided_unsubscribe_url(self):
        """An explicit unsubscribe_url is injected verbatim (BL-1103)."""
        per_contact = "https://example.com/api/unsubscribe?contact_id=X&token=Y"
        _, html, _ = render_eventfest_email(
            "Evo", "https://example.com/invite/123", unsubscribe_url=per_contact
        )
        assert per_contact in html

    def test_plain_text_has_link(self):
        _, _, plain = render_eventfest_email(
            "Martine", "https://example.com/invite/456"
        )
        assert "https://example.com/invite/456" in plain

    def test_plain_text_no_html_tags(self):
        _, _, plain = render_eventfest_email(
            "Martine", "https://example.com/invite/456"
        )
        assert "<table" not in plain
        assert "<td" not in plain
        assert "<p " not in plain

    def test_microsite_link_is_hyperlink_in_html(self):
        _, html, _ = render_eventfest_email("Jano", "https://example.com/invite/abc")
        assert 'href="https://example.com/invite/abc"' in html

    def test_nabidce_vystoupeni_is_hyperlink(self):
        _, html, _ = render_eventfest_email("Jano", "https://example.com/invite/abc")
        # The "nabídce vystoupení" text should be wrapped in <a>
        assert "nabídce vystoupení</a>" in html

    def test_email_text_content(self):
        _, html, _ = render_eventfest_email("Jano", "https://example.com/invite/abc")
        assert "EVENT FEST" in html
        assert "Hat Jazz" in html
        assert "Handstand" in html
        assert "Hanka" in html

    def test_no_unreplaced_variables(self):
        _, html, plain = render_eventfest_email(
            "Jano", "https://example.com/invite/abc"
        )
        assert "{{" not in html
        assert "}}" not in html
        assert "{{" not in plain
        assert "}}" not in plain

    def test_empty_name(self):
        subject, html, plain = render_eventfest_email("", "https://x.com/inv/1")
        # Should render without error
        assert "https://x.com/inv/1" in html
        assert subject == EVENTFEST_SUBJECT
        # "Hezký den, ," — empty name, greeting still present
        assert "Hezký den," in plain

    def test_none_name(self):
        subject, html, plain = render_eventfest_email(None, "https://x.com/inv/1")
        assert "https://x.com/inv/1" in html
        assert subject == EVENTFEST_SUBJECT

    def test_responsive_meta_viewport(self):
        _, html, _ = render_eventfest_email("Jano", "https://example.com/inv/1")
        assert "viewport" in html
        assert "width=device-width" in html


class TestTemplateIntegrity:
    """Verify the raw templates have expected placeholders."""

    def test_html_template_has_vocative_placeholder(self):
        assert "{{vocative_name}}" in EVENTFEST_HTML_TEMPLATE

    def test_html_template_has_microsite_placeholder(self):
        assert "{{microsite_link}}" in EVENTFEST_HTML_TEMPLATE

    def test_plain_template_has_vocative_placeholder(self):
        assert "{{vocative_name}}" in EVENTFEST_PLAIN_TEMPLATE

    def test_plain_template_has_microsite_placeholder(self):
        assert "{{microsite_link}}" in EVENTFEST_PLAIN_TEMPLATE


class TestFeaturedActsGrid:
    """Tests for the v4-approved hardcoded 2x2 thumbnail grid.

    The v4 template hardcodes the 4 featured acts (Complicité, Glamour in
    Red, Aerial Hoop — Armagedon, Onyx). All thumbnail cards link to
    ``{{microsite_link}}`` (partner home) rather than per-slug detail
    pages — this keeps the template simple and avoids the per-slug URL
    complexity for the 357-partner send.
    """

    # The four hardcoded thumbnail URLs — part of the v4 contract.
    EXPECTED_THUMBNAIL_URLS = (
        "https://booking.loserscirque.cz/api/media/file/01-2-768x512.jpg",
        "https://booking.loserscirque.cz/api/media/file/01-11-768x512.jpg",
        "https://booking.loserscirque.cz/api/media/file/40_1-768x512.jpg",
        "https://booking.loserscirque.cz/api/media/file/01-17-768x512.jpg",
    )
    EXPECTED_THUMBNAIL_CAPTIONS = (
        "Complicité",
        "Glamour in Red",
        "Aerial Hoop — Armagedon",
        "Onyx",
    )

    def test_hardcoded_thumbnails_render_regardless_of_featured_acts_kwarg(self):
        """Thumbnails are hardcoded — not affected by featured_acts kwarg."""
        _, html, _ = render_eventfest_email(
            "Jano",
            "https://booking.loserscirque.cz/invite/tok",
            featured_acts=[],  # Ignored by v4 template
        )
        for url in self.EXPECTED_THUMBNAIL_URLS:
            assert url in html, f"missing hardcoded thumbnail {url!r}"

    def test_none_featured_acts_still_renders_hardcoded_thumbnails(self):
        _, html, _ = render_eventfest_email(
            "Jano",
            "https://example.com/invite/tok",
            featured_acts=None,
        )
        # v4: thumbnails are hardcoded, so they render even with None
        for url in self.EXPECTED_THUMBNAIL_URLS:
            assert url in html

    def test_html_contains_four_thumbnail_images(self):
        _, html, _ = render_eventfest_email(
            "Jano", "https://booking.loserscirque.cz/invite/tok"
        )
        for url in self.EXPECTED_THUMBNAIL_URLS:
            assert url in html
        for caption in self.EXPECTED_THUMBNAIL_CAPTIONS:
            assert caption in html

    def test_thumbnail_cards_link_to_microsite_link(self):
        """All 4 thumbnail <a href> resolve to microsite_link, not detail pages."""
        _, html, _ = render_eventfest_email(
            "Jano", "https://booking.loserscirque.cz/invite/tok-abc"
        )
        # microsite_link should appear many times (logo, wordmark, 4 thumbs,
        # CTA mso, CTA non-mso, nabidce-link). At least the 4 thumb links.
        assert html.count("https://booking.loserscirque.cz/invite/tok-abc") >= 8
        # No legacy per-slug detail-page hrefs bleed through
        assert "/cs/performances/complicite?t=" not in html
        assert "/cs/animations/glamour-in-red?t=" not in html

    def test_plain_text_lists_all_four_acts(self):
        _, _, plain = render_eventfest_email(
            "Jano", "https://booking.loserscirque.cz/invite/tok"
        )
        for caption in self.EXPECTED_THUMBNAIL_CAPTIONS:
            assert caption in plain

    def test_plain_text_no_html_tags_in_acts(self):
        _, _, plain = render_eventfest_email(
            "Jano", "https://booking.loserscirque.cz/invite/tok"
        )
        assert "<img" not in plain
        assert "<a " not in plain
        assert "<table" not in plain

    def test_backwards_compat_no_featured_acts_kwarg(self):
        """Existing callers that pass only (name, microsite_link) still work."""
        subject, html, plain = render_eventfest_email(
            "Jano", "https://example.com/invite/tok"
        )
        assert subject == EVENTFEST_SUBJECT
        assert "{{" not in html
        assert "}}" not in html
        assert "{{" not in plain
        assert "}}" not in plain

    def test_backwards_compat_recipient_token_and_site_url_accepted(self):
        """Legacy callers that pass recipient_token/site_url don't crash."""
        subject, html, _ = render_eventfest_email(
            "Jano",
            "https://booking.loserscirque.cz/invite/tok",
            recipient_token="abc123",
            site_url="https://booking.loserscirque.cz",
            featured_acts=[
                {
                    "name": "ignored",
                    "slug": "ignored",
                    "image_url": "https://x/ignored.jpg",
                }
            ],
        )
        # v4 template ignores these — hardcoded thumbs still present
        assert subject == EVENTFEST_SUBJECT
        assert "ignored" not in html


class TestV4BrandContract:
    """Tests that pin down the v4-approved visual/brand contract.

    These two tests are the canary for the rich template — if they fail
    we're rendering the plain minimal template again.
    """

    def test_eventfest_template_contains_logo_and_wordmark(self):
        """Rendered HTML must contain the circular logo + LOSERS CIRQUE wordmark."""
        _, html, _ = render_eventfest_email(
            "Jano", "https://booking.loserscirque.cz/invite/tok"
        )
        assert (
            "https://booking.loserscirque.cz/images/lcc-logo-2025.png" in html
        ), "logo image URL missing"
        assert "LOSERS" in html, "LOSERS wordmark missing"
        assert "CIRQUE" in html, "CIRQUE wordmark missing"
        # Deep blue header band colour present
        assert "#0A0066" in html, "deep-blue brand colour missing"
        # Red accent present
        assert "#FF0000" in html, "red accent/CTA colour missing"

    def test_eventfest_template_contains_4_thumbnails(self):
        """Rendered HTML must contain all 4 hardcoded thumbnail URLs."""
        _, html, _ = render_eventfest_email(
            "Jano", "https://booking.loserscirque.cz/invite/tok"
        )
        required = (
            "https://booking.loserscirque.cz/api/media/file/01-2-768x512.jpg",
            "https://booking.loserscirque.cz/api/media/file/01-11-768x512.jpg",
            "https://booking.loserscirque.cz/api/media/file/40_1-768x512.jpg",
            "https://booking.loserscirque.cz/api/media/file/01-17-768x512.jpg",
        )
        for url in required:
            assert url in html, f"missing thumbnail URL {url!r}"
        # CTA button text
        assert "Prohlédněte si celou nabídku" in html

    def test_eventfest_template_contains_signature_block(self):
        """Signature block with Hana's contact details is present."""
        _, html, _ = render_eventfest_email(
            "Jano", "https://booking.loserscirque.cz/invite/tok"
        )
        assert "Hana Faková" in html
        assert "Event Producer" in html
        assert "+420 737 853 490" in html
        assert "hana@unitedarts.cz" in html
        # Round-2: the 3 URL footer collapsed to a single booking.loserscirque.cz
        # display whose href is {{microsite_link}}.
        assert "booking.loserscirque.cz" in html
        assert "www.unitedarts.cz" not in html
        assert "www.divadlobravo.cz" not in html


# NOTE: tests for get_or_create_invite moved to tests/unit/test_microsite_invites.py
# as part of the switch from POST /api/invites (singular) to POST /api/invites/bulk
# with applyEventFestDefaults.  Keeping them in this file would assert on the old
# singular response shape and fail.

# ---------------------------------------------------------------------------
# Tone (vykání / tykání) per-contact switching — EventFest list has 351
# vykat recipients and 6 tykat recipients; the template must render both.
# ---------------------------------------------------------------------------


class TestEventfestTone:
    """Render both vykání (default) and tykání variants of the EventFest body."""

    # Strings that MUST appear only when tone == vykat.
    VYKAT_FRAGMENTS = (
        "pro Vás",
        "na Vás",
        "hledáte",
        "můžete",
        "Zastavte se",
    )
    # Strings that MUST appear only when tone == tykat.
    TYKAT_FRAGMENTS = (
        "pro Tebe",
        "na Tebe",
        "hledáš",
        "můžeš",
        "Zastav se",
    )

    def test_eventfest_template_default_vykani_pronouns(self):
        """Default tone renders all formal pronouns/verbs (backwards-compat)."""
        _, html, plain = render_eventfest_email(
            "Jano", "https://example.com/invite/abc"
        )
        for fragment in self.VYKAT_FRAGMENTS:
            assert fragment in html, f"missing {fragment!r} in HTML (default vykat)"
            assert fragment in plain, f"missing {fragment!r} in plain (default vykat)"
        # No leaked tykání forms.
        for fragment in self.TYKAT_FRAGMENTS:
            assert fragment not in html, f"leaked {fragment!r} in HTML (default vykat)"
            assert fragment not in plain, f"leaked {fragment!r} in plain (default vykat)"
        # No unsubstituted placeholders.
        assert "{{" not in html
        assert "{{" not in plain

    def test_eventfest_template_explicit_vykat_pronouns(self):
        """Explicit tone='vykat' matches the default."""
        _, html, _ = render_eventfest_email(
            "Jano", "https://example.com/invite/abc", tone="vykat"
        )
        for fragment in self.VYKAT_FRAGMENTS:
            assert fragment in html

    def test_eventfest_template_explicit_tykani_pronouns(self):
        """tone='tykat' renders all informal pronouns/verbs; no vykání leaks."""
        _, html, plain = render_eventfest_email(
            "Jano", "https://example.com/invite/abc", tone="tykat"
        )
        for fragment in self.TYKAT_FRAGMENTS:
            assert fragment in html, f"missing {fragment!r} in HTML (tykat)"
            assert fragment in plain, f"missing {fragment!r} in plain (tykat)"
        for fragment in self.VYKAT_FRAGMENTS:
            assert fragment not in html, f"leaked {fragment!r} in HTML (tykat)"
            assert fragment not in plain, f"leaked {fragment!r} in plain (tykat)"
        assert "{{" not in html
        assert "{{" not in plain

    def test_eventfest_template_tykani_with_michal_vocative(self):
        """tone=tykat + Michal → vocative unchanged, pronouns informal."""
        _, html, plain = render_eventfest_email(
            "Michale", "https://example.com/invite/abc", tone="tykat"
        )
        # Vocative form is provided by caller; it doesn't depend on tone.
        assert "Michale" in html
        assert "Michale" in plain
        # Tykání pronouns present.
        assert "pro Tebe" in html
        assert "na Tebe" in html
        # Vykání pronouns absent.
        assert "pro Vás" not in html
        assert "na Vás" not in html

    def test_eventfest_template_tykani_with_hana_vocative(self):
        """tone=tykat + Hano → vocative unchanged, pronouns informal."""
        _, html, plain = render_eventfest_email(
            "Hano", "https://example.com/invite/abc", tone="tykat"
        )
        assert "Hano" in html
        assert "Hano" in plain
        assert "pro Tebe" in html
        assert "Zastav se" in plain
        assert "pro Vás" not in html
        assert "Zastavte se" not in plain

    def test_unknown_tone_falls_back_to_vykat(self):
        """Unrecognised tone string defaults to formal register."""
        _, html, _ = render_eventfest_email(
            "Jano", "https://example.com/invite/abc", tone="onikáni"
        )
        for fragment in self.VYKAT_FRAGMENTS:
            assert fragment in html
        for fragment in self.TYKAT_FRAGMENTS:
            assert fragment not in html

    def test_none_tone_falls_back_to_vykat(self):
        """Passing None for tone defaults to formal register."""
        # render_eventfest_email(tone=None) — the helper tolerates None via
        # tone_variables() even though the annotation says str.
        _, html, _ = render_eventfest_email(
            "Jano", "https://example.com/invite/abc", tone=None  # type: ignore[arg-type]
        )
        for fragment in self.VYKAT_FRAGMENTS:
            assert fragment in html

    def test_tone_variants_map_has_matching_placeholders(self):
        """Both tone dicts expose the same keys (no register-specific leaks)."""
        from api.services.eventfest_template import _TONE_VARIANTS

        assert set(_TONE_VARIANTS["vykat"]) == set(_TONE_VARIANTS["tykat"])
        # And those keys are exactly the placeholders the template references.
        assert set(_TONE_VARIANTS["vykat"]) == {
            "you_acc",
            "you_look_verb",
            "you_can_verb",
            "stop_by_imper",
        }


class TestSendServiceToneFromContact:
    """send_service._build_template_variables reads contact.address_style."""

    def _fake_contact(self, first_name: str = "Michal", address_style: str | None = "vykat"):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=None,
            tenant_id=None,
            first_name=first_name,
            last_name="",
            email_address="x@example.com",
            address_style=address_style,
        )

    def _fake_cc(self, token: str = "tok-1"):
        from types import SimpleNamespace

        return SimpleNamespace(id=None, microsite_partner_token=token)

    def _fake_campaign(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=None, generation_config={"template_type": "eventfest"}
        )

    def test_send_service_picks_tone_from_contact_address_style(self):
        """address_style='tykat' → variables carry tykání pronouns."""
        import os
        from unittest.mock import patch

        from api.services.send_service import _build_template_variables

        with patch.dict(
            os.environ,
            {"UA_MICROSITE_URL": "", "UA_INVITE_API_KEY": ""},
            clear=False,
        ):
            variables = _build_template_variables(
                self._fake_contact("Michal", address_style="tykat"),
                self._fake_cc(),
                self._fake_campaign(),
            )

        assert variables["you_acc"] == "Tebe"
        assert variables["you_look_verb"] == "hledáš"
        assert variables["you_can_verb"] == "můžeš"
        assert variables["stop_by_imper"] == "Zastav se"

    def test_send_service_picks_vykat_for_explicit_vykat(self):
        """address_style='vykat' → variables carry vykání pronouns."""
        import os
        from unittest.mock import patch

        from api.services.send_service import _build_template_variables

        with patch.dict(
            os.environ,
            {"UA_MICROSITE_URL": "", "UA_INVITE_API_KEY": ""},
            clear=False,
        ):
            variables = _build_template_variables(
                self._fake_contact("Michal", address_style="vykat"),
                self._fake_cc(),
                self._fake_campaign(),
            )

        assert variables["you_acc"] == "Vás"
        assert variables["you_look_verb"] == "hledáte"
        assert variables["you_can_verb"] == "můžete"
        assert variables["stop_by_imper"] == "Zastavte se"

    def test_send_service_defaults_to_vykani_for_null_address_style(self):
        """address_style=None → defensive fallback to vykání."""
        import os
        from unittest.mock import patch

        from api.services.send_service import _build_template_variables

        with patch.dict(
            os.environ,
            {"UA_MICROSITE_URL": "", "UA_INVITE_API_KEY": ""},
            clear=False,
        ):
            variables = _build_template_variables(
                self._fake_contact("Michal", address_style=None),
                self._fake_cc(),
                self._fake_campaign(),
            )

        assert variables["you_acc"] == "Vás"
        assert variables["you_can_verb"] == "můžete"

    def test_send_service_defaults_to_vykani_for_empty_address_style(self):
        """address_style='' → defensive fallback to vykání (like NULL)."""
        import os
        from unittest.mock import patch

        from api.services.send_service import _build_template_variables

        with patch.dict(
            os.environ,
            {"UA_MICROSITE_URL": "", "UA_INVITE_API_KEY": ""},
            clear=False,
        ):
            variables = _build_template_variables(
                self._fake_contact("Michal", address_style=""),
                self._fake_cc(),
                self._fake_campaign(),
            )

        assert variables["you_acc"] == "Vás"

    def test_send_service_tone_only_populated_for_eventfest(self):
        """Other template types don't get the tone variables."""
        import os
        from types import SimpleNamespace
        from unittest.mock import patch

        from api.services.send_service import _build_template_variables

        other_campaign = SimpleNamespace(
            generation_config={"template_type": "meetup"}
        )
        with patch.dict(os.environ, {}, clear=False):
            variables = _build_template_variables(
                self._fake_contact("Michal", address_style="tykat"),
                self._fake_cc(),
                other_campaign,
            )

        # Tone placeholders should be absent — only eventfest wires them.
        assert "you_acc" not in variables
        assert "you_can_verb" not in variables

    def test_end_to_end_tykat_contact_renders_informal_body(self):
        """Full pipeline: tykat contact → stored body → per-recipient render.

        Mirrors the stored-body-plus-send-time-substitution pattern used in
        production: provisioner stores body with placeholders intact, send
        service populates per-contact variables, _replace_template_variables
        produces the final body shipped to Resend.
        """
        import os
        from unittest.mock import patch

        from api.services.eventfest_campaign import _render_storable_body
        from api.services.send_service import (
            _build_template_variables,
            _replace_template_variables,
        )

        # Step 1 — provision: body stored with placeholders.
        stored_html, stored_plain = _render_storable_body(
            featured_acts=None, site_url="https://booking.loserscirque.cz"
        )
        assert "{{you_acc}}" in stored_html
        assert "{{you_can_verb}}" in stored_html

        # Step 2 — send time: build variables for a tykat contact.
        with patch.dict(
            os.environ,
            {"UA_MICROSITE_URL": "", "UA_INVITE_API_KEY": ""},
            clear=False,
        ):
            variables = _build_template_variables(
                self._fake_contact("Michale", address_style="tykat"),
                self._fake_cc(),
                self._fake_campaign(),
            )

        # Step 3 — substitute per-recipient.
        final_html = _replace_template_variables(stored_html, variables)
        final_plain = _replace_template_variables(stored_plain, variables)

        # All placeholders resolved.
        assert "{{" not in final_html
        assert "{{" not in final_plain
        # Tykání forms present, vykání absent.
        assert "pro Tebe" in final_html
        assert "hledáš" in final_html
        assert "Zastav se" in final_plain
        assert "pro Vás" not in final_html
        assert "hledáte" not in final_html
        assert "Zastavte se" not in final_plain


class TestHankaRound2Revisions:
    """Tests that pin down Hanka's round-2 copy revisions.

    Covers the 6 changes: EVENT FESTu genitive, bullet lines for
    Hat Jazz/Handstand, "ve vstupní hale" stánek phrasing,
    představení→vystoupení, thumbnail reorder, single booking URL.
    """

    def test_event_festu_genitive(self):
        """Template renders 'v rámci EVENT FESTu' (genitive), not 'akce EVENT FEST'."""
        _, html, plain = render_eventfest_email(
            "Jano", "https://example.com/invite/tok"
        )
        assert "EVENT FESTu" in html, "missing genitive EVENT FESTu in HTML"
        assert "EVENT FESTu" in plain, "missing genitive EVENT FESTu in plain"
        # The old "akce EVENT FEST" wording must be gone.
        assert "akce EVENT FEST" not in html
        assert "akce EVENT FEST" not in plain

    def test_stanek_ve_vstupni_hale(self):
        """'ve vstupní hale' qualifies the stánek invitation in both registers."""
        _, html_v, plain_v = render_eventfest_email(
            "Jano", "https://example.com/invite/tok", tone="vykat"
        )
        _, html_t, plain_t = render_eventfest_email(
            "Jano", "https://example.com/invite/tok", tone="tykat"
        )
        for body in (html_v, plain_v, html_t, plain_t):
            assert "ve vstupní hale" in body, "missing 've vstupní hale' qualifier"
        # Vykat: "Zastavte se i na našem stánku ve vstupní hale"
        assert "Zastavte se i" in html_v and "stánku ve vstupní hale" in html_v
        # Tykat: "Zastav se i na našem stánku ve vstupní hale"
        assert "Zastav se i" in html_t and "stánku ve vstupní hale" in html_t

    def test_thumbnail_order_complicite_onyx_aerial_glamour(self):
        """HTML thumbnails render in order: complicite, onyx, aerial, glamour."""
        _, html, _ = render_eventfest_email(
            "Jano", "https://booking.loserscirque.cz/invite/tok"
        )
        pos_complicite = html.find("01-2-768x512")
        pos_onyx = html.find("01-17-768x512")
        pos_aerial = html.find("40_1-768x512")
        pos_glamour = html.find("01-11-768x512")
        assert -1 not in (pos_complicite, pos_onyx, pos_aerial, pos_glamour), (
            "one or more thumbnail URLs missing"
        )
        assert pos_complicite < pos_onyx < pos_aerial < pos_glamour, (
            f"thumbnail order wrong: complicite={pos_complicite} "
            f"onyx={pos_onyx} aerial={pos_aerial} glamour={pos_glamour}"
        )
