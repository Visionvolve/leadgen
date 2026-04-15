"""Unit tests for Resend webhook handler (BL-315).

Covers:
- Each event type updates the correct EmailSendLog fields
- Duplicate events are idempotent (second open doesn't overwrite opened_at)
- Unknown event types return 200
- Missing EmailSendLog returns 200 (don't break on unknown email_id)
- Empty/invalid body returns 200
- Svix signature verification (when secret configured)
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def seed_send_log(db, seed_tenant):
    """Create a minimal EmailSendLog record for webhook testing."""
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
        first_name="Jan",
        last_name="Novak",
        email_address="jan@example.com",
    )
    db.session.add(contact)
    db.session.flush()

    campaign = Campaign(
        tenant_id=tenant_id,
        name="Webhook Test Campaign",
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
        subject="Test Subject",
        body="Hello Jan",
        status="approved",
        campaign_contact_id=cc.id,
    )
    db.session.add(message)
    db.session.flush()

    log = EmailSendLog(
        tenant_id=tenant_id,
        message_id=message.id,
        resend_message_id="resend-test-id-001",
        status="sent",
        from_email="outreach@test.com",
        to_email="jan@example.com",
        sent_at=datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    db.session.add(log)
    db.session.commit()

    return {
        "log": log,
        "message": message,
        "contact": contact,
        "tenant": seed_tenant,
    }


def _webhook_payload(event_type, email_id="resend-test-id-001", extra_data=None):
    """Build a Resend webhook payload."""
    data = {"email_id": email_id, "to": ["jan@example.com"]}
    if extra_data:
        data.update(extra_data)
    return {"type": event_type, "data": data}


class TestResendWebhook:
    """Tests for POST /api/webhooks/resend."""

    def test_delivered_event(self, client, seed_send_log):
        """email.delivered sets delivered_at and status."""
        payload = _webhook_payload("email.delivered")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        assert log.status == "delivered"
        assert log.delivered_at is not None

    def test_opened_event_first_open(self, client, seed_send_log):
        """email.opened sets opened_at and increments open_count."""
        payload = _webhook_payload("email.opened")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        assert log.opened_at is not None
        assert log.open_count == 1

    def test_opened_event_idempotent(self, client, seed_send_log):
        """Second open increments count but doesn't overwrite opened_at."""
        payload = _webhook_payload("email.opened")

        # First open
        client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        first_opened_at = log.opened_at

        # Second open
        client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )

        db.session.refresh(log)
        assert log.opened_at == first_opened_at  # Not overwritten
        assert log.open_count == 2  # Incremented

    def test_clicked_event_first_click(self, client, seed_send_log):
        """email.clicked sets clicked_at and increments click_count."""
        payload = _webhook_payload("email.clicked")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        assert log.clicked_at is not None
        assert log.click_count == 1

    def test_clicked_event_idempotent(self, client, seed_send_log):
        """Second click increments count but doesn't overwrite clicked_at."""
        payload = _webhook_payload("email.clicked")

        client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        first_clicked_at = log.clicked_at

        client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )

        db.session.refresh(log)
        assert log.clicked_at == first_clicked_at
        assert log.click_count == 2

    def test_bounced_event(self, client, seed_send_log):
        """email.bounced sets bounced_at, bounce_type, and status."""
        payload = _webhook_payload(
            "email.bounced",
            extra_data={"bounce": {"type": "hard"}},
        )
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        assert log.status == "bounced"
        assert log.bounced_at is not None
        assert log.bounce_type == "hard"

    def test_complained_event(self, client, seed_send_log):
        """email.complained sets complained_at and status."""
        payload = _webhook_payload("email.complained")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        assert log.status == "complained"
        assert log.complained_at is not None

    def test_unknown_event_returns_200(self, client, seed_send_log):
        """Unknown event types return 200 (don't break Resend retries)."""
        payload = _webhook_payload("email.unknown_event")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ignored"

    def test_missing_email_id_returns_200(self, client, seed_send_log):
        """Missing email_id in data returns 200."""
        payload = {"type": "email.delivered", "data": {"to": ["jan@example.com"]}}
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ignored"

    def test_unknown_email_id_returns_200(self, client, seed_send_log):
        """Unknown resend_message_id returns 200 (no matching log)."""
        payload = _webhook_payload("email.delivered", email_id="nonexistent-id")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ignored"
        assert data["reason"] == "unknown email_id"

    def test_empty_body_returns_200(self, client, db):
        """Empty body returns 200."""
        resp = client.post(
            "/api/webhooks/resend",
            data="",
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_no_auth_required(self, client, seed_send_log):
        """Webhook endpoint works without any auth headers."""
        payload = _webhook_payload("email.delivered")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
            # No Authorization header
        )
        assert resp.status_code == 200

    @patch.dict("os.environ", {"RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA=="})
    def test_invalid_signature_returns_400(self, client, seed_send_log):
        """Invalid svix signature returns 400 when secret is configured."""
        payload = _webhook_payload("email.delivered")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
            headers={
                "svix-id": "msg_test",
                "svix-timestamp": "1234567890",
                "svix-signature": "v1,invalidsignature",
            },
        )
        assert resp.status_code == 400

    @patch.dict("os.environ", {"RESEND_WEBHOOK_SECRET": ""})
    def test_no_secret_skips_verification(self, client, seed_send_log):
        """No webhook secret configured means verification is skipped."""
        payload = _webhook_payload("email.delivered")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_bounced_soft(self, client, seed_send_log):
        """Soft bounce sets bounce_type to 'soft'."""
        payload = _webhook_payload(
            "email.bounced",
            extra_data={"bounce": {"type": "soft"}},
        )
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        assert log.bounce_type == "soft"
