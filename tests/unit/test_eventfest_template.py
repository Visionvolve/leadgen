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
        _, html, _ = render_eventfest_email("Evo", "https://example.com/invite/123")
        assert "unsubscribe" in html.lower()
        assert "hana@unitedarts.cz" in html

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
    """Tests for the 2x2 thumbnail grid section."""

    SAMPLE_ACTS = [
        {
            "name": "Complicité",
            "slug": "complicite",
            "image_url": "https://booking.loserscirque.cz/api/media/file/complicite-01.jpg",
            "category": "performances",
        },
        {
            "name": "Glamour in Red",
            "slug": "glamour-in-red",
            "image_url": "https://booking.loserscirque.cz/api/media/file/glamour-01.jpg",
            "category": "animations",
        },
        {
            "name": "Onyx",
            "slug": "onyx",
            "image_url": "https://booking.loserscirque.cz/api/media/file/onyx-01.jpg",
            "category": "performances",
        },
    ]

    def test_empty_featured_acts_renders_without_thumbnail_section(self):
        """If featured_acts=[], no empty table/placeholder leaks into output."""
        _, html, plain = render_eventfest_email(
            "Jano",
            "https://booking.loserscirque.cz/invite/tok",
            recipient_token="tok",
            site_url="https://booking.loserscirque.cz",
            featured_acts=[],
        )
        assert "{{featured_acts_section}}" not in html
        assert "{{featured_acts_plain}}" not in plain
        # No placeholder <img> or grid table should appear
        assert "/cs/performances/" not in html
        assert "/cs/animations/" not in html
        # Plain text should not contain the acts header
        assert "Vybraná vystoupení" not in plain

    def test_none_featured_acts_renders_without_thumbnail_section(self):
        _, html, _ = render_eventfest_email(
            "Jano",
            "https://example.com/invite/tok",
            recipient_token="tok",
            site_url="https://booking.loserscirque.cz",
            featured_acts=None,
        )
        assert "{{featured_acts_section}}" not in html
        assert "/cs/performances/" not in html

    def test_html_contains_img_for_each_act(self):
        _, html, _ = render_eventfest_email(
            "Jano",
            "https://example.com/invite/tok",
            recipient_token="abc123",
            site_url="https://booking.loserscirque.cz",
            featured_acts=self.SAMPLE_ACTS,
        )
        # One <img> per entry
        assert html.count("<img ") == len(self.SAMPLE_ACTS)
        # Each image URL appears
        for act in self.SAMPLE_ACTS:
            assert act["image_url"] in html
        # Each act name appears as caption
        for act in self.SAMPLE_ACTS:
            assert act["name"] in html

    def test_each_link_contains_recipient_token_query_param(self):
        _, html, _ = render_eventfest_email(
            "Jano",
            "https://example.com/invite/tok",
            recipient_token="abc123",
            site_url="https://booking.loserscirque.cz",
            featured_acts=self.SAMPLE_ACTS,
        )
        # Count hrefs that include the token query param
        token_href_count = html.count("?t=abc123")
        assert token_href_count == len(self.SAMPLE_ACTS)

    def test_links_point_to_detail_pages_not_invite_route(self):
        _, html, _ = render_eventfest_email(
            "Jano",
            "https://example.com/invite/tok",
            recipient_token="abc123",
            site_url="https://booking.loserscirque.cz",
            featured_acts=self.SAMPLE_ACTS,
        )
        # Detail page URLs, not /invite/{token} — the ?t mechanism is
        # additive on the detail page.
        assert (
            'href="https://booking.loserscirque.cz/cs/performances/complicite?t=abc123"'
            in html
        )
        assert (
            'href="https://booking.loserscirque.cz/cs/animations/glamour-in-red?t=abc123"'
            in html
        )
        assert (
            'href="https://booking.loserscirque.cz/cs/performances/onyx?t=abc123"'
            in html
        )

    def test_site_url_trailing_slash_is_normalised(self):
        _, html, _ = render_eventfest_email(
            "Jano",
            "https://example.com/invite/tok",
            recipient_token="xyz",
            site_url="https://booking.loserscirque.cz/",
            featured_acts=[self.SAMPLE_ACTS[0]],
        )
        # No double slash in the constructed URL
        assert "cz//cs/performances" not in html
        assert (
            "https://booking.loserscirque.cz/cs/performances/complicite?t=xyz"
            in html
        )

    def test_caps_at_four_acts(self):
        five_acts = self.SAMPLE_ACTS + [
            {
                "name": "Aerial silk Armagedon",
                "slug": "aerial-silk-armagedon",
                "image_url": "https://x/a.jpg",
                "category": "performances",
            },
            {
                "name": "Fifth Act",
                "slug": "fifth",
                "image_url": "https://x/5.jpg",
                "category": "performances",
            },
        ]
        _, html, _ = render_eventfest_email(
            "Jano",
            "https://example.com/invite/tok",
            recipient_token="tok",
            site_url="https://booking.loserscirque.cz",
            featured_acts=five_acts,
        )
        assert html.count("<img ") == 4
        assert "Fifth Act" not in html

    def test_plain_text_lists_acts_with_urls(self):
        _, _, plain = render_eventfest_email(
            "Jano",
            "https://example.com/invite/tok",
            recipient_token="abc123",
            site_url="https://booking.loserscirque.cz",
            featured_acts=self.SAMPLE_ACTS,
        )
        assert "Vybraná vystoupení" in plain
        for act in self.SAMPLE_ACTS:
            # Each name appears in the bullet list
            assert f"- {act['name']}:" in plain
        # Each URL appears with the token
        assert (
            "https://booking.loserscirque.cz/cs/performances/complicite?t=abc123"
            in plain
        )
        assert (
            "https://booking.loserscirque.cz/cs/animations/glamour-in-red?t=abc123"
            in plain
        )

    def test_plain_text_no_html_tags_in_acts(self):
        _, _, plain = render_eventfest_email(
            "Jano",
            "https://example.com/invite/tok",
            recipient_token="abc123",
            site_url="https://booking.loserscirque.cz",
            featured_acts=self.SAMPLE_ACTS,
        )
        assert "<img" not in plain
        assert "<a " not in plain
        assert "<table" not in plain

    def test_default_category_is_performances(self):
        """If caller omits 'category', default to performances."""
        acts = [
            {
                "name": "Onyx",
                "slug": "onyx",
                "image_url": "https://x.jpg",
            }
        ]
        _, html, _ = render_eventfest_email(
            "Jano",
            "https://example.com/invite/tok",
            recipient_token="t",
            site_url="https://booking.loserscirque.cz",
            featured_acts=acts,
        )
        assert "/cs/performances/onyx?t=t" in html

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
            first_name=first_name,
            last_name="",
            email_address="x@example.com",
            address_style=address_style,
        )

    def _fake_cc(self, token: str = "tok-1"):
        from types import SimpleNamespace

        return SimpleNamespace(microsite_partner_token=token)

    def _fake_campaign(self):
        from types import SimpleNamespace

        return SimpleNamespace(generation_config={"template_type": "eventfest"})

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
