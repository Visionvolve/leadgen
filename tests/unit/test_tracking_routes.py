"""Tests for the microsite event tracking endpoint."""

import pytest

from api.models import Activity, Campaign, CampaignContact, Contact
from tests.conftest import auth_header


@pytest.fixture
def api_key(app):
    """Set UA_INVITE_API_KEY on the app config and return it."""
    key = "test-tracking-key-12345"
    app.config["UA_INVITE_API_KEY"] = key
    yield key
    app.config["UA_INVITE_API_KEY"] = ""


@pytest.fixture
def seed_contact(db, seed_tenant):
    """Create a single contact for tracking tests."""
    c = Contact(
        tenant_id=seed_tenant.id,
        first_name="Jana",
        last_name="Novakova",
        email_address="jana@example.com",
    )
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def seed_campaign_with_contact(db, seed_tenant, seed_contact, seed_companies_contacts):
    """Create a campaign with the seed contact assigned."""
    data = seed_companies_contacts
    campaign = Campaign(
        tenant_id=seed_tenant.id,
        name="Microsite Campaign",
        status="active",
        owner_id=data["owners"][0].id,
    )
    db.session.add(campaign)
    db.session.flush()

    cc = CampaignContact(
        campaign_id=campaign.id,
        contact_id=seed_contact.id,
        tenant_id=seed_tenant.id,
    )
    db.session.add(cc)
    db.session.commit()
    return campaign


def _headers(api_key):
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


class TestMicrositeEventIngestion:
    """POST /api/tracking/microsite-event"""

    def test_valid_event_matched_by_email(self, client, api_key, seed_contact):
        resp = client.post(
            "/api/tracking/microsite-event",
            json={
                "token": "abc123",
                "event": "invite_redeemed",
                "data": {"email": "jana@example.com"},
            },
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["matched"] is True

        # Verify activity was persisted
        with client.application.app_context():
            act = Activity.query.filter_by(
                contact_id=seed_contact.id, source="microsite"
            ).first()
            assert act is not None
            assert act.activity_name == "invite_redeemed"
            assert act.event_type == "invite_redeemed"
            assert act.activity_type == "event"

    def test_valid_event_matched_by_token_email(self, client, api_key, seed_contact):
        """When data has no email, fall back to token-as-email."""
        resp = client.post(
            "/api/tracking/microsite-event",
            json={
                "token": "jana@example.com",
                "event": "page_viewed",
                "data": {"page": "/products"},
            },
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["matched"] is True

    def test_unresolved_contact_returns_ok(self, client, api_key, seed_contact):
        """Unknown token/email still returns 200 but matched=False."""
        resp = client.post(
            "/api/tracking/microsite-event",
            json={
                "token": "unknown-token",
                "event": "product_viewed",
                "data": {},
            },
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["matched"] is False

    def test_missing_api_key_rejected(self, client, api_key, seed_contact):
        resp = client.post(
            "/api/tracking/microsite-event",
            json={"token": "x", "event": "page_viewed", "data": {}},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is False
        assert "unauthorized" in body.get("error", "")

    def test_wrong_api_key_rejected(self, client, api_key, seed_contact):
        resp = client.post(
            "/api/tracking/microsite-event",
            json={"token": "x", "event": "page_viewed", "data": {}},
            headers={"X-API-Key": "wrong-key", "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is False

    def test_missing_event_returns_error(self, client, api_key):
        resp = client.post(
            "/api/tracking/microsite-event",
            json={"token": "x", "data": {}},
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is False
        assert "missing" in body.get("error", "")

    def test_unknown_event_returns_error(self, client, api_key):
        resp = client.post(
            "/api/tracking/microsite-event",
            json={"token": "x", "event": "hacked", "data": {}},
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is False
        assert "unknown" in body.get("error", "")

    def test_custom_timestamp_parsed(self, client, api_key, seed_contact):
        resp = client.post(
            "/api/tracking/microsite-event",
            json={
                "token": "t",
                "event": "session_ended",
                "data": {"email": "jana@example.com"},
                "timestamp": "2026-04-13T10:30:00Z",
            },
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["matched"] is True

    def test_all_valid_events_accepted(self, client, api_key, seed_contact):
        for event in ("invite_redeemed", "product_viewed", "page_viewed", "session_ended"):
            resp = client.post(
                "/api/tracking/microsite-event",
                json={
                    "token": "t",
                    "event": event,
                    "data": {"email": "jana@example.com"},
                },
                headers=_headers(api_key),
            )
            assert resp.status_code == 200
            assert resp.get_json()["ok"] is True


class TestCampaignAnalyticsMicrosite:
    """Verify the microsite section in campaign analytics response."""

    def test_analytics_includes_microsite_section(
        self, client, api_key, seed_contact, seed_campaign_with_contact, seed_super_admin
    ):
        """Ingest events then verify analytics aggregates them."""
        # Ingest two microsite events for the contact
        for event in ("page_viewed", "product_viewed"):
            client.post(
                "/api/tracking/microsite-event",
                json={
                    "token": "t",
                    "event": event,
                    "data": {"email": "jana@example.com"},
                },
                headers=_headers(api_key),
            )

        # Fetch campaign analytics (requires auth)
        campaign_id = str(seed_campaign_with_contact.id)
        hdrs = auth_header(client)
        hdrs["X-Namespace"] = "test-corp"
        resp = client.get(f"/api/campaigns/{campaign_id}/analytics", headers=hdrs)
        assert resp.status_code == 200
        body = resp.get_json()

        ms = body.get("microsite")
        assert ms is not None, "Response must include 'microsite' key"
        assert ms["visits"] == 2
        assert ms["unique_visitors"] == 1
        assert ms["product_views"] == 1
        assert ms["visit_rate"] > 0

    def test_analytics_microsite_zero_when_no_events(
        self, client, seed_campaign_with_contact, seed_super_admin
    ):
        """Campaign with no microsite events returns zeros."""
        campaign_id = str(seed_campaign_with_contact.id)
        hdrs = auth_header(client)
        hdrs["X-Namespace"] = "test-corp"
        resp = client.get(f"/api/campaigns/{campaign_id}/analytics", headers=hdrs)
        assert resp.status_code == 200
        body = resp.get_json()

        ms = body.get("microsite")
        assert ms is not None
        assert ms["visits"] == 0
        assert ms["unique_visitors"] == 0
        assert ms["product_views"] == 0
        assert ms["visit_rate"] == 0
