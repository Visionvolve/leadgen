"""Unit tests for GET /api/campaigns/<id>/analytics endpoint."""
import json

from api.models import (
    Campaign,
    CampaignContact,
    Contact,
    EmailSendLog,
    LinkedInSendQueue,
    Message,
    Owner,
)
from tests.conftest import auth_header


def _make_campaign(db, tenant_id, name="Test Campaign", gen_config=None):
    """Helper: create a campaign and return it."""
    c = Campaign(
        tenant_id=tenant_id,
        name=name,
        status="review",
        generation_config=json.dumps(gen_config or {}),
    )
    db.session.add(c)
    db.session.flush()
    return c


def _make_contact(db, tenant_id, first_name, email=None, linkedin_url=None):
    """Helper: create a contact and return it."""
    ct = Contact(
        tenant_id=tenant_id,
        first_name=first_name,
        last_name="Test",
        email_address=email,
        linkedin_url=linkedin_url,
    )
    db.session.add(ct)
    db.session.flush()
    return ct


def _make_campaign_contact(db, campaign_id, contact_id, tenant_id):
    """Helper: link a contact to a campaign."""
    cc = CampaignContact(
        campaign_id=campaign_id,
        contact_id=contact_id,
        tenant_id=tenant_id,
        status="generated",
    )
    db.session.add(cc)
    db.session.flush()
    return cc


def _make_message(
    db, tenant_id, contact_id, campaign_contact_id,
    channel="email", status="draft", step=1, cost=0.01,
):
    """Helper: create a message."""
    m = Message(
        tenant_id=tenant_id,
        contact_id=contact_id,
        campaign_contact_id=campaign_contact_id,
        channel=channel,
        sequence_step=step,
        body="Hello",
        subject="Hi" if channel == "email" else None,
        status=status,
        generation_cost_usd=cost,
    )
    db.session.add(m)
    db.session.flush()
    return m


class TestCampaignAnalyticsEmpty:
    """Test analytics on an empty campaign (no contacts/messages)."""

    def test_empty_campaign_returns_zeros(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        # Create a campaign with no contacts
        resp = client.post("/api/campaigns", headers=headers, json={"name": "Empty"})
        assert resp.status_code == 201
        campaign_id = resp.get_json()["id"]

        resp = client.get(f"/api/campaigns/{campaign_id}/analytics", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["messages"]["total"] == 0
        assert data["messages"]["by_status"] == {}
        assert data["messages"]["by_channel"] == {}
        assert data["messages"]["by_step"] == {}
        assert data["sending"]["email"]["total"] == 0
        assert data["sending"]["linkedin"]["total"] == 0
        assert data["contacts"]["total"] == 0
        assert data["contacts"]["with_email"] == 0
        assert data["contacts"]["with_linkedin"] == 0
        assert data["contacts"]["both_channels"] == 0
        assert data["cost"]["generation_usd"] == 0
        assert data["cost"]["email_sends"] == 0
        assert data["timeline"]["created_at"] is not None
        assert data["timeline"]["first_send_at"] is None
        assert data["timeline"]["last_send_at"] is None


class TestCampaignAnalyticsMessages:
    """Test message count aggregation by status, channel, and step."""

    def test_message_counts(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]

        campaign = _make_campaign(db, tenant.id)
        ct1 = _make_contact(db, tenant.id, "Alice", email="alice@test.com")
        ct2 = _make_contact(db, tenant.id, "Bob", linkedin_url="https://linkedin.com/in/bob")
        cc1 = _make_campaign_contact(db, campaign.id, ct1.id, tenant.id)
        cc2 = _make_campaign_contact(db, campaign.id, ct2.id, tenant.id)

        # Messages with various statuses, channels, steps
        _make_message(db, tenant.id, ct1.id, cc1.id, channel="email", status="draft", step=1)
        _make_message(db, tenant.id, ct1.id, cc1.id, channel="email", status="approved", step=2)
        _make_message(db, tenant.id, ct1.id, cc1.id, channel="email", status="approved", step=1)
        _make_message(db, tenant.id, ct2.id, cc2.id, channel="linkedin_connect", status="draft", step=1)
        _make_message(db, tenant.id, ct2.id, cc2.id, channel="linkedin_message", status="rejected", step=2)
        db.session.commit()

        resp = client.get(f"/api/campaigns/{campaign.id}/analytics", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()

        # Total messages
        assert data["messages"]["total"] == 5

        # By status
        assert data["messages"]["by_status"]["draft"] == 2
        assert data["messages"]["by_status"]["approved"] == 2
        assert data["messages"]["by_status"]["rejected"] == 1

        # By channel
        assert data["messages"]["by_channel"]["email"] == 3
        assert data["messages"]["by_channel"]["linkedin_connect"] == 1
        assert data["messages"]["by_channel"]["linkedin_message"] == 1

        # By step
        assert data["messages"]["by_step"]["1"] == 3
        assert data["messages"]["by_step"]["2"] == 2


class TestCampaignAnalyticsEmailSending:
    """Test email send log aggregation."""

    def test_email_sending_stats(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]

        campaign = _make_campaign(db, tenant.id)
        ct1 = _make_contact(db, tenant.id, "Alice", email="alice@test.com")
        cc1 = _make_campaign_contact(db, campaign.id, ct1.id, tenant.id)

        m1 = _make_message(db, tenant.id, ct1.id, cc1.id, channel="email", status="sent")
        m2 = _make_message(db, tenant.id, ct1.id, cc1.id, channel="email", status="sent", step=2)
        m3 = _make_message(db, tenant.id, ct1.id, cc1.id, channel="email", status="sent", step=3)

        # Create email send log entries
        for msg, status in [(m1, "delivered"), (m2, "sent"), (m3, "bounced")]:
            log = EmailSendLog(
                tenant_id=tenant.id,
                message_id=msg.id,
                status=status,
                from_email="sender@test.com",
                to_email="alice@test.com",
            )
            db.session.add(log)

        # Add a queued and a failed entry
        m4 = _make_message(db, tenant.id, ct1.id, cc1.id, channel="email", status="approved", step=1)
        m5 = _make_message(db, tenant.id, ct1.id, cc1.id, channel="email", status="approved", step=2)
        db.session.add(EmailSendLog(
            tenant_id=tenant.id, message_id=m4.id,
            status="queued", from_email="sender@test.com", to_email="alice@test.com",
        ))
        db.session.add(EmailSendLog(
            tenant_id=tenant.id, message_id=m5.id,
            status="failed", from_email="sender@test.com", to_email="alice@test.com",
            error="Connection timeout",
        ))
        db.session.commit()

        resp = client.get(f"/api/campaigns/{campaign.id}/analytics", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()

        email = data["sending"]["email"]
        assert email["total"] == 5
        assert email["queued"] == 1
        assert email["sent"] == 1
        assert email["delivered"] == 1
        assert email["bounced"] == 1
        assert email["failed"] == 1

        # Cost should reflect email sends total
        assert data["cost"]["email_sends"] == 5


class TestCampaignAnalyticsContacts:
    """Test contact stats (with_email, with_linkedin, both)."""

    def test_contact_stats(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]

        campaign = _make_campaign(db, tenant.id)

        # Contact with email only
        ct1 = _make_contact(db, tenant.id, "EmailOnly", email="a@test.com")
        _make_campaign_contact(db, campaign.id, ct1.id, tenant.id)

        # Contact with linkedin only
        ct2 = _make_contact(db, tenant.id, "LinkedInOnly", linkedin_url="https://linkedin.com/in/x")
        _make_campaign_contact(db, campaign.id, ct2.id, tenant.id)

        # Contact with both
        ct3 = _make_contact(db, tenant.id, "Both", email="b@test.com", linkedin_url="https://linkedin.com/in/y")
        _make_campaign_contact(db, campaign.id, ct3.id, tenant.id)

        # Contact with neither
        ct4 = _make_contact(db, tenant.id, "Neither")
        _make_campaign_contact(db, campaign.id, ct4.id, tenant.id)

        db.session.commit()

        resp = client.get(f"/api/campaigns/{campaign.id}/analytics", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["contacts"]["total"] == 4
        assert data["contacts"]["with_email"] == 2      # EmailOnly + Both
        assert data["contacts"]["with_linkedin"] == 2    # LinkedInOnly + Both
        assert data["contacts"]["both_channels"] == 1    # Both only


class TestCampaignAnalyticsCost:
    """Test cost aggregation from generation_config and messages."""

    def test_cost_from_generation_config(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]

        campaign = _make_campaign(
            db, tenant.id,
            gen_config={"cost": {"generation_usd": 1.25}},
        )
        db.session.commit()

        resp = client.get(f"/api/campaigns/{campaign.id}/analytics", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["cost"]["generation_usd"] == 1.25

    def test_cost_fallback_to_messages(self, client, seed_companies_contacts, db):
        """When generation_config has no cost, sum from messages."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]

        campaign = _make_campaign(db, tenant.id, gen_config={})
        ct1 = _make_contact(db, tenant.id, "Alice", email="a@test.com")
        cc1 = _make_campaign_contact(db, campaign.id, ct1.id, tenant.id)
        _make_message(db, tenant.id, ct1.id, cc1.id, cost=0.10)
        _make_message(db, tenant.id, ct1.id, cc1.id, step=2, cost=0.15)
        db.session.commit()

        resp = client.get(f"/api/campaigns/{campaign.id}/analytics", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert abs(data["cost"]["generation_usd"] - 0.25) < 0.01


class TestCampaignAnalyticsAuth:
    """Test authentication / authorization."""

    def test_auth_required(self, client, db):
        resp = client.get("/api/campaigns/some-id/analytics")
        assert resp.status_code == 401

    def test_campaign_not_found(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.get("/api/campaigns/00000000-0000-0000-0000-000000000000/analytics", headers=headers)
        assert resp.status_code == 404
        assert "not found" in resp.get_json()["error"].lower()


class TestCampaignAnalyticsLinkedIn:
    """Test LinkedIn send queue aggregation."""

    def test_linkedin_sending_stats(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        owner = seed_companies_contacts["owners"][0]

        campaign = _make_campaign(db, tenant.id)
        ct1 = _make_contact(db, tenant.id, "Alice", linkedin_url="https://linkedin.com/in/alice")
        cc1 = _make_campaign_contact(db, campaign.id, ct1.id, tenant.id)

        m1 = _make_message(db, tenant.id, ct1.id, cc1.id, channel="linkedin_connect", status="sent")
        m2 = _make_message(db, tenant.id, ct1.id, cc1.id, channel="linkedin_message", status="sent", step=2)

        # Queue entries
        db.session.add(LinkedInSendQueue(
            tenant_id=str(tenant.id),
            message_id=str(m1.id),
            contact_id=str(ct1.id),
            owner_id=str(owner.id),
            action_type="connection_request",
            linkedin_url="https://linkedin.com/in/alice",
            body="Hi",
            status="sent",
        ))
        db.session.add(LinkedInSendQueue(
            tenant_id=str(tenant.id),
            message_id=str(m2.id),
            contact_id=str(ct1.id),
            owner_id=str(owner.id),
            action_type="message",
            linkedin_url="https://linkedin.com/in/alice",
            body="Follow up",
            status="queued",
        ))
        db.session.commit()

        resp = client.get(f"/api/campaigns/{campaign.id}/analytics", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()

        li = data["sending"]["linkedin"]
        assert li["total"] == 2
        assert li["sent"] == 1
        assert li["queued"] == 1
