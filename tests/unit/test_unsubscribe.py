"""Unit tests for the Unsubscribe Loop (BL-1103, BL-1105 — Milestone v25 Phase 3).

Covers:
1. Webhook-driven suppression on email.unsubscribed / hard-bounce / complaint
2. Send-side suppression gate filters out is_suppressed contacts
3. Public POST /api/unsubscribe with HMAC token marks + sends confirmation
4. POST is idempotent (no duplicate confirmation email)
5. Invalid / cross-tenant tokens are rejected with 403
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seed_send_log(db, seed_tenant):
    """Minimal Tenant + Contact + Campaign + Message + EmailSendLog graph."""
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
        resend_message_id="resend-msg-unsub-001",
        status="delivered",
        from_email="outreach@test.com",
        to_email="hana@example.com",
        sent_at=datetime(2026, 4, 10, 10, 0, 0, tzinfo=timezone.utc),
        delivered_at=datetime(2026, 4, 10, 10, 0, 30, tzinfo=timezone.utc),
    )
    db.session.add(log)
    db.session.commit()

    return {
        "tenant_id": tenant_id,
        "owner": owner,
        "contact": contact,
        "campaign": campaign,
        "campaign_contact": cc,
        "message": message,
        "log": log,
    }


# ---------------------------------------------------------------------------
# 1. Webhook-driven suppression
# ---------------------------------------------------------------------------


class TestWebhookSuppression:
    """Webhook handler flips Contact.is_suppressed + writes Activity audit."""

    @pytest.fixture(autouse=True)
    def _mock_signature_ok(self, monkeypatch):
        monkeypatch.setattr(
            "api.routes.webhook_routes._verify_svix_signature",
            lambda payload_bytes, headers: True,
        )

    def _post(
        self, client, event_type, email_id="resend-msg-unsub-001", extra_data=None
    ):
        data = {"email_id": email_id}
        if extra_data:
            data.update(extra_data)
        return client.post(
            "/api/webhooks/resend",
            data=json.dumps({"type": event_type, "data": data}),
            content_type="application/json",
        )

    def test_webhook_unsubscribed_suppresses_contact(self, client, seed_send_log):
        resp = self._post(client, "email.unsubscribed")
        assert resp.status_code == 200

        from api.models import Activity, Contact, db

        contact = db.session.get(Contact, seed_send_log["contact"].id)
        assert contact.is_suppressed is True
        assert contact.suppressed_at is not None
        assert contact.suppression_reason == "resend_webhook"

        activity = (
            db.session.query(Activity)
            .filter_by(contact_id=contact.id, event_type="contact.unsubscribed")
            .first()
        )
        assert activity is not None
        assert activity.activity_type == "event"

    def test_webhook_hard_bounce_suppresses(self, client, seed_send_log):
        resp = self._post(
            client,
            "email.bounced",
            extra_data={"bounce": {"type": "hard"}},
        )
        assert resp.status_code == 200

        from api.models import Contact, db

        contact = db.session.get(Contact, seed_send_log["contact"].id)
        assert contact.is_suppressed is True
        assert contact.suppression_reason == "hard_bounce"

    def test_webhook_soft_bounce_does_not_suppress(self, client, seed_send_log):
        resp = self._post(
            client,
            "email.bounced",
            extra_data={"bounce": {"type": "soft"}},
        )
        assert resp.status_code == 200

        from api.models import Contact, db

        contact = db.session.get(Contact, seed_send_log["contact"].id)
        assert contact.is_suppressed is False
        assert contact.suppression_reason is None

    def test_webhook_complained_suppresses(self, client, seed_send_log):
        resp = self._post(client, "email.complained")
        assert resp.status_code == 200

        from api.models import Contact, db

        contact = db.session.get(Contact, seed_send_log["contact"].id)
        assert contact.is_suppressed is True
        assert contact.suppression_reason == "spam_complaint"

    def test_webhook_unsubscribed_idempotent(self, client, seed_send_log):
        """Replay of the same webhook does not duplicate suppressed_at."""
        resp1 = self._post(client, "email.unsubscribed")
        assert resp1.status_code == 200

        from api.models import Activity, Contact, db

        first_suppressed_at = db.session.get(
            Contact, seed_send_log["contact"].id
        ).suppressed_at

        # Replay
        resp2 = self._post(client, "email.unsubscribed")
        assert resp2.status_code == 200

        contact_after = db.session.get(Contact, seed_send_log["contact"].id)
        assert contact_after.suppressed_at == first_suppressed_at  # earliest wins

        # Only one Activity row
        activities = (
            db.session.query(Activity)
            .filter_by(contact_id=contact_after.id, event_type="contact.unsubscribed")
            .all()
        )
        assert len(activities) == 1


# ---------------------------------------------------------------------------
# 2. Send-side suppression filter
# ---------------------------------------------------------------------------


class TestSendSideFilter:
    """send_campaign_emails must skip suppressed contacts."""

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_send_side_filter_excludes_suppressed(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        import json as _json

        from api.models import Campaign, CampaignContact, Message, Tenant

        seed = seed_companies_contacts
        tenant_id = seed["tenant"].id

        # Configure Resend key
        tenant = db.session.get(Tenant, tenant_id)
        tenant.settings = _json.dumps({"resend_api_key": "re_test_key"})

        owner = seed["owners"][0]

        # Build a campaign with 2 approved-email messages
        sender_config = {
            "from_email": "outreach@test.com",
            "from_name": "Test",
            "reply_to": "reply@test.com",
        }
        campaign = Campaign(
            tenant_id=tenant_id,
            name="Suppression filter test",
            status="review",
            sender_config=_json.dumps(sender_config),
        )
        db.session.add(campaign)
        db.session.flush()

        # Find 2 contacts with email addresses
        contacts_with_email = [c for c in seed["contacts"] if c.email_address][:2]
        assert len(contacts_with_email) == 2

        # Mark one suppressed
        suppressed = contacts_with_email[0]
        suppressed.is_suppressed = True
        suppressed.suppressed_at = datetime.now(timezone.utc)
        suppressed.suppression_reason = "manual"

        for c in contacts_with_email:
            cc = CampaignContact(
                campaign_id=campaign.id,
                contact_id=c.id,
                tenant_id=tenant_id,
                status="generated",
            )
            db.session.add(cc)
            db.session.flush()
            m = Message(
                tenant_id=tenant_id,
                contact_id=c.id,
                owner_id=owner.id,
                channel="email",
                sequence_step=1,
                variant="a",
                subject="hi",
                body="body",
                status="approved",
                campaign_contact_id=cc.id,
            )
            db.session.add(m)
        db.session.commit()

        mock_send.return_value = {"id": "resend_msg_x"}

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            result = send_campaign_emails(str(campaign.id), str(tenant_id))

        # Only the non-suppressed contact got a send call
        assert mock_send.call_count == 1
        assert result["sent_count"] == 1
        assert result["total"] == 1

        # The suppressed contact has no EmailSendLog row from this campaign
        from api.models import EmailSendLog

        suppressed_logs = (
            db.session.query(EmailSendLog)
            .filter_by(to_email=suppressed.email_address)
            .all()
        )
        # No sent rows for the suppressed recipient created by this send pass
        assert all(
            log.status not in ("queued", "sent", "delivered") for log in suppressed_logs
        )


# ---------------------------------------------------------------------------
# 3-5. Public POST /api/unsubscribe endpoint
# ---------------------------------------------------------------------------


class TestUnsubscribeEndpoint:
    """Public unsubscribe endpoint — HMAC token + confirmation email."""

    def _token_for(self, app, contact):
        with app.test_request_context("/"):
            from api.routes.unsubscribe_routes import generate_unsubscribe_token

            return generate_unsubscribe_token(contact)

    def test_unsubscribe_post_marks_suppressed_and_sends_confirmation(
        self, client, app, db, seed_send_log
    ):
        # Configure Resend key so the confirmation email can be dispatched.
        import json as _json

        from api.models import Tenant

        tenant = db.session.get(Tenant, seed_send_log["tenant_id"])
        tenant.settings = _json.dumps(
            {
                "resend_api_key": "re_test_key",
                "sender_config": {
                    "from_email": "outreach@test.com",
                    "from_name": "Test",
                },
            }
        )
        db.session.commit()

        contact = seed_send_log["contact"]
        token = self._token_for(app, contact)

        with patch("api.services.send_service._send_single_email") as mock_send:
            mock_send.return_value = {"id": "confirm_resend_id"}

            resp = client.post(
                "/api/unsubscribe",
                data={"contact_id": contact.id, "token": token},
            )

        assert resp.status_code == 200

        from api.models import Activity, Contact

        c = db.session.get(Contact, contact.id)
        assert c.is_suppressed is True
        assert c.suppressed_at is not None
        assert c.suppression_reason == "user_one_click"

        # Confirmation email dispatched exactly once
        assert mock_send.call_count == 1
        # And to the right recipient
        sent_kwargs = mock_send.call_args.kwargs
        assert sent_kwargs["to_email"] == contact.email_address
        assert "Unsubscribed" in sent_kwargs["subject"]

        # Activity audit row
        activities = (
            db.session.query(Activity)
            .filter_by(contact_id=contact.id, event_type="contact.unsubscribed")
            .all()
        )
        assert len(activities) == 1

    def test_unsubscribe_post_idempotent_does_not_resend(
        self, client, app, db, seed_send_log
    ):
        import json as _json

        from api.models import Tenant

        tenant = db.session.get(Tenant, seed_send_log["tenant_id"])
        tenant.settings = _json.dumps(
            {
                "resend_api_key": "re_test_key",
                "sender_config": {
                    "from_email": "outreach@test.com",
                    "from_name": "Test",
                },
            }
        )
        db.session.commit()

        contact = seed_send_log["contact"]
        token = self._token_for(app, contact)

        with patch("api.services.send_service._send_single_email") as mock_send:
            mock_send.return_value = {"id": "confirm_resend_id"}
            r1 = client.post(
                "/api/unsubscribe",
                data={"contact_id": contact.id, "token": token},
            )
            r2 = client.post(
                "/api/unsubscribe",
                data={"contact_id": contact.id, "token": token},
            )

        assert r1.status_code == 200
        assert r2.status_code == 200

        # Send was called exactly once across both POSTs
        assert mock_send.call_count == 1

        # Still exactly one Activity row
        from api.models import Activity

        activities = (
            db.session.query(Activity)
            .filter_by(contact_id=contact.id, event_type="contact.unsubscribed")
            .all()
        )
        assert len(activities) == 1

    def test_unsubscribe_token_invalid_403(self, client, app, db, seed_send_log):
        contact = seed_send_log["contact"]
        resp = client.post(
            "/api/unsubscribe",
            data={"contact_id": contact.id, "token": "obviouslybogus"},
        )
        assert resp.status_code == 403

        # Contact NOT suppressed
        from api.models import Contact

        c = db.session.get(Contact, contact.id)
        assert c.is_suppressed is False

    def test_unsubscribe_token_cross_tenant_403(self, client, app, db, seed_send_log):
        """Token signed for a different (contact,tenant) pair must be rejected."""
        from api.models import Contact, Tenant

        # Make a second tenant + a contact in it
        other_tenant = Tenant(name="Other Corp", slug="other-corp", is_active=True)
        db.session.add(other_tenant)
        db.session.flush()

        attacker = Contact(
            tenant_id=other_tenant.id,
            first_name="Eve",
            last_name="X",
            email_address="eve@other.com",
        )
        db.session.add(attacker)
        db.session.commit()

        # Mint a token for the attacker's (contact,tenant) pair
        attacker_token = self._token_for(app, attacker)

        # But submit it against the FIRST tenant's contact_id
        victim = seed_send_log["contact"]
        resp = client.post(
            "/api/unsubscribe",
            data={"contact_id": victim.id, "token": attacker_token},
        )
        assert resp.status_code == 403

        victim_after = db.session.get(Contact, victim.id)
        assert victim_after.is_suppressed is False

    def test_unsubscribe_token_for_other_contact_in_same_tenant_403(
        self, client, app, db, seed_send_log
    ):
        """Token bound to contact A cannot be used to suppress contact B."""
        from api.models import Contact

        other = Contact(
            tenant_id=seed_send_log["tenant_id"],
            first_name="Carol",
            last_name="X",
            email_address="carol@example.com",
        )
        db.session.add(other)
        db.session.commit()

        # Token for `other` ...
        other_token = self._token_for(app, other)

        # ... submitted against `seed_send_log['contact']`
        resp = client.post(
            "/api/unsubscribe",
            data={"contact_id": seed_send_log["contact"].id, "token": other_token},
        )
        assert resp.status_code == 403

        from api.models import Contact as _Contact

        original = db.session.get(_Contact, seed_send_log["contact"].id)
        assert original.is_suppressed is False

    def test_unsubscribe_get_renders_confirmation_page(
        self, client, app, seed_send_log
    ):
        contact = seed_send_log["contact"]
        token = self._token_for(app, contact)

        resp = client.get(f"/api/unsubscribe?contact_id={contact.id}&token={token}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Confirm unsubscribe" in body or "Unsubscribe" in body

        # GET must NOT suppress the contact
        from api.models import Contact, db as _db

        c = _db.session.get(Contact, contact.id)
        assert c.is_suppressed is False


# ---------------------------------------------------------------------------
# Bad-input handling — hotfix for the 500 reported on staging (BL hotfix
# 2026-05-12).  Every malformed-input path must return a 4xx, never a 500,
# even when the request bypasses the dashboard (e.g. a corporate link scanner
# fetching a tampered URL).
# ---------------------------------------------------------------------------


class TestUnsubscribeBadInput:
    """The endpoint must never 500 on garbage input."""

    def test_get_invalid_contact_id_format_returns_400(self, client):
        resp = client.get(
            "/api/unsubscribe?contact_id=not-a-uuid&token=whatever",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "invalid_contact_id"}

    def test_get_missing_contact_id_returns_400(self, client):
        resp = client.get(
            "/api/unsubscribe?token=whatever",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 400

    def test_get_nil_uuid_returns_404(self, client):
        """The all-zeros UUID is well-formed but won't exist — must be 404."""
        resp = client.get(
            "/api/unsubscribe?contact_id=00000000-0000-0000-0000-000000000000"
            "&token=bogus",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "not_found"}

    def test_post_invalid_contact_id_format_returns_400(self, client):
        resp = client.post(
            "/api/unsubscribe",
            data={"contact_id": "not-a-uuid", "token": "whatever"},
        )
        assert resp.status_code == 400

    def test_post_nil_uuid_returns_404(self, client):
        resp = client.post(
            "/api/unsubscribe",
            data={
                "contact_id": "00000000-0000-0000-0000-000000000000",
                "token": "bogus",
            },
        )
        assert resp.status_code == 404

    def test_get_html_response_for_bad_input(self, client):
        """Browsers (no Accept: json) get the HTML error page, still 400."""
        resp = client.get(
            "/api/unsubscribe?contact_id=not-a-uuid&token=whatever",
        )
        assert resp.status_code == 400
        body = resp.get_data(as_text=True)
        assert "invalid" in body.lower() or "expired" in body.lower()
