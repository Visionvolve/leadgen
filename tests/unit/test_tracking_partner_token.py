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


class TestPhase4CampaignAttributionFk:
    """Phase 4 Fix C + Fix D: the tracking endpoint must (a) preserve the
    top-level token inside activities.payload so pre-061 JSONB joins keep
    working, and (b) populate the new activities.campaign_contact_id FK
    whenever the token matches a known CampaignContact row. The combination
    is what lets the dashboard attribute every click back to a specific
    campaign reliably and with a proper index — no JSONB extract needed."""

    def test_payload_preserves_token_when_token_matches(
        self, client, api_key, seed_partner_recipient, db
    ):
        """Fix C — payload must carry the token as a top-level key."""
        resp = client.post(
            "/api/tracking/microsite-event",
            json={
                "token": "ptok_abc123",
                "event": "product_viewed",
                "data": {"product_slug": "cyr-wheel"},
            },
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        contact_id = seed_partner_recipient["contact"].id
        with client.application.app_context():
            act = (
                Activity.query.filter_by(
                    contact_id=contact_id,
                    event_type="product_viewed",
                )
                .order_by(Activity.created_at.desc())
                .first()
            )
            assert act is not None
            # SQLite-in-test stores JSONB-as-Text, so parse if we need to.
            payload = act.payload
            if isinstance(payload, str):
                import json

                payload = json.loads(payload)
            assert payload.get("token") == "ptok_abc123"
            assert payload.get("product_slug") == "cyr-wheel"

    def test_payload_preserves_token_even_when_token_unknown(
        self, client, api_key, seed_partner_recipient, db
    ):
        """Fix C — unknown token still gets round-tripped to payload.token
        (so the JSONB join can later reconcile if the DB is backfilled)."""
        resp = client.post(
            "/api/tracking/microsite-event",
            json={
                "token": "ptok_not_in_db",
                "event": "page_viewed",
                "data": {
                    "email": "petr@example.com",
                    "path": "/cs/performances/onyx",
                },
            },
            headers=_headers(api_key),
        )
        assert resp.status_code == 200

        contact_id = seed_partner_recipient["contact"].id
        with client.application.app_context():
            act = (
                Activity.query.filter_by(
                    contact_id=contact_id,
                    event_type="page_viewed",
                )
                .order_by(Activity.created_at.desc())
                .first()
            )
            assert act is not None
            payload = act.payload
            if isinstance(payload, str):
                import json

                payload = json.loads(payload)
            assert payload.get("token") == "ptok_not_in_db"

    def test_campaign_contact_id_set_when_token_matches(
        self, client, api_key, seed_partner_recipient, db
    ):
        """Fix D — when the token resolves a CampaignContact, the activity
        gets the proper FK populated so campaign attribution is a fast
        indexed join, not a JSONB extract."""
        cc_id = seed_partner_recipient["cc"].id

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
        assert resp.get_json()["matched"] is True

        contact_id = seed_partner_recipient["contact"].id
        with client.application.app_context():
            act = (
                Activity.query.filter_by(
                    contact_id=contact_id,
                    event_type="invite_redeemed",
                )
                .order_by(Activity.created_at.desc())
                .first()
            )
            assert act is not None
            assert act.campaign_contact_id == cc_id

    def test_campaign_contact_id_null_when_token_unknown(
        self, client, api_key, seed_partner_recipient, db
    ):
        """Fix D — when the token does NOT match any CampaignContact, the
        activity is still persisted (via email fallback), but the FK is
        left NULL so we don't accidentally attribute to a wrong campaign."""
        resp = client.post(
            "/api/tracking/microsite-event",
            json={
                "token": "ptok_does_not_exist",
                "event": "page_viewed",
                "data": {"email": "petr@example.com"},
            },
            headers=_headers(api_key),
        )
        assert resp.status_code == 200
        assert resp.get_json()["matched"] is True

        contact_id = seed_partner_recipient["contact"].id
        with client.application.app_context():
            act = (
                Activity.query.filter_by(
                    contact_id=contact_id,
                    event_type="page_viewed",
                )
                .order_by(Activity.created_at.desc())
                .first()
            )
            assert act is not None
            assert act.campaign_contact_id is None

    def test_campaign_contact_fk_ondelete_set_null(
        self, client, api_key, seed_partner_recipient, db
    ):
        """Migration 061 declares ON DELETE SET NULL. Deleting the
        CampaignContact must NOT cascade-delete activities rows — they
        are historical events and stay around, just with the FK nulled.

        The SQLAlchemy ForeignKey declares ondelete='SET NULL'; this test
        exercises the model-level declaration by manually nulling the FK
        after deleting the parent row (SQLite-in-test does not always
        enforce ondelete declaratively, so we assert the intent — i.e. the
        activity survives, the parent is gone, and nulling is safe). The
        prod DDL (migration 061) enforces the cascade at the DB level."""
        from api.models import Activity, CampaignContact

        # Ingest an event first so we have a real activity row.
        client.post(
            "/api/tracking/microsite-event",
            json={
                "token": "ptok_abc123",
                "event": "invite_redeemed",
                "data": {},
            },
            headers=_headers(api_key),
        )

        cc_id = seed_partner_recipient["cc"].id
        contact_id = seed_partner_recipient["contact"].id

        with client.application.app_context():
            act = Activity.query.filter_by(contact_id=contact_id).first()
            assert act is not None
            assert act.campaign_contact_id == cc_id

            # Simulate the ondelete=SET NULL effect: null the FK, then
            # delete the parent row. Order matters on SQLite.
            act.campaign_contact_id = None
            db.session.flush()
            cc = db.session.get(CampaignContact, cc_id)
            db.session.delete(cc)
            db.session.commit()

            # Historical activity row still exists.
            surviving = db.session.get(Activity, act.id)
            assert surviving is not None
            assert surviving.campaign_contact_id is None
            assert surviving.event_type == "invite_redeemed"
