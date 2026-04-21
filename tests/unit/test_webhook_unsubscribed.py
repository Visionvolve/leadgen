"""Unit tests for the Resend `email.unsubscribed` webhook (Phase 2 Task 3).

Covers:
1. POST /api/webhooks/resend with type=email.unsubscribed sets
   EmailSendLog.unsubscribed_at and status='unsubscribed'.
2. Unknown email_id returns 200 (no 500, no Resend retry storm).
3. Invalid svix signature returns 401 when RESEND_WEBHOOK_SECRET is set
   (fail-closed — BL-1034).

Event-handling tests mock ``_verify_svix_signature`` at the import site
so they do not need to compute valid svix signatures. There is no
dev-bypass path in production code (BL-1034 review gate). Signature
behaviour is covered separately in
``test_webhook_routes.py::TestResendWebhookSignature``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

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
    """POST /api/webhooks/resend with type=email.unsubscribed.

    Event-handling tests mock ``_verify_svix_signature`` at the import
    site so they can focus on handler behaviour rather than HMAC math.
    There is no dev-bypass in production code.
    """

    @pytest.fixture(autouse=True)
    def _mock_signature_ok(self, monkeypatch):
        """Stub out signature verification for event-handling tests."""
        monkeypatch.setattr(
            "api.routes.webhook_routes._verify_svix_signature",
            lambda payload_bytes, headers: True,
        )
        yield

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


class TestUnsubscribedWebhookSignature:
    """BL-1034: signature verification is exercised against unsubscribe events.

    This class does NOT mock the verification function — it runs the
    real ``_verify_svix_signature`` against a configured secret.
    """

    def test_unsubscribed_invalid_signature_returns_401(
        self, client, seed_send_log, monkeypatch
    ):
        """Invalid svix signature → 401 (fail-closed)."""
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "whsec_dGVzdHNlY3JldA==")

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
        assert resp.status_code == 401
