"""Unit tests for Resend webhook handler (BL-315 + BL-1034).

Covers:
- Each event type updates the correct EmailSendLog fields
- Duplicate events are idempotent (second open doesn't overwrite opened_at)
- Unknown event types return 200
- Missing EmailSendLog returns 200 (don't break on unknown email_id)
- Empty/invalid body returns 200
- Svix signature verification is fail-closed (BL-1034):
  - Missing RESEND_WEBHOOK_SECRET → 401
  - Invalid signature → 401
  - Valid signature → 200
  - Dev-bypass (FLASK_ENV=development + secret=dev-bypass) → 200

Tests that exercise event-handling logic (not signature verification)
run with the dev-bypass active via ``_dev_bypass_env`` so the handler
accepts unsigned payloads. This matches how the local dev server is
configured in ``scripts/init-env.sh``.
"""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Shared environment patches
# ---------------------------------------------------------------------------
# Tests that focus on handler logic (not signature verification) run with
# the dev-bypass active. This keeps the existing tests green under the new
# fail-closed default without inventing a valid signature for each test.
_DEV_BYPASS_ENV = {
    "FLASK_ENV": "development",
    "RESEND_WEBHOOK_SECRET": "dev-bypass",
}


@pytest.fixture
def dev_bypass_env(monkeypatch):
    """Activate the documented dev-only svix verification bypass."""
    for key, value in _DEV_BYPASS_ENV.items():
        monkeypatch.setenv(key, value)
    yield


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
    """Tests for POST /api/webhooks/resend.

    BL-1034: the webhook is now fail-closed on svix signature
    verification. Tests in this class focus on event-handling logic
    rather than signature verification and therefore run with the
    documented dev-only bypass active. Signature-specific behaviour is
    covered in ``TestResendWebhookSignature`` below.
    """

    @pytest.fixture(autouse=True)
    def _auto_dev_bypass(self, dev_bypass_env):
        """Activate the dev-bypass for every test in this class."""
        yield

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


# ---------------------------------------------------------------------------
# Svix signature verification (BL-1034 — fail-closed)
# ---------------------------------------------------------------------------
# The svix HMAC secret is "testsecret" base64-encoded, matching the value
# used by the existing ``whsec_dGVzdHNlY3JldA==`` fixture for readability.
_TEST_SECRET_PLAIN = b"testsecret"
_TEST_SECRET_ENV = "whsec_" + base64.b64encode(_TEST_SECRET_PLAIN).decode()


def _sign_svix(
    payload_bytes: bytes,
    svix_id: str = "msg_test",
    svix_timestamp: str = "1234567890",
    secret_bytes: bytes = _TEST_SECRET_PLAIN,
) -> dict:
    """Compute a valid svix v1 signature header set for ``payload_bytes``."""
    to_sign = f"{svix_id}.{svix_timestamp}.".encode() + payload_bytes
    digest = hmac.new(secret_bytes, to_sign, hashlib.sha256).digest()
    sig = base64.b64encode(digest).decode()
    return {
        "svix-id": svix_id,
        "svix-timestamp": svix_timestamp,
        "svix-signature": f"v1,{sig}",
    }


class TestResendWebhookSignature:
    """BL-1034 — svix signature verification is fail-closed.

    Covers the four acceptance criteria:
    - (a) no secret → 401
    - (b) bad signature → 401
    - (c) good signature → 200
    - (d) dev-bypass (FLASK_ENV=development + secret=dev-bypass) → 200
    """

    def test_missing_secret_returns_401(self, client, seed_send_log, monkeypatch):
        """No secret configured → fail-closed with 401 and critical log."""
        # Ensure both envs are fully unset for this test
        monkeypatch.delenv("RESEND_WEBHOOK_SECRET", raising=False)
        monkeypatch.delenv("FLASK_ENV", raising=False)

        payload = _webhook_payload("email.delivered")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 401
        assert resp.get_json() == {"error": "Invalid signature"}

    def test_empty_secret_returns_401(self, client, seed_send_log, monkeypatch):
        """Secret explicitly set to empty string → still fail-closed."""
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "")
        monkeypatch.delenv("FLASK_ENV", raising=False)

        payload = _webhook_payload("email.delivered")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_invalid_signature_returns_401(self, client, seed_send_log, monkeypatch):
        """Secret configured but signature invalid → 401."""
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", _TEST_SECRET_ENV)
        monkeypatch.delenv("FLASK_ENV", raising=False)

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
        assert resp.status_code == 401

    def test_missing_svix_headers_returns_401(self, client, seed_send_log, monkeypatch):
        """Secret configured but svix-* headers missing → 401."""
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", _TEST_SECRET_ENV)
        monkeypatch.delenv("FLASK_ENV", raising=False)

        payload = _webhook_payload("email.delivered")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_valid_signature_returns_200(self, client, seed_send_log, monkeypatch):
        """Secret configured and signature valid → handler accepts (200)."""
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", _TEST_SECRET_ENV)
        monkeypatch.delenv("FLASK_ENV", raising=False)

        payload = _webhook_payload("email.delivered")
        body = json.dumps(payload).encode()
        headers = _sign_svix(body)

        resp = client.post(
            "/api/webhooks/resend",
            data=body,
            content_type="application/json",
            headers=headers,
        )
        assert resp.status_code == 200

    def test_dev_bypass_accepts_unsigned_payload(
        self, client, seed_send_log, monkeypatch
    ):
        """FLASK_ENV=development + secret=dev-bypass → skip verification."""
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "dev-bypass")

        payload = _webhook_payload("email.delivered")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_dev_bypass_requires_flask_env_development(
        self, client, seed_send_log, monkeypatch
    ):
        """secret=dev-bypass alone (no FLASK_ENV) must NOT skip verification.

        This is defence-in-depth: an operator who accidentally deploys
        with ``RESEND_WEBHOOK_SECRET=dev-bypass`` in staging or prod
        gets a 401 rather than silent acceptance.
        """
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "dev-bypass")
        monkeypatch.setenv("FLASK_ENV", "staging")

        payload = _webhook_payload("email.delivered")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        # "dev-bypass" is treated as a normal secret here, and with no
        # svix headers the verification fails.
        assert resp.status_code == 401

    def test_dev_bypass_token_not_special_in_production(
        self, client, seed_send_log, monkeypatch
    ):
        """FLASK_ENV=production + secret=dev-bypass → still 401."""
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "dev-bypass")

        payload = _webhook_payload("email.delivered")
        resp = client.post(
            "/api/webhooks/resend",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 401
