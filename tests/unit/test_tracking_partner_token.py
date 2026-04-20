"""Unit tests for partner-token contact resolution in tracking_routes
(Phase 2 Task 3).

Covers:
4. POST /api/tracking/microsite-event with token matching a
   CampaignContact.microsite_partner_token resolves the correct contact
   and persists an Activity row.
5. Backward-compat: when the token is NOT a known partner token, the
   existing email-in-data lookup path still resolves the contact.
"""

from __future__ import annotations

import pytest

from api.models import Activity, Campaign, CampaignContact, Contact


@pytest.fixture
def api_key(app):
    """Configure the X-API-Key the tracking endpoint expects."""
    key = "test-tracking-key-phase2"
    app.config["UA_INVITE_API_KEY"] = key
    yield key
    app.config["UA_INVITE_API_KEY"] = ""


@pytest.fixture
def seed_partner_recipient(db, seed_tenant):
    """Seed a Contact + CampaignContact with a known partner token."""
    contact = Contact(
        tenant_id=seed_tenant.id,
        first_name="Petr",
        last_name="Cerny",
        email_address="petr@example.com",
    )
    db.session.add(contact)
    db.session.flush()

    campaign = Campaign(
        tenant_id=seed_tenant.id,
        name="Partner Token Test",
        status="sending",
    )
    db.session.add(campaign)
    db.session.flush()

    cc = CampaignContact(
        campaign_id=campaign.id,
        contact_id=contact.id,
        tenant_id=seed_tenant.id,
        status="sent",
        microsite_partner_token="ptok_abc123",
    )
    db.session.add(cc)
    db.session.commit()
    return {"contact": contact, "campaign": campaign, "cc": cc}


def _headers(api_key):
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


class TestPartnerTokenResolution:
    """POST /api/tracking/microsite-event partner-token strategy."""

    def test_partner_token_resolves_contact(
        self, client, api_key, seed_partner_recipient, db
    ):
        """Test 4: token=<partner_token> → Activity created on the right contact."""
        resp = client.post(
            "/api/tracking/microsite-event",
            json={
                "token": "ptok_abc123",
                "event": "invite_redeemed",
                "data": {},
            },
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["matched"] is True

        # Activity persisted, linked to seed_partner_recipient.contact
        contact_id = seed_partner_recipient["contact"].id
        with client.application.app_context():
            act = (
                Activity.query.filter_by(
                    contact_id=contact_id,
                    source="microsite",
                )
                .order_by(Activity.created_at.desc())
                .first()
            )
            assert act is not None
            assert act.event_type == "invite_redeemed"

    def test_email_lookup_still_works_when_token_unknown(
        self, client, api_key, seed_partner_recipient, db
    ):
        """Test 5: token NOT a partner token → email fallback still works."""
        # Use a distinct token (not in CampaignContact.microsite_partner_token).
        resp = client.post(
            "/api/tracking/microsite-event",
            json={
                "token": "not-a-real-partner-token",
                "event": "page_viewed",
                "data": {"email": "petr@example.com"},
            },
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["matched"] is True

        contact_id = seed_partner_recipient["contact"].id
        with client.application.app_context():
            act = Activity.query.filter_by(
                contact_id=contact_id,
                event_type="page_viewed",
                source="microsite",
            ).first()
            assert act is not None
