"""Tests for the ua-microsite invite integration.

Verifies that ``get_or_create_invite`` calls the bulk endpoint
(``/api/invites/bulk``) with ``applyEventFestDefaults`` at the TOP
LEVEL of the body, parses the bulk response shape, preserves retry
semantics on transient failures, and supports an opt-out for
non-EventFest use cases.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from api.services.microsite_invites import get_or_create_invite


def _bulk_success_response(
    email: str = "jana@example.com",
    token: str = "abc123",
    status: str = "created",
    url: str | None = None,
) -> MagicMock:
    """Helper: build a mock response matching the bulk endpoint shape."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "created": 1 if status == "created" else 0,
        "reused": 1 if status == "reused" else 0,
        "results": [
            {
                "email": email,
                "token": token,
                "url": url if url is not None else f"/invite/{token}",
                "status": status,
            }
        ],
    }
    resp.raise_for_status = MagicMock()
    return resp


class TestBulkEndpointUsed:
    """The function must hit the bulk endpoint, never the singular one."""

    @patch("api.services.microsite_invites.requests.post")
    def test_bulk_endpoint_used(self, mock_post):
        mock_post.return_value = _bulk_success_response()

        get_or_create_invite(
            "jana@example.com",
            "Jana Nováková",
            "https://booking.loserscirque.cz",
            "secret-key",
        )

        called_url = mock_post.call_args.args[0]
        assert called_url == "https://booking.loserscirque.cz/api/invites/bulk"
        # Make sure the singular endpoint is NOT used.
        assert not called_url.endswith("/api/invites")


class TestApplyEventFestDefaultsTopLevel:
    """``applyEventFestDefaults`` must be a top-level key, not nested inside a contact."""

    @patch("api.services.microsite_invites.requests.post")
    def test_apply_eventfest_defaults_top_level(self, mock_post):
        mock_post.return_value = _bulk_success_response()

        get_or_create_invite(
            "jana@example.com",
            "Jana Nováková",
            "https://booking.loserscirque.cz",
            "secret-key",
        )

        body = mock_post.call_args.kwargs["json"]

        # Top-level flag must be present and truthy.
        assert body.get("applyEventFestDefaults") is True

        # Contacts must be a non-empty array and MUST NOT carry the flag.
        assert isinstance(body.get("contacts"), list)
        assert len(body["contacts"]) == 1
        contact = body["contacts"][0]
        assert "applyEventFestDefaults" not in contact
        assert contact["email"] == "jana@example.com"
        assert contact["name"] == "Jana Nováková"
        # `type: "partner"` was the singular-endpoint payload; bulk does not use it.
        assert "type" not in contact

    @patch("api.services.microsite_invites.requests.post")
    def test_company_forwarded_when_provided(self, mock_post):
        mock_post.return_value = _bulk_success_response()

        get_or_create_invite(
            "jana@example.com",
            "Jana Nováková",
            "https://booking.loserscirque.cz",
            "secret-key",
            company="Acme s.r.o.",
        )

        contact = mock_post.call_args.kwargs["json"]["contacts"][0]
        assert contact["company"] == "Acme s.r.o."

    @patch("api.services.microsite_invites.requests.post")
    def test_company_omitted_when_not_provided(self, mock_post):
        mock_post.return_value = _bulk_success_response()

        get_or_create_invite(
            "jana@example.com",
            "Jana Nováková",
            "https://booking.loserscirque.cz",
            "secret-key",
        )

        contact = mock_post.call_args.kwargs["json"]["contacts"][0]
        assert "company" not in contact


class TestResponseParsingBulkShape:
    """The function must read ``results[0]`` from the bulk response shape."""

    @patch("api.services.microsite_invites.requests.post")
    def test_response_parsing_bulk_shape(self, mock_post):
        mock_post.return_value = _bulk_success_response(
            email="jana@example.com",
            token="abc123",
            status="created",
        )

        url = get_or_create_invite(
            "jana@example.com",
            "Jana Nováková",
            "https://booking.loserscirque.cz",
            "test-key",
        )

        assert url == "https://booking.loserscirque.cz/invite/abc123"

    @patch("api.services.microsite_invites.requests.post")
    def test_response_parsing_reused_invite(self, mock_post):
        """Idempotent reuse — same parsing path as created."""
        mock_post.return_value = _bulk_success_response(
            email="jana@example.com",
            token="reused999",
            status="reused",
        )

        url = get_or_create_invite(
            "jana@example.com",
            "Jana Nováková",
            "https://booking.loserscirque.cz",
            "test-key",
        )

        assert url == "https://booking.loserscirque.cz/invite/reused999"

    @patch("api.services.microsite_invites.requests.post")
    def test_response_parsing_absolute_url(self, mock_post):
        """When the microsite already returns an absolute URL, pass it through."""
        mock_post.return_value = _bulk_success_response(
            email="test@example.com",
            token="xyz",
            url="https://booking.loserscirque.cz/invite/xyz",
        )

        url = get_or_create_invite(
            "test@example.com",
            "Test User",
            "https://booking.loserscirque.cz",
            "test-key",
        )

        assert url == "https://booking.loserscirque.cz/invite/xyz"

    @patch("api.services.microsite_invites.requests.post")
    def test_response_parsing_per_contact_error(self, mock_post):
        """A per-contact ``status: 'error'`` entry yields ``None`` (not a retry loop)."""
        error_resp = MagicMock()
        error_resp.status_code = 200
        error_resp.json.return_value = {
            "created": 0,
            "reused": 0,
            "results": [
                {
                    "email": "jana@example.com",
                    "token": "",
                    "url": "",
                    "status": "error",
                    "error": "missing email",
                }
            ],
        }
        error_resp.raise_for_status = MagicMock()
        mock_post.return_value = error_resp

        url = get_or_create_invite(
            "jana@example.com",
            "Jana Nováková",
            "https://booking.loserscirque.cz",
            "test-key",
        )
        assert url is None
        # Per-contact errors are terminal; no retry storm.
        assert mock_post.call_count == 1


class TestOptOutOfDefaults:
    """Non-EventFest callers can opt out of the EventFest preference defaults."""

    @patch("api.services.microsite_invites.requests.post")
    def test_opt_out_of_defaults(self, mock_post):
        mock_post.return_value = _bulk_success_response()

        get_or_create_invite(
            "jana@example.com",
            "Jana Nováková",
            "https://booking.loserscirque.cz",
            "secret-key",
            apply_eventfest_defaults=False,
        )

        body = mock_post.call_args.kwargs["json"]
        # When opted out, the flag must either be absent or explicitly false.
        assert body.get("applyEventFestDefaults", False) is False

    @patch("api.services.microsite_invites.requests.post")
    def test_default_applies_eventfest(self, mock_post):
        """Sanity check: the DEFAULT for EventFest send is ON."""
        mock_post.return_value = _bulk_success_response()

        get_or_create_invite(
            "jana@example.com",
            "Jana Nováková",
            "https://booking.loserscirque.cz",
            "secret-key",
        )

        body = mock_post.call_args.kwargs["json"]
        assert body["applyEventFestDefaults"] is True


class TestErrorHandlingPreserved:
    """Retry-on-transient-failure semantics (Phase 3 Task C) must survive."""

    @patch("api.services.microsite_invites.requests.post")
    def test_error_handling_preserved(self, mock_post):
        """Transient 5xx on the first call, success on the second."""
        failing_resp = MagicMock()
        failing_resp.status_code = 503
        failing_resp.raise_for_status.side_effect = Exception("503 Service Unavailable")

        success_resp = _bulk_success_response(token="retry123")

        mock_post.side_effect = [failing_resp, success_resp]

        url = get_or_create_invite(
            "test@example.com",
            "Test",
            "https://booking.loserscirque.cz",
            "key",
        )

        assert url == "https://booking.loserscirque.cz/invite/retry123"
        assert mock_post.call_count == 2

    @patch("api.services.microsite_invites.requests.post")
    def test_connection_error_retried(self, mock_post):
        """ConnectionError on the first call, success on the second."""
        success_resp = _bulk_success_response(token="retry456")
        mock_post.side_effect = [ConnectionError("boom"), success_resp]

        url = get_or_create_invite(
            "test@example.com",
            "Test",
            "https://booking.loserscirque.cz",
            "key",
        )

        assert url == "https://booking.loserscirque.cz/invite/retry456"
        assert mock_post.call_count == 2

    @patch("api.services.microsite_invites.requests.post")
    def test_returns_none_after_exhausted_retries(self, mock_post):
        """Both attempts fail → None (caller decides what to do)."""
        mock_post.side_effect = ConnectionError("always down")

        url = get_or_create_invite(
            "test@example.com",
            "Test",
            "https://booking.loserscirque.cz",
            "key",
        )

        assert url is None
        assert mock_post.call_count == 2

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
