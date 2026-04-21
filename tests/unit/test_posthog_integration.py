"""Unit tests for PostHog backend integration (BL-1035).

Covers: client initialization, query construction, graceful degradation on
HTTP errors, 30s cache behavior, and cache-key isolation. All HTTP traffic
is mocked — tests never hit the real PostHog API.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from api.integrations.posthog import (
    CampaignMicrositeMetrics,
    PostHogClient,
    PostHogUnavailableError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _posthog_env(monkeypatch):
    """Provide minimally valid PostHog env for every test.

    Individual tests can override via monkeypatch.delenv / setenv.
    """
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test_secret_KEY_DO_NOT_LEAK")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "383334")
    yield


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure each test starts with an empty module-level cache."""
    from api.integrations import posthog

    posthog._clear_cache_for_tests()
    yield
    posthog._clear_cache_for_tests()


def _mock_posthog_response(
    visits=10,
    unique_visitors=7,
    cta_clicks=2,
    form_submits=1,
    avg_time_on_page_sec=42.5,
    status_code=200,
):
    """Build a MagicMock that mimics a PostHog Query API JSON response."""
    resp = MagicMock()
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} error", response=resp
        )
        resp.text = f"status {status_code}"
        return resp
    # Real PostHog Query API returns {"results": [[<row cells>]], "columns": [...]}.
    resp.json.return_value = {
        "columns": [
            "visits",
            "unique_visitors",
            "cta_clicks",
            "form_submits",
            "avg_time_on_page_sec",
        ],
        "results": [
            [visits, unique_visitors, cta_clicks, form_submits, avg_time_on_page_sec]
        ],
    }
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Init / config
# ---------------------------------------------------------------------------


class TestClientInit:
    def test_missing_personal_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
        with pytest.raises(RuntimeError) as excinfo:
            PostHogClient()
        assert "POSTHOG_PERSONAL_API_KEY" in str(excinfo.value)

    def test_missing_project_id_raises(self, monkeypatch):
        monkeypatch.delenv("POSTHOG_PROJECT_ID", raising=False)
        with pytest.raises(RuntimeError) as excinfo:
            PostHogClient()
        assert "POSTHOG_PROJECT_ID" in str(excinfo.value)

    def test_default_host(self, monkeypatch):
        monkeypatch.delenv("POSTHOG_HOST", raising=False)
        client = PostHogClient()
        assert client.host == "https://us.i.posthog.com"

    def test_explicit_args_override_env(self, monkeypatch):
        monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
        client = PostHogClient(
            personal_api_key="phx_explicit",
            host="https://eu.i.posthog.com",
            project_id="42",
        )
        assert client.personal_api_key == "phx_explicit"
        assert client.host == "https://eu.i.posthog.com"
        assert client.project_id == "42"


# ---------------------------------------------------------------------------
# query()
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_posts_to_correct_url(self):
        client = PostHogClient()
        mock_resp = _mock_posthog_response()

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ) as mock_post:
            client.query("SELECT 1")

        args, kwargs = mock_post.call_args
        # URL is the first positional arg
        url = args[0] if args else kwargs.get("url")
        assert url == "https://us.i.posthog.com/api/projects/383334/query/"

    def test_query_uses_bearer_auth(self):
        client = PostHogClient()
        mock_resp = _mock_posthog_response()

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ) as mock_post:
            client.query("SELECT 1")

        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer phx_test_secret_KEY_DO_NOT_LEAK"
        assert headers["Content-Type"] == "application/json"

    def test_query_payload_has_hogql(self):
        client = PostHogClient()
        mock_resp = _mock_posthog_response()

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ) as mock_post:
            client.query("SELECT event FROM events LIMIT 5", variables={"x": 1})

        payload = mock_post.call_args[1]["json"]
        assert payload["query"]["kind"] == "HogQLQuery"
        assert payload["query"]["query"] == "SELECT event FROM events LIMIT 5"
        assert payload["query"]["values"] == {"x": 1}

    def test_query_parses_results_into_dicts(self):
        client = PostHogClient()
        mock_resp = _mock_posthog_response(
            visits=5, unique_visitors=3, cta_clicks=1, form_submits=0,
            avg_time_on_page_sec=12.3,
        )

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ):
            rows = client.query("SELECT ...")

        assert rows == [
            {
                "visits": 5,
                "unique_visitors": 3,
                "cta_clicks": 1,
                "form_submits": 0,
                "avg_time_on_page_sec": 12.3,
            }
        ]

    def test_query_500_raises_posthog_unavailable(self):
        client = PostHogClient()
        mock_resp = _mock_posthog_response(status_code=500)

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ):
            with pytest.raises(PostHogUnavailableError) as excinfo:
                client.query("SELECT 1")

        # Sanity: personal API key must never leak into the error message.
        assert "phx_test_secret_KEY_DO_NOT_LEAK" not in str(excinfo.value)
        assert "PostHog" in str(excinfo.value)

    def test_query_timeout_raises_posthog_unavailable(self):
        client = PostHogClient()

        with patch(
            "api.integrations.posthog.requests.post",
            side_effect=requests.Timeout("read timed out"),
        ):
            with pytest.raises(PostHogUnavailableError):
                client.query("SELECT 1")

    def test_query_4xx_raises_posthog_unavailable(self):
        client = PostHogClient()
        mock_resp = _mock_posthog_response(status_code=403)

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ):
            with pytest.raises(PostHogUnavailableError):
                client.query("SELECT 1")


# ---------------------------------------------------------------------------
# get_campaign_microsite_metrics()
# ---------------------------------------------------------------------------


class TestCampaignMicrositeMetrics:
    def _range(self):
        until = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
        since = until - timedelta(days=7)
        return since, until

    def test_returns_typed_result(self):
        client = PostHogClient()
        since, until = self._range()
        mock_resp = _mock_posthog_response(
            visits=20, unique_visitors=15, cta_clicks=4, form_submits=1,
            avg_time_on_page_sec=55.0,
        )

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ):
            result = client.get_campaign_microsite_metrics(
                campaign_id="cmp_abc", since=since, until=until
            )

        assert isinstance(result, CampaignMicrositeMetrics)
        assert result.campaign_id == "cmp_abc"
        assert result.visits == 20
        assert result.unique_visitors == 15
        assert result.cta_clicks == 4
        assert result.form_submits == 1
        assert result.avg_time_on_page_sec == 55.0
        assert result.since == since
        assert result.until == until

    def test_filters_query_by_campaign_id_and_time_window(self):
        client = PostHogClient()
        since, until = self._range()
        mock_resp = _mock_posthog_response()

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ) as mock_post:
            client.get_campaign_microsite_metrics(
                campaign_id="cmp_xyz", since=since, until=until
            )

        payload = mock_post.call_args[1]["json"]
        values = payload["query"]["values"]
        assert values["campaign_id"] == "cmp_xyz"
        assert values["since"] == since.isoformat()
        assert values["until"] == until.isoformat()
        # Query body references the events table and key event names.
        q = payload["query"]["query"]
        assert "events" in q
        assert "$pageview" in q
        assert "cta_clicked" in q
        assert "form_submitted" in q

    def test_handles_null_avg_time_on_page(self):
        """PostHog returns None when no page views have time_on_page_ms."""
        client = PostHogClient()
        since, until = self._range()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "columns": [
                "visits",
                "unique_visitors",
                "cta_clicks",
                "form_submits",
                "avg_time_on_page_sec",
            ],
            "results": [[0, 0, 0, 0, None]],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ):
            result = client.get_campaign_microsite_metrics(
                campaign_id="cmp_zero", since=since, until=until
            )

        assert result.visits == 0
        assert result.avg_time_on_page_sec is None

    def test_empty_result_returns_zeros(self):
        """PostHog returns an empty results list when nothing matches."""
        client = PostHogClient()
        since, until = self._range()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "columns": [
                "visits",
                "unique_visitors",
                "cta_clicks",
                "form_submits",
                "avg_time_on_page_sec",
            ],
            "results": [],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ):
            result = client.get_campaign_microsite_metrics(
                campaign_id="cmp_nothing", since=since, until=until
            )

        assert result.visits == 0
        assert result.unique_visitors == 0
        assert result.cta_clicks == 0
        assert result.form_submits == 0
        assert result.avg_time_on_page_sec is None

    def test_posthog_5xx_propagates_as_unavailable(self):
        client = PostHogClient()
        since, until = self._range()
        mock_resp = _mock_posthog_response(status_code=503)

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ):
            with pytest.raises(PostHogUnavailableError):
                client.get_campaign_microsite_metrics(
                    campaign_id="cmp_down", since=since, until=until
                )


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


class TestCache:
    def _range(self):
        until = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
        since = until - timedelta(days=7)
        return since, until

    def test_second_call_within_30s_does_not_hit_http(self):
        client = PostHogClient()
        since, until = self._range()
        mock_resp = _mock_posthog_response(visits=42)

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ) as mock_post:
            r1 = client.get_campaign_microsite_metrics(
                campaign_id="cmp_cache", since=since, until=until
            )
            r2 = client.get_campaign_microsite_metrics(
                campaign_id="cmp_cache", since=since, until=until
            )

        assert mock_post.call_count == 1
        assert r1.visits == r2.visits == 42

    def test_cache_expires_after_ttl(self):
        client = PostHogClient()
        since, until = self._range()
        mock_resp = _mock_posthog_response(visits=1)

        fake_now = [1000.0]

        def fake_monotonic():
            return fake_now[0]

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ) as mock_post, patch(
            "api.integrations.posthog.time.monotonic", side_effect=fake_monotonic
        ):
            client.get_campaign_microsite_metrics(
                campaign_id="cmp_exp", since=since, until=until
            )
            # Advance past 30s TTL
            fake_now[0] += 31.0
            client.get_campaign_microsite_metrics(
                campaign_id="cmp_exp", since=since, until=until
            )

        assert mock_post.call_count == 2

    def test_cache_key_distinguishes_campaign_id(self):
        client = PostHogClient()
        since, until = self._range()
        mock_resp = _mock_posthog_response()

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ) as mock_post:
            client.get_campaign_microsite_metrics(
                campaign_id="cmp_a", since=since, until=until
            )
            client.get_campaign_microsite_metrics(
                campaign_id="cmp_b", since=since, until=until
            )

        assert mock_post.call_count == 2

    def test_cache_key_distinguishes_since_until(self):
        client = PostHogClient()
        since1, until1 = self._range()
        since2 = since1 - timedelta(days=30)
        until2 = until1
        mock_resp = _mock_posthog_response()

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ) as mock_post:
            client.get_campaign_microsite_metrics(
                campaign_id="cmp_same", since=since1, until=until1
            )
            client.get_campaign_microsite_metrics(
                campaign_id="cmp_same", since=since2, until=until2
            )

        assert mock_post.call_count == 2


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


class TestSecretHygiene:
    def test_error_message_never_contains_personal_api_key(self):
        client = PostHogClient()
        mock_resp = _mock_posthog_response(status_code=500)

        with patch(
            "api.integrations.posthog.requests.post", return_value=mock_resp
        ):
            try:
                client.query("SELECT 1")
            except PostHogUnavailableError as exc:
                assert "phx_test_secret_KEY_DO_NOT_LEAK" not in str(exc)
                assert "phx_test_secret_KEY_DO_NOT_LEAK" not in repr(exc)

    def test_client_repr_does_not_leak_key(self):
        client = PostHogClient()
        assert "phx_test_secret_KEY_DO_NOT_LEAK" not in repr(client)
        assert "phx_test_secret_KEY_DO_NOT_LEAK" not in str(client)
