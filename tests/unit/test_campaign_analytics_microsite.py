"""Unit tests for GET /api/campaigns/<id>/analytics/microsite (BL-1038).

Covers: happy-path payload shape, graceful degradation when PostHog raises
PostHogUnavailableError, graceful degradation when PostHog is not configured
(RuntimeError on ``PostHogClient()`` init), cross-tenant 404 isolation, range
window calculation for 24h/7d/30d/all, invalid range 400, auth required.

All PostHog traffic is mocked — tests never hit the real PostHog API.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from api.integrations.posthog import (
    CampaignMicrositeMetrics,
    PostHogUnavailableError,
)
from api.models import Campaign, Tenant
from tests.conftest import auth_header


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _posthog_env(monkeypatch):
    """Default PostHog env for microsite route tests. Individual tests may
    delenv to exercise the not-configured branch."""
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test_secret_KEY_DO_NOT_LEAK")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "383334")
    yield


def _make_campaign(db, tenant_id, name="Analytics Campaign"):
    c = Campaign(
        tenant_id=tenant_id,
        name=name,
        status="review",
        generation_config=json.dumps({}),
    )
    db.session.add(c)
    db.session.flush()
    return c


def _sample_metrics(campaign_id, since, until, **overrides):
    kwargs = dict(
        campaign_id=campaign_id,
        since=since,
        until=until,
        visits=128,
        unique_visitors=94,
        cta_clicks=12,
        form_submits=3,
        avg_time_on_page_sec=42.5,
    )
    kwargs.update(overrides)
    return CampaignMicrositeMetrics(**kwargs)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestMicrositeHappyPath:
    def test_returns_metrics_from_posthog(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        def _fake(self, campaign_id, since, until):
            return _sample_metrics(campaign_id, since, until)

        with patch(
            "api.integrations.posthog.PostHogClient.get_campaign_microsite_metrics",
            _fake,
        ):
            resp = client.get(
                f"/api/campaigns/{campaign.id}/analytics/microsite?range=7d",
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["campaign_id"] == str(campaign.id)
        assert data["range"] == "7d"
        assert data["source"] == "posthog"
        assert data["posthog_available"] is True
        assert "degraded_reason" not in data

        assert data["metrics"] == {
            "visits": 128,
            "unique_visitors": 94,
            "cta_clicks": 12,
            "form_submits": 3,
            "avg_time_on_page_sec": 42.5,
        }

        # since / until are ISO-8601 and span ~7 days
        since = datetime.fromisoformat(data["since"])
        until = datetime.fromisoformat(data["until"])
        delta = until - since
        assert (
            timedelta(days=7) - timedelta(seconds=5)
            <= delta
            <= timedelta(days=7) + timedelta(seconds=5)
        )

    def test_default_range_is_7d(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        def _fake(self, campaign_id, since, until):
            return _sample_metrics(campaign_id, since, until)

        with patch(
            "api.integrations.posthog.PostHogClient.get_campaign_microsite_metrics",
            _fake,
        ):
            resp = client.get(
                f"/api/campaigns/{campaign.id}/analytics/microsite", headers=headers
            )
        assert resp.status_code == 200
        assert resp.get_json()["range"] == "7d"

    def test_range_24h_window(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        def _fake(self, campaign_id, since, until):
            return _sample_metrics(campaign_id, since, until)

        with patch(
            "api.integrations.posthog.PostHogClient.get_campaign_microsite_metrics",
            _fake,
        ):
            resp = client.get(
                f"/api/campaigns/{campaign.id}/analytics/microsite?range=24h",
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.get_json()
        since = datetime.fromisoformat(data["since"])
        until = datetime.fromisoformat(data["until"])
        delta = until - since
        assert (
            timedelta(hours=24) - timedelta(seconds=5)
            <= delta
            <= timedelta(hours=24) + timedelta(seconds=5)
        )

    def test_range_30d_window(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        def _fake(self, campaign_id, since, until):
            return _sample_metrics(campaign_id, since, until)

        with patch(
            "api.integrations.posthog.PostHogClient.get_campaign_microsite_metrics",
            _fake,
        ):
            resp = client.get(
                f"/api/campaigns/{campaign.id}/analytics/microsite?range=30d",
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.get_json()
        since = datetime.fromisoformat(data["since"])
        until = datetime.fromisoformat(data["until"])
        delta = until - since
        assert (
            timedelta(days=30) - timedelta(seconds=5)
            <= delta
            <= timedelta(days=30) + timedelta(seconds=5)
        )

    def test_range_all_uses_far_past(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        def _fake(self, campaign_id, since, until):
            return _sample_metrics(campaign_id, since, until)

        with patch(
            "api.integrations.posthog.PostHogClient.get_campaign_microsite_metrics",
            _fake,
        ):
            resp = client.get(
                f"/api/campaigns/{campaign.id}/analytics/microsite?range=all",
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.get_json()
        since = datetime.fromisoformat(data["since"])
        # "all" should put the window opener in the far past (pre-2022)
        assert since.year <= 2022

    def test_nullable_avg_time_preserved(self, client, seed_companies_contacts, db):
        """When PostHog has no time-on-page data, avg_time_on_page_sec is None."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        def _fake(self, campaign_id, since, until):
            return _sample_metrics(campaign_id, since, until, avg_time_on_page_sec=None)

        with patch(
            "api.integrations.posthog.PostHogClient.get_campaign_microsite_metrics",
            _fake,
        ):
            resp = client.get(
                f"/api/campaigns/{campaign.id}/analytics/microsite?range=7d",
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["metrics"]["avg_time_on_page_sec"] is None


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestMicrositeDegradation:
    def test_posthog_unavailable_returns_200_with_zero_metrics(
        self, client, seed_companies_contacts, db
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        def _boom(self, campaign_id, since, until):
            raise PostHogUnavailableError("PostHog Query API returned HTTP 503")

        with patch(
            "api.integrations.posthog.PostHogClient.get_campaign_microsite_metrics",
            _boom,
        ):
            resp = client.get(
                f"/api/campaigns/{campaign.id}/analytics/microsite?range=7d",
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["posthog_available"] is False
        assert data["source"] == "posthog"
        assert data["metrics"] == {
            "visits": 0,
            "unique_visitors": 0,
            "cta_clicks": 0,
            "form_submits": 0,
            "avg_time_on_page_sec": None,
        }
        assert "degraded_reason" in data
        # Reason is a plain string — never leaks the API key.
        assert "phx_" not in data["degraded_reason"]
        assert "PERSONAL_API_KEY" not in data["degraded_reason"]

    def test_posthog_not_configured_returns_200_with_zero_metrics(
        self, client, seed_companies_contacts, db, monkeypatch
    ):
        """Missing POSTHOG_PERSONAL_API_KEY raises RuntimeError at client init
        — the route should degrade, not 500."""
        monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/microsite?range=7d",
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["posthog_available"] is False
        assert data["metrics"]["visits"] == 0
        assert data["metrics"]["avg_time_on_page_sec"] is None
        # Reason is not empty but must not contain secret material.
        reason = data.get("degraded_reason", "")
        assert reason
        assert "phx_" not in reason

    def test_degraded_reason_does_not_leak_posthog_key(
        self, client, seed_companies_contacts, db, monkeypatch
    ):
        """Even if a hypothetical error message included the key, the route
        must never pass the raw API key into the response."""
        monkeypatch.setenv(
            "POSTHOG_PERSONAL_API_KEY", "phx_SUPER_SECRET_DO_NOT_LEAK_xyz"
        )
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        def _boom(self, campaign_id, since, until):
            raise PostHogUnavailableError("PostHog Query API network error")

        with patch(
            "api.integrations.posthog.PostHogClient.get_campaign_microsite_metrics",
            _boom,
        ):
            resp = client.get(
                f"/api/campaigns/{campaign.id}/analytics/microsite?range=7d",
                headers=headers,
            )

        raw = resp.get_data(as_text=True)
        assert "phx_SUPER_SECRET_DO_NOT_LEAK_xyz" not in raw


# ---------------------------------------------------------------------------
# Security / validation
# ---------------------------------------------------------------------------


class TestMicrositeSecurity:
    def test_auth_required(self, client, db):
        resp = client.get("/api/campaigns/some-id/analytics/microsite")
        assert resp.status_code == 401

    def test_campaign_not_found_returns_404(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get(
            "/api/campaigns/00000000-0000-0000-0000-000000000000/analytics/microsite",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_cross_tenant_campaign_returns_404_not_403(
        self, client, seed_companies_contacts, db, seed_super_admin
    ):
        """A campaign that exists but belongs to a different tenant must
        return 404 (NOT 403) — spec NFR-3: avoid existence disclosure."""
        # Create a second tenant + campaign that the caller must not see.
        other = Tenant(name="Other Corp", slug="other-corp", is_active=True)
        db.session.add(other)
        db.session.flush()
        other_campaign = _make_campaign(db, other.id, name="Other Tenant Campaign")
        db.session.commit()

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"  # auth context is test-corp

        # Even if PostHog would happily return data, the tenant check must
        # short-circuit before any PostHog call. We use an explicit MagicMock
        # + assert_not_called() (rather than a side-effecting AssertionError
        # helper) so the assertion is clearly visible in the test body and
        # won't be swallowed by any broad except in the route handler.
        mock_metrics = MagicMock()
        with patch(
            "api.integrations.posthog.PostHogClient.get_campaign_microsite_metrics",
            mock_metrics,
        ):
            resp = client.get(
                f"/api/campaigns/{other_campaign.id}/analytics/microsite?range=7d",
                headers=headers,
            )

        assert resp.status_code == 404
        mock_metrics.assert_not_called()  # PostHog never invoked
        body = resp.get_json() or {}
        err = (body.get("error") or "").lower()
        # Spec NFR-3: 404 should look like "not found", never "forbidden".
        assert "not found" in err or err == ""

    def test_invalid_range_returns_400(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/microsite?range=bogus",
            headers=headers,
        )
        assert resp.status_code == 400
