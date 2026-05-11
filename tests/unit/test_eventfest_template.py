"""Tests for EventFest HTML email template rendering."""

from unittest.mock import patch, MagicMock

from api.services.eventfest_template import (
    render_eventfest_email,
    _replace_template_variables,
    EVENTFEST_HTML_TEMPLATE,
    EVENTFEST_PLAIN_TEMPLATE,
    EVENTFEST_SUBJECT,
)
from api.services.microsite_invites import get_or_create_invite


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
        The footer label "Odhlasit se" (Czech for "unsubscribe") must
        remain in either case.
        """
        _, html, _ = render_eventfest_email("Evo", "https://example.com/invite/123")
        assert "Odhl" in html  # "Odhlasit se" footer label still present
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


class TestGetOrCreateInvite:
    """Tests for the microsite invite integration."""

    @patch("api.services.microsite_invites.requests.post")
    def test_successful_invite_creation(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "token": "abc123",
            "url": "/invite/abc123",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        url = get_or_create_invite(
            "jana@example.com",
            "Jana Nováková",
            "https://demo.visionvolve.com",
            "test-key",
        )
        assert url == "https://demo.visionvolve.com/invite/abc123"

    @patch("api.services.microsite_invites.requests.post")
    def test_invite_with_absolute_url(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "token": "xyz",
            "url": "https://demo.visionvolve.com/invite/xyz",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        url = get_or_create_invite(
            "test@example.com",
            "Test User",
            "https://demo.visionvolve.com",
            "test-key",
        )
        assert url == "https://demo.visionvolve.com/invite/xyz"

    @patch("api.services.microsite_invites.requests.post")
    def test_invite_with_token_only(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": "tok123"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        url = get_or_create_invite(
            "test@example.com",
            "Test",
            "https://demo.visionvolve.com",
            "key",
        )
        assert url == "https://demo.visionvolve.com/invite/tok123"

    @patch("api.services.microsite_invites.requests.post")
    def test_returns_none_on_api_failure(self, mock_post):
        mock_post.side_effect = ConnectionError("timeout")

        url = get_or_create_invite(
            "test@example.com",
            "Test",
            "https://demo.visionvolve.com",
            "key",
        )
        assert url is None

    def test_missing_microsite_url_returns_none(self):
        url = get_or_create_invite(
            "test@example.com",
            "Test",
            "",
            "key",
        )
        assert url is None

    def test_missing_api_key_returns_none(self):
        url = get_or_create_invite(
            "test@example.com",
            "Test",
            "https://example.com",
            "",
        )
        assert url is None

    @patch("api.services.microsite_invites.requests.post")
    def test_retry_on_first_failure(self, mock_post):
        """First call fails, second succeeds."""
        success_resp = MagicMock()
        success_resp.json.return_value = {
            "token": "retry123",
            "url": "/invite/retry123",
        }
        success_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [ConnectionError("fail"), success_resp]

        url = get_or_create_invite(
            "test@example.com",
            "Test",
            "https://demo.visionvolve.com",
            "key",
        )
        assert url == "https://demo.visionvolve.com/invite/retry123"
        assert mock_post.call_count == 2

    @patch("api.services.microsite_invites.requests.post")
    def test_sends_correct_payload(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": "t", "url": "/invite/t"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        get_or_create_invite(
            "jana@example.com",
            "Jana Nováková",
            "https://demo.visionvolve.com",
            "secret-key",
        )

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"] == {
            "email": "jana@example.com",
            "name": "Jana Nováková",
            "type": "partner",
        }
        assert call_kwargs.kwargs["headers"]["x-api-key"] == "secret-key"
