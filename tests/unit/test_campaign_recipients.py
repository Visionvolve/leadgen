"""Unit tests for /api/campaigns/<id>/recipients + analytics extensions
(Phase 2 Task 4).

Covers:
- /analytics returns engagement.unsubscribed + engagement.delivered
  + sending.email.unsubscribed.
- /recipients returns one row per CampaignContact with the partner token
  and a chronologically-sorted timeline merging EmailSendLog events with
  microsite Activity events.
- /recipients is tenant-scoped (404 for foreign campaign).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.conftest import auth_header


@pytest.fixture
def smoke_campaign(db, seed_tenant, seed_user_with_role):
    """Seed a campaign with one recipient + a full event timeline."""
    from api.models import (
        Activity,
        Campaign,
        CampaignContact,
        Contact,
        EmailSendLog,
        Message,
        Owner,
    )

    # Owner + recipient.
    owner = Owner(tenant_id=seed_tenant.id, name="Hanka")
    db.session.add(owner)
    db.session.flush()

    contact = Contact(
        tenant_id=seed_tenant.id,
        first_name="Petr",
        last_name="Novak",
        email_address="petr@x.com",
    )
    db.session.add(contact)
    db.session.flush()

    campaign = Campaign(
        tenant_id=seed_tenant.id,
        name="Phase 2 Smoke",
        status="sending",
        owner_id=owner.id,
        sender_config={
            "from_email": "hana@loserscirque.cz",
            "from_name": "Hanka | LCC",
        },
    )
    db.session.add(campaign)
    db.session.flush()

    cc = CampaignContact(
        campaign_id=campaign.id,
        contact_id=contact.id,
        tenant_id=seed_tenant.id,
        status="sent",
        microsite_partner_token="ptok_petr",
    )
    db.session.add(cc)
    db.session.flush()

    msg = Message(
        tenant_id=seed_tenant.id,
        contact_id=contact.id,
        owner_id=owner.id,
        channel="email",
        sequence_step=1,
        variant="a",
        subject="EventFest",
        body="Hi {{vocative_name}}",
        status="approved",
        campaign_contact_id=cc.id,
    )
    db.session.add(msg)
    db.session.flush()

    log = EmailSendLog(
        tenant_id=seed_tenant.id,
        message_id=msg.id,
        resend_message_id="resend-smoke-1",
        status="unsubscribed",
        from_email="hana@loserscirque.cz",
        to_email="petr@x.com",
        sent_at=datetime(2026, 4, 1, 9, 0, 0, tzinfo=timezone.utc),
        delivered_at=datetime(2026, 4, 1, 9, 0, 5, tzinfo=timezone.utc),
        opened_at=datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc),
        clicked_at=datetime(2026, 4, 1, 10, 5, 0, tzinfo=timezone.utc),
        unsubscribed_at=datetime(2026, 4, 1, 11, 0, 0, tzinfo=timezone.utc),
    )
    db.session.add(log)

    # Microsite invite redemption activity
    act = Activity(
        tenant_id=seed_tenant.id,
        contact_id=contact.id,
        activity_name="invite_redeemed",
        activity_type="event",
        source="microsite",
        event_type="invite_redeemed",
        occurred_at=datetime(2026, 4, 1, 10, 30, 0, tzinfo=timezone.utc),
        timestamp=datetime(2026, 4, 1, 10, 30, 0, tzinfo=timezone.utc),
    )
    db.session.add(act)

    db.session.commit()
    return {"campaign": campaign, "cc": cc, "contact": contact, "msg": msg}


def _auth(client):
    """Test JWT for the seeded user."""
    return auth_header(client, email="user@test.com")


class TestAnalyticsExtensions:
    """GET /api/campaigns/<id>/analytics — Phase 2 fields."""

    def test_engagement_includes_unsubscribed_and_delivered(
        self, client, smoke_campaign, seed_user_with_role
    ):
        camp = smoke_campaign["campaign"]
        resp = client.get(
            f"/api/campaigns/{camp.id}/analytics",
            headers=_auth(client),
        )
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()

        engagement = body["engagement"]
        assert engagement["unsubscribed"] == 1
        assert engagement["delivered"] == 1
        assert engagement["opened"] == 1
        assert engagement["clicked"] == 1
        assert "unsubscribe_rate" in engagement

        sending_email = body["sending"]["email"]
        assert sending_email["unsubscribed"] == 1
        assert sending_email["delivered"] == 1


class TestCampaignRecipients:
    """GET /api/campaigns/<id>/recipients."""

    def test_recipients_returns_chronological_timeline(
        self, client, smoke_campaign, seed_user_with_role
    ):
        camp = smoke_campaign["campaign"]
        resp = client.get(
            f"/api/campaigns/{camp.id}/recipients",
            headers=_auth(client),
        )
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()

        assert "recipients" in body
        assert len(body["recipients"]) == 1
        recipient = body["recipients"][0]

        assert recipient["email"] == "petr@x.com"
        assert recipient["name"] == "Petr Novak"
        assert recipient["microsite_partner_token"] == "ptok_petr"

        # Timeline: 5 mail events + 1 microsite activity = 6
        timeline = recipient["timeline"]
        assert len(timeline) == 6

        # Chronological order (ascending ts).
        timestamps = [ev["ts"] for ev in timeline]
        assert timestamps == sorted(timestamps)

        # Verify each expected event type present.
        types = [ev["type"] for ev in timeline]
        assert types.count("sent") == 1
        assert types.count("delivered") == 1
        assert types.count("opened") == 1
        assert types.count("clicked") == 1
        assert types.count("unsubscribed") == 1
        assert types.count("microsite_activity") == 1

        # Confirm the microsite event surfaces the activity name.
        ms = next(ev for ev in timeline if ev["type"] == "microsite_activity")
        assert ms["event"] == "invite_redeemed"

    def test_recipients_404_for_unknown_campaign(
        self, client, smoke_campaign, seed_user_with_role
    ):
        resp = client.get(
            "/api/campaigns/00000000-0000-0000-0000-000000000000/recipients",
            headers=_auth(client),
        )
        assert resp.status_code == 404
