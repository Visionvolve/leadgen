"""Unit tests for the Resend `email.unsubscribed` webhook (Phase 2 Task 3).

Covers:
1. POST /api/webhooks/resend with type=email.unsubscribed sets
   EmailSendLog.unsubscribed_at and status='unsubscribed'.
2. Unknown email_id returns 200 (no 500, no Resend retry storm).
3. Invalid svix signature returns 400 when RESEND_WEBHOOK_SECRET is set.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def seed_send_log(db, seed_tenant):
    """Create a minimal EmailSendLog row for unsubscribe webhook testing."""
    from api.models import (
        Campaign,
        CampaignContact,
        Contact,
        EmailSendLog,
        Message,
        Owner,
    )

    tenant_id = seed_tenant.id

    owner = Owner(tenant_id=tenant_id, name="Test Owner")
    db.session.add(owner)
    db.session.flush()

    contact = Contact(
        tenant_id=tenant_id,
        first_name="Hana",
        last_name="Novakova",
        email_address="hana@example.com",
    )
    db.session.add(contact)
    db.session.flush()

    campaign = Campaign(
        tenant_id=tenant_id,
        name="Unsubscribe Test Campaign",
        status="sending",
    )
    db.session.add(campaign)
    db.session.flush()

    cc = CampaignContact(
        campaign_id=campaign.id,
        contact_id=contact.id,
        tenant_id=tenant_id,
        status="sent",
    )
    db.session.add(cc)
    db.session.flush()

    message = Message(
        tenant_id=tenant_id,
        contact_id=contact.id,
        owner_id=owner.id,
        channel="email",
        sequence_step=1,
        variant="a",
        subject="Test",
        body="Test body",
        status="approved",
        campaign_contact_id=cc.id,
    )
    db.session.add(message)
    db.session.flush()

    log = EmailSendLog(
        tenant_id=tenant_id,
        message_id=message.id,
        resend_message_id="resend-unsub-id-001",
        status="delivered",
        from_email="outreach@test.com",
        to_email="hana@example.com",
        sent_at=datetime(2026, 4, 10, 10, 0, 0, tzinfo=timezone.utc),
        delivered_at=datetime(2026, 4, 10, 10, 0, 30, tzinfo=timezone.utc),
    )
    db.session.add(log)
    db.session.commit()

    return {"log": log, "message": message, "contact": contact}


def _payload(event_type, email_id="resend-unsub-id-001"):
    return {"type": event_type, "data": {"email_id": email_id}}


class TestUnsubscribedWebhook:
    """POST /api/webhooks/resend with type=email.unsubscribed."""

    def test_unsubscribed_sets_timestamp_and_status(self, client, seed_send_log):
        """Test 1: matching log → unsubscribed_at populated, status='unsubscribed'."""
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(_payload("email.unsubscribed")),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        assert log.unsubscribed_at is not None
        assert log.status == "unsubscribed"

    def test_unsubscribed_unknown_email_id_returns_200(self, client, seed_send_log):
        """Test 2: unknown email_id → 200 with reason 'unknown email_id'."""
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(_payload("email.unsubscribed", email_id="not-a-real-id")),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ignored"
        assert body["reason"] == "unknown email_id"

    @patch.dict("os.environ", {"RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA=="})
    def test_unsubscribed_invalid_signature_returns_400(self, client, seed_send_log):
        """Test 3: invalid svix signature → 400 (parity with existing 5 events)."""
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(_payload("email.unsubscribed")),
            content_type="application/json",
            headers={
                "svix-id": "msg_test",
                "svix-timestamp": "1234567890",
                "svix-signature": "v1,invalidsignature",
            },
        )
        assert resp.status_code == 400
