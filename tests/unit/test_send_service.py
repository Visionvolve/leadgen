"""Unit tests for the Resend email send service (Task 6).

Covers:
- Email dispatch via Resend API (mocked)
- Idempotent send (skips already-sent messages)
- Failure handling (one email fails, others continue)
- Missing sender_config returns 400
- Non-email messages excluded
- Send-status endpoint
- Daily/hourly quota enforcement
- Warm-up schedule
- Send delay with jitter
- List-Unsubscribe header (CAN-SPAM)
- Pre-send email validation
- Quota info in send-status response
"""

import json
from unittest.mock import patch

import pytest

from tests.conftest import auth_header


def _setup_campaign_with_approved_emails(db, seed, msg_count=3, include_linkedin=False):
    """Create a campaign with approved email messages and sender_config.

    Returns (campaign, messages, contacts_used).
    """
    from api.models import Campaign, CampaignContact, Message

    tenant_id = seed["tenant"].id
    owner = seed["owners"][0]

    sender_config = {
        "from_email": "outreach@test.com",
        "from_name": "Test Outreach",
        "reply_to": "replies@test.com",
    }
    campaign = Campaign(
        tenant_id=tenant_id,
        name="Send Test Campaign",
        status="review",
        sender_config=json.dumps(sender_config),
    )
    db.session.add(campaign)
    db.session.flush()

    messages = []
    contacts_used = []
    for i in range(min(msg_count, len(seed["contacts"]))):
        contact = seed["contacts"][i]
        contacts_used.append(contact)
        cc = CampaignContact(
            campaign_id=campaign.id,
            contact_id=contact.id,
            tenant_id=tenant_id,
            status="generated",
        )
        db.session.add(cc)
        db.session.flush()

        m = Message(
            tenant_id=tenant_id,
            contact_id=contact.id,
            owner_id=owner.id,
            channel="email",
            sequence_step=1,
            variant="a",
            subject=f"Subject for {contact.first_name}",
            body=f"Hello {contact.first_name}, this is a test message.",
            status="approved",
            campaign_contact_id=cc.id,
        )
        db.session.add(m)
        messages.append(m)

    if include_linkedin:
        # Add a linkedin message that should be excluded from email send
        contact = seed["contacts"][0]
        cc_existing = db.session.execute(
            db.text("""
                SELECT id FROM campaign_contacts
                WHERE campaign_id = :cid AND contact_id = :ctid
            """),
            {"cid": campaign.id, "ctid": contact.id},
        ).fetchone()
        cc_id = cc_existing[0] if cc_existing else None

        if cc_id:
            li_msg = Message(
                tenant_id=tenant_id,
                contact_id=contact.id,
                owner_id=owner.id,
                channel="linkedin_connect",
                sequence_step=1,
                variant="a",
                body="Let's connect!",
                status="approved",
                campaign_contact_id=cc_id,
            )
            db.session.add(li_msg)

    db.session.flush()
    db.session.commit()
    return campaign, messages, contacts_used


def _setup_tenant_with_resend_key(db, seed, extra_settings=None):
    """Configure the test tenant with a Resend API key and optional settings."""
    from api.models import Tenant

    tenant = db.session.get(Tenant, seed["tenant"].id)
    settings = {"resend_api_key": "re_test_key_123"}
    if extra_settings:
        settings.update(extra_settings)
    tenant.settings = json.dumps(settings)
    db.session.commit()


class TestSendCampaignEmails:
    """Unit tests for send_campaign_emails service function."""

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_send_dispatches_all_approved(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """Approved email messages are dispatched via Resend."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(db, seed)
        campaign, messages, contacts = _setup_campaign_with_approved_emails(
            db, seed, msg_count=3
        )

        # Mock Resend response
        mock_send.return_value = {"id": "resend_msg_001"}

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            result = send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        # Only contacts with email addresses should be sent
        contacts_with_email = [c for c in contacts if c.email_address]
        assert result["sent_count"] == len(contacts_with_email)
        assert result["total"] == len(contacts)
        assert mock_send.call_count == len(contacts_with_email)

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_send_idempotent_skips_already_sent(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """Re-sending skips messages that already have a non-failed EmailSendLog."""
        from api.models import EmailSendLog

        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(db, seed)
        campaign, messages, contacts = _setup_campaign_with_approved_emails(
            db, seed, msg_count=2
        )

        # Pre-create a "sent" log for the first message
        log = EmailSendLog(
            tenant_id=seed["tenant"].id,
            message_id=messages[0].id,
            resend_message_id="re_already_sent",
            status="sent",
            from_email="outreach@test.com",
            to_email=contacts[0].email_address or "test@test.com",
        )
        db.session.add(log)
        db.session.commit()

        mock_send.return_value = {"id": "resend_msg_002"}

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            result = send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        assert result["skipped_count"] >= 1
        # The first message was skipped, so send_count should be less
        assert result["sent_count"] < len(messages)

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_send_handles_failure_gracefully(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """Failed sends are logged but don't stop other sends."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(db, seed)
        campaign, messages, contacts = _setup_campaign_with_approved_emails(
            db, seed, msg_count=3
        )

        # First call succeeds, second raises, third succeeds
        call_count = [0]

        def side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("Resend API error: rate limit exceeded")
            return {"id": f"resend_msg_{call_count[0]:03d}"}

        mock_send.side_effect = side_effect

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            result = send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        # At least one should have succeeded and at least one failed
        assert result["sent_count"] >= 1
        assert result["failed_count"] >= 1
        # Total should account for all attempts
        assert (
            result["total"]
            == result["sent_count"] + result["failed_count"] + result["skipped_count"]
        )

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_send_excludes_non_email_messages(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """LinkedIn messages are not sent via Resend."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(db, seed)
        campaign, messages, contacts = _setup_campaign_with_approved_emails(
            db, seed, msg_count=2, include_linkedin=True
        )

        mock_send.return_value = {"id": "resend_msg_001"}

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        # Only email messages should be sent, not linkedin
        for call_args in mock_send.call_args_list:
            # verify we never tried to send a linkedin message
            assert "connect" not in str(call_args).lower()

    def test_send_raises_on_missing_sender_config(
        self, app, db, seed_companies_contacts
    ):
        """send_campaign_emails raises when sender_config has no from_email."""
        from api.models import Campaign

        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(db, seed)
        tenant_id = seed["tenant"].id

        # Campaign with empty sender_config
        campaign = Campaign(
            tenant_id=tenant_id,
            name="No Sender Campaign",
            status="review",
            sender_config=json.dumps({}),
        )
        db.session.add(campaign)
        db.session.commit()

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            with pytest.raises(ValueError, match="missing from_email"):
                send_campaign_emails(str(campaign.id), str(tenant_id))

    def test_send_raises_on_missing_api_key(self, app, db, seed_companies_contacts):
        """send_campaign_emails raises when tenant has no resend_api_key."""
        seed = seed_companies_contacts
        tenant_id = seed["tenant"].id

        # Create campaign with valid sender config but NO Resend API key on tenant
        campaign_data = _setup_campaign_with_approved_emails(db, seed, msg_count=1)
        campaign = campaign_data[0]

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            with pytest.raises(ValueError, match="resend_api_key"):
                send_campaign_emails(str(campaign.id), str(tenant_id))


class TestQuotaEnforcement:
    """Tests for daily/hourly send quota enforcement."""

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    @patch("api.services.send_service._count_sent_today")
    def test_daily_quota_blocks_send(
        self, mock_count_today, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """Sending is blocked when daily quota is reached."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(
            db,
            seed,
            extra_settings={
                "send_limits": {"daily": 50, "hourly": 30, "warmup_enabled": False}
            },
        )
        campaign, messages, _ = _setup_campaign_with_approved_emails(
            db, seed, msg_count=2
        )

        # Pretend 50 emails already sent today
        mock_count_today.return_value = 50

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            result = send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        assert result["quota_stopped"] is True
        assert result["sent_count"] == 0
        assert "Daily send limit" in result.get("quota_message", "")
        mock_send.assert_not_called()

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    @patch("api.services.send_service._count_sent_this_hour")
    def test_hourly_quota_blocks_send(
        self, mock_count_hour, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """Sending is blocked when hourly quota is reached."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(
            db,
            seed,
            extra_settings={
                "send_limits": {"daily": 100, "hourly": 10, "warmup_enabled": False}
            },
        )
        campaign, messages, _ = _setup_campaign_with_approved_emails(
            db, seed, msg_count=2
        )

        # Pretend 10 emails sent this hour
        mock_count_hour.return_value = 10

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            result = send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        assert result["quota_stopped"] is True
        assert result["sent_count"] == 0
        assert "Hourly send limit" in result.get("quota_message", "")
        mock_send.assert_not_called()

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_tenant_configurable_limits(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """Tenant-specific send limits are respected."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(
            db,
            seed,
            extra_settings={
                "send_limits": {
                    "daily": 200,
                    "hourly": 50,
                    "delay_seconds": 5,
                    "warmup_enabled": False,
                }
            },
        )
        campaign, messages, contacts = _setup_campaign_with_approved_emails(
            db, seed, msg_count=2
        )
        mock_send.return_value = {"id": "resend_msg_001"}

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            result = send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        # Should succeed since we're well under 200 daily / 50 hourly
        contacts_with_email = [c for c in contacts if c.email_address]
        assert result["sent_count"] == len(contacts_with_email)
        assert result.get("quota_stopped") is False


class TestWarmupSchedule:
    """Tests for warm-up schedule enforcement."""

    def test_warmup_limit_day_1(self, app):
        """Day 1 warm-up limit is 20."""
        from api.services.send_service import _get_warmup_limit

        assert _get_warmup_limit(1) == 20

    def test_warmup_limit_day_5(self, app):
        """Day 5 warm-up limit is 100."""
        from api.services.send_service import _get_warmup_limit

        assert _get_warmup_limit(5) == 100

    def test_warmup_limit_day_14(self, app):
        """Day 14 warm-up limit is 300."""
        from api.services.send_service import _get_warmup_limit

        assert _get_warmup_limit(14) == 300

    def test_warmup_limit_day_30_plus(self, app):
        """Day 30+ warm-up limit is 500."""
        from api.services.send_service import _get_warmup_limit

        assert _get_warmup_limit(30) == 500
        assert _get_warmup_limit(60) == 500

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    @patch("api.services.send_service._get_warmup_day")
    @patch("api.services.send_service._count_sent_today")
    def test_warmup_caps_daily_limit(
        self,
        mock_count_today,
        mock_warmup_day,
        mock_send,
        mock_sleep,
        app,
        db,
        seed_companies_contacts,
    ):
        """Warm-up limit overrides daily limit when it's lower."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(
            db,
            seed,
            extra_settings={
                "send_limits": {"daily": 100, "hourly": 50, "warmup_enabled": True}
            },
        )
        campaign, messages, _ = _setup_campaign_with_approved_emails(
            db, seed, msg_count=2
        )

        # Day 1 warm-up = 20, daily = 100 → effective is 20
        mock_warmup_day.return_value = 1
        mock_count_today.return_value = 20  # Already at warm-up limit

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            result = send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        assert result["quota_stopped"] is True
        assert "warm-up" in result.get("quota_message", "").lower()

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_warmup_disabled_skips_schedule(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """When warmup_enabled=false, warm-up schedule is not applied."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(
            db,
            seed,
            extra_settings={
                "send_limits": {"daily": 100, "hourly": 50, "warmup_enabled": False}
            },
        )
        campaign, messages, contacts = _setup_campaign_with_approved_emails(
            db, seed, msg_count=2
        )
        mock_send.return_value = {"id": "resend_msg_001"}

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            result = send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        # Should succeed without warm-up restriction
        contacts_with_email = [c for c in contacts if c.email_address]
        assert result["sent_count"] == len(contacts_with_email)


class TestSendDelay:
    """Tests for send delay with jitter."""

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_default_delay_is_30_seconds(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """Default delay between sends is ~30 seconds (with jitter)."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(db, seed)
        campaign, messages, contacts = _setup_campaign_with_approved_emails(
            db, seed, msg_count=2
        )
        mock_send.return_value = {"id": "resend_msg_001"}

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        # Verify sleep was called with values near 30 (30 +/- 5 jitter)
        if mock_sleep.call_count > 0:
            for call in mock_sleep.call_args_list:
                delay = call[0][0]
                assert 25.0 <= delay <= 35.0, (
                    f"Delay {delay} not in expected range [25, 35]"
                )

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_custom_delay_from_tenant_settings(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """Tenant-configured delay is used instead of default."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(
            db,
            seed,
            extra_settings={
                "send_limits": {"delay_seconds": 10, "warmup_enabled": False}
            },
        )
        campaign, messages, contacts = _setup_campaign_with_approved_emails(
            db, seed, msg_count=2
        )
        mock_send.return_value = {"id": "resend_msg_001"}

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        if mock_sleep.call_count > 0:
            for call in mock_sleep.call_args_list:
                delay = call[0][0]
                assert 5.0 <= delay <= 15.0, (
                    f"Delay {delay} not in expected range [5, 15]"
                )


class TestUnsubscribeHeader:
    """Tests for List-Unsubscribe CAN-SPAM header."""

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service.resend", create=True)
    def test_list_unsubscribe_header_included(
        self, mock_resend_module, mock_sleep, app, db, seed_companies_contacts
    ):
        """Emails include List-Unsubscribe header for CAN-SPAM compliance."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(
            db, seed, extra_settings={"send_limits": {"warmup_enabled": False}}
        )
        campaign, messages, contacts = _setup_campaign_with_approved_emails(
            db, seed, msg_count=1
        )

        # Mock the resend module's Emails.send
        mock_resend_module.Emails.send.return_value = type("R", (), {"id": "re_123"})()

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            send_campaign_emails(str(campaign.id), str(seed["tenant"].id))

        # Check that Emails.send was called with headers containing List-Unsubscribe
        if mock_resend_module.Emails.send.call_count > 0:
            call_args = mock_resend_module.Emails.send.call_args
            params = call_args[0][0] if call_args[0] else call_args[1]
            if isinstance(params, dict) and "headers" in params:
                headers = params["headers"]
                assert "List-Unsubscribe" in headers
                assert "test.com" in headers["List-Unsubscribe"]
                assert "List-Unsubscribe-Post" in headers

    def test_send_single_email_adds_unsubscribe_header(self, app):
        """_send_single_email includes List-Unsubscribe when sender_domain provided."""
        import unittest.mock as mock

        with mock.patch("resend.Emails.send") as mock_send:
            mock_send.return_value = type("R", (), {"id": "re_456"})()

            from api.services.send_service import _send_single_email

            _send_single_email(
                to_email="recipient@example.com",
                sender="Test <test@acme.com>",
                reply_to="reply@acme.com",
                subject="Test",
                body_html="<p>Hello</p>",
                sender_domain="acme.com",
            )

            call_args = mock_send.call_args[0][0]
            assert "headers" in call_args
            assert "List-Unsubscribe" in call_args["headers"]
            assert "acme.com" in call_args["headers"]["List-Unsubscribe"]
            assert (
                call_args["headers"]["List-Unsubscribe-Post"]
                == "List-Unsubscribe=One-Click"
            )


class TestPreSendValidation:
    """Tests for pre-send email validation."""

    def test_validate_filters_no_email(self, app):
        """Contacts without email are filtered out with a warning."""
        from unittest.mock import MagicMock

        from api.services.send_service import _validate_recipients

        msg = MagicMock(id="msg-1")
        contact = MagicMock(
            id="c-1", email_address=None, first_name="John", last_name="Doe"
        )
        cc = MagicMock()

        valid, warnings = _validate_recipients([(msg, contact, cc)])
        assert len(valid) == 0
        assert len(warnings) == 1
        assert warnings[0]["issue"] == "no_email"

    def test_validate_filters_invalid_email(self, app):
        """Invalid email addresses are filtered out."""
        from unittest.mock import MagicMock

        from api.services.send_service import _validate_recipients

        msg = MagicMock(id="msg-1")
        contact = MagicMock(
            id="c-1", email_address="not-an-email", first_name="Jane", last_name="Doe"
        )
        cc = MagicMock()

        valid, warnings = _validate_recipients([(msg, contact, cc)])
        assert len(valid) == 0
        assert len(warnings) == 1
        assert warnings[0]["issue"] == "invalid_email"

    def test_validate_filters_duplicates(self, app):
        """Duplicate recipients within a campaign are flagged."""
        from unittest.mock import MagicMock

        from api.services.send_service import _validate_recipients

        msg1 = MagicMock(id="msg-1")
        msg2 = MagicMock(id="msg-2")
        contact1 = MagicMock(
            id="c-1", email_address="same@test.com", first_name="A", last_name="B"
        )
        contact2 = MagicMock(
            id="c-2", email_address="same@test.com", first_name="C", last_name="D"
        )
        cc = MagicMock()

        valid, warnings = _validate_recipients(
            [(msg1, contact1, cc), (msg2, contact2, cc)]
        )
        assert len(valid) == 1
        assert len(warnings) == 1
        assert warnings[0]["issue"] == "duplicate"

    def test_validate_passes_valid_emails(self, app):
        """Valid, unique emails pass validation."""
        from unittest.mock import MagicMock

        from api.services.send_service import _validate_recipients

        msg1 = MagicMock(id="msg-1")
        msg2 = MagicMock(id="msg-2")
        contact1 = MagicMock(
            id="c-1", email_address="alice@test.com", first_name="A", last_name="B"
        )
        contact2 = MagicMock(
            id="c-2", email_address="bob@test.com", first_name="C", last_name="D"
        )
        cc = MagicMock()

        valid, warnings = _validate_recipients(
            [(msg1, contact1, cc), (msg2, contact2, cc)]
        )
        assert len(valid) == 2
        assert len(warnings) == 0

    def test_email_regex_valid_cases(self, app):
        """EMAIL_RE accepts common valid email formats."""
        from api.services.send_service import EMAIL_RE

        valid = [
            "user@example.com",
            "user.name@example.com",
            "user+tag@example.com",
            "user@sub.example.com",
            "user123@test.co.uk",
        ]
        for email in valid:
            assert EMAIL_RE.match(email), f"{email} should be valid"

    def test_email_regex_invalid_cases(self, app):
        """EMAIL_RE rejects invalid email formats."""
        from api.services.send_service import EMAIL_RE

        invalid = [
            "not-an-email",
            "@nouser.com",
            "user@",
            "user@.com",
            "",
            "user @space.com",
        ]
        for email in invalid:
            assert not EMAIL_RE.match(email), f"{email} should be invalid"


class TestSendEmailsEndpoint:
    """Integration tests for POST /api/campaigns/<id>/send-emails."""

    def test_send_emails_missing_sender_config(
        self, client, seed_companies_contacts, db
    ):
        """Returns 400 when campaign has no sender_config."""
        from api.models import Campaign

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts

        # Create campaign without sender config
        campaign = Campaign(
            tenant_id=seed["tenant"].id,
            name="No Sender",
            status="review",
        )
        db.session.add(campaign)
        db.session.commit()

        resp = client.post(
            f"/api/campaigns/{campaign.id}/send-emails",
            headers=headers,
        )
        assert resp.status_code == 400
        assert "from_email" in resp.get_json()["error"].lower()

    def test_send_emails_missing_resend_key(self, client, seed_companies_contacts, db):
        """Returns 400 when tenant has no Resend API key."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts

        campaign, messages, _ = _setup_campaign_with_approved_emails(
            db, seed, msg_count=1
        )
        # Do NOT set up resend key on tenant

        resp = client.post(
            f"/api/campaigns/{campaign.id}/send-emails",
            headers=headers,
        )
        assert resp.status_code == 400
        assert "resend_api_key" in resp.get_json()["error"].lower()

    def test_send_emails_no_approved_messages(
        self, client, seed_companies_contacts, db
    ):
        """Returns 400 when campaign has no approved email messages."""
        from api.models import Campaign

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts

        _setup_tenant_with_resend_key(db, seed)

        campaign = Campaign(
            tenant_id=seed["tenant"].id,
            name="Empty Campaign",
            status="review",
            sender_config=json.dumps({"from_email": "sender@test.com"}),
        )
        db.session.add(campaign)
        db.session.commit()

        resp = client.post(
            f"/api/campaigns/{campaign.id}/send-emails",
            headers=headers,
        )
        assert resp.status_code == 400
        assert "no approved" in resp.get_json()["error"].lower()

    @patch("api.routes.campaign_routes.send_campaign_emails")
    def test_send_emails_starts_background_send(
        self, mock_send, client, seed_companies_contacts, db
    ):
        """Endpoint starts background send and returns queued count."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts

        _setup_tenant_with_resend_key(db, seed)
        campaign, messages, _ = _setup_campaign_with_approved_emails(
            db, seed, msg_count=2
        )

        resp = client.post(
            f"/api/campaigns/{campaign.id}/send-emails",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["queued_count"] >= 1
        assert data["sender"]["from_email"] == "outreach@test.com"
        assert data["sender"]["from_name"] == "Test Outreach"
        # Should include quota info
        assert "quota" in data
        assert "daily_remaining" in data["quota"]
        assert "warmup_day" in data["quota"]

    @patch("api.routes.campaign_routes.get_quota_status")
    def test_send_emails_blocked_by_daily_quota(
        self, mock_quota, client, seed_companies_contacts, db
    ):
        """Returns 429 when daily quota is exhausted."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts

        _setup_tenant_with_resend_key(db, seed)
        campaign, _, _ = _setup_campaign_with_approved_emails(db, seed, msg_count=1)

        mock_quota.return_value = {
            "daily_limit": 100,
            "daily_sent": 100,
            "daily_remaining": 0,
            "hourly_limit": 30,
            "hourly_sent": 5,
            "hourly_remaining": 25,
            "warmup_enabled": False,
            "warmup_day": 1,
            "warmup_limit": 20,
        }

        resp = client.post(
            f"/api/campaigns/{campaign.id}/send-emails",
            headers=headers,
        )
        assert resp.status_code == 429
        data = resp.get_json()
        assert "daily send limit" in data["error"].lower()
        assert "quota" in data

    @patch("api.routes.campaign_routes.get_quota_status")
    def test_send_emails_blocked_by_hourly_quota(
        self, mock_quota, client, seed_companies_contacts, db
    ):
        """Returns 429 when hourly quota is exhausted."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts

        _setup_tenant_with_resend_key(db, seed)
        campaign, _, _ = _setup_campaign_with_approved_emails(db, seed, msg_count=1)

        mock_quota.return_value = {
            "daily_limit": 100,
            "daily_sent": 20,
            "daily_remaining": 80,
            "hourly_limit": 30,
            "hourly_sent": 30,
            "hourly_remaining": 0,
            "warmup_enabled": False,
            "warmup_day": 1,
            "warmup_limit": 20,
        }

        resp = client.post(
            f"/api/campaigns/{campaign.id}/send-emails",
            headers=headers,
        )
        assert resp.status_code == 429
        data = resp.get_json()
        assert "hourly send limit" in data["error"].lower()

    def test_send_emails_campaign_not_found(self, client, seed_companies_contacts, db):
        """Returns 404 for non-existent campaign."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            "/api/campaigns/00000000-0000-0000-0000-000000000099/send-emails",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_send_emails_requires_auth(self, client, db):
        """Returns 401 without authentication."""
        resp = client.post("/api/campaigns/some-id/send-emails")
        assert resp.status_code == 401


class TestSendStatusEndpoint:
    """Integration tests for GET /api/campaigns/<id>/send-status."""

    def test_send_status_empty(self, client, seed_companies_contacts, db):
        """Returns zero counts for campaign with no sends."""
        from api.models import Campaign

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts

        campaign = Campaign(
            tenant_id=seed["tenant"].id,
            name="Status Test Campaign",
            status="review",
        )
        db.session.add(campaign)
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{campaign.id}/send-status",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 0
        assert data["sent"] == 0
        assert data["delivered"] == 0
        assert data["failed"] == 0
        assert data["bounced"] == 0
        assert data["queued"] == 0
        # New quota fields
        assert "daily_remaining" in data
        assert "hourly_remaining" in data
        assert "warmup_day" in data
        assert "warmup_limit" in data

    def test_send_status_with_logs(self, client, seed_companies_contacts, db):
        """Returns correct counts from EmailSendLog entries."""
        from api.models import EmailSendLog

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts

        campaign, messages, _ = _setup_campaign_with_approved_emails(
            db, seed, msg_count=3
        )

        # Create logs with different statuses
        statuses = ["sent", "delivered", "failed"]
        for i, msg in enumerate(messages):
            if i < len(statuses):
                log = EmailSendLog(
                    tenant_id=seed["tenant"].id,
                    message_id=msg.id,
                    status=statuses[i],
                    from_email="outreach@test.com",
                    to_email=f"contact{i}@test.com",
                )
                db.session.add(log)
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{campaign.id}/send-status",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 3
        assert data["sent"] == 1
        assert data["delivered"] == 1
        assert data["failed"] == 1

    def test_send_status_campaign_not_found(self, client, seed_companies_contacts, db):
        """Returns 404 for non-existent campaign."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.get(
            "/api/campaigns/00000000-0000-0000-0000-000000000099/send-status",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_send_status_requires_auth(self, client, db):
        """Returns 401 without authentication."""
        resp = client.get("/api/campaigns/some-id/send-status")
        assert resp.status_code == 401


class TestGetQuotaStatus:
    """Tests for the get_quota_status helper."""

    def test_quota_status_defaults(self, app, db, seed_companies_contacts):
        """Returns conservative defaults when no send_limits configured."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(db, seed)

        from api.services.send_service import get_quota_status

        with app.app_context():
            quota = get_quota_status(str(seed["tenant"].id))

        # Default warmup enabled, day 1
        assert quota["warmup_enabled"] is True
        assert quota["warmup_day"] == 1
        assert quota["warmup_limit"] == 20
        assert quota["hourly_limit"] == 30
        assert quota["daily_limit"] <= 20  # min(100, warmup=20)

    def test_quota_status_custom_limits(self, app, db, seed_companies_contacts):
        """Returns tenant-specific limits."""
        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(
            db,
            seed,
            extra_settings={
                "send_limits": {"daily": 200, "hourly": 50, "warmup_enabled": False}
            },
        )

        from api.services.send_service import get_quota_status

        with app.app_context():
            quota = get_quota_status(str(seed["tenant"].id))

        assert quota["daily_limit"] == 200
        assert quota["hourly_limit"] == 50
        assert quota["warmup_enabled"] is False


class TestRenderBodyHtml:
    """Unit tests for _render_body_html helper."""

    def test_plain_text_to_html(self, app):
        from api.services.send_service import _render_body_html

        result = _render_body_html("Hello World")
        assert "<p>Hello World</p>" in result

    def test_multiline_to_paragraphs(self, app):
        from api.services.send_service import _render_body_html

        result = _render_body_html("First paragraph\n\nSecond paragraph")
        assert "<p>First paragraph</p>" in result
        assert "<p>Second paragraph</p>" in result

    def test_single_newlines_to_br(self, app):
        from api.services.send_service import _render_body_html

        result = _render_body_html("Line one\nLine two")
        assert "<br>" in result

    def test_html_passthrough(self, app):
        from api.services.send_service import _render_body_html

        html = "<p>Already <strong>formatted</strong></p>"
        assert _render_body_html(html) == html

    def test_empty_body(self, app):
        from api.services.send_service import _render_body_html

        result = _render_body_html("")
        assert result == "<p></p>"

    def test_none_body(self, app):
        from api.services.send_service import _render_body_html

        result = _render_body_html(None)
        assert result == "<p></p>"


class TestSupersededRows:
    """BL-1029: when a failed send is followed by a successful send to the
    same message, the earlier failed row is marked superseded so analytics
    don't double-count retries."""

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_retry_after_failure_marks_earlier_row_superseded(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """Abort-then-retry flow produces exactly one effective row per
        message in the default (superseded_at IS NULL) view while all
        attempts remain in the table for audit."""
        from api.models import EmailSendLog

        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(db, seed)
        campaign, messages, _ = _setup_campaign_with_approved_emails(
            db, seed, msg_count=1
        )
        message = messages[0]
        tenant_id = seed["tenant"].id

        # Simulate a prior failed attempt (e.g. daily_quota_exceeded abort):
        # a `failed` row already exists for this message.
        failed_log = EmailSendLog(
            tenant_id=tenant_id,
            message_id=message.id,
            status="failed",
            from_email="outreach@test.com",
            to_email="x@test.com",
            error="daily_quota_exceeded",
        )
        db.session.add(failed_log)
        db.session.commit()
        failed_id = failed_log.id
        assert failed_log.superseded_at is None

        mock_send.return_value = {"id": "re_retry_success"}

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            result = send_campaign_emails(str(campaign.id), str(tenant_id))

        assert result["sent_count"] == 1

        # All attempts (audit view): still 2 rows, the failed one and the
        # new sent one.
        all_attempts = (
            db.session.query(EmailSendLog)
            .filter(EmailSendLog.message_id == message.id)
            .all()
        )
        assert len(all_attempts) == 2

        # Effective (default) view: only the successful row.
        effective = (
            db.session.query(EmailSendLog)
            .filter(
                EmailSendLog.message_id == message.id,
                EmailSendLog.superseded_at.is_(None),
            )
            .all()
        )
        assert len(effective) == 1
        assert effective[0].status == "sent"

        # The old failed row carries a superseded_by FK to the winning row.
        # Expire session-cached instances so .get() re-reads from DB.
        db.session.expire_all()
        refreshed = db.session.get(EmailSendLog, failed_id)
        assert refreshed.superseded_at is not None
        assert refreshed.superseded_by is not None
        assert str(refreshed.superseded_by) == str(effective[0].id)

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_failure_without_prior_failure_does_not_mark_superseded(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """A brand-new failure (no earlier attempt) must NOT be marked
        superseded. Superseded status is only set when a *successful* send
        follows a failed one."""
        from api.models import EmailSendLog

        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(db, seed)
        campaign, messages, _ = _setup_campaign_with_approved_emails(
            db, seed, msg_count=1
        )
        message = messages[0]
        tenant_id = seed["tenant"].id

        mock_send.side_effect = Exception("resend api error")

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            send_campaign_emails(str(campaign.id), str(tenant_id))

        logs = (
            db.session.query(EmailSendLog)
            .filter(EmailSendLog.message_id == message.id)
            .all()
        )
        assert len(logs) == 1
        assert logs[0].status == "failed"
        assert logs[0].superseded_at is None
        assert logs[0].superseded_by is None

    @patch("api.services.send_service.time.sleep")
    @patch("api.services.send_service._send_single_email")
    def test_successful_send_without_prior_failure_is_not_superseded(
        self, mock_send, mock_sleep, app, db, seed_companies_contacts
    ):
        """Normal happy-path send leaves the winning row's superseded_at
        null and has nothing to mark."""
        from api.models import EmailSendLog

        seed = seed_companies_contacts
        _setup_tenant_with_resend_key(db, seed)
        campaign, messages, _ = _setup_campaign_with_approved_emails(
            db, seed, msg_count=1
        )
        message = messages[0]
        tenant_id = seed["tenant"].id

        mock_send.return_value = {"id": "re_happy_path"}

        from api.services.send_service import send_campaign_emails

        with app.app_context():
            send_campaign_emails(str(campaign.id), str(tenant_id))

        logs = (
            db.session.query(EmailSendLog)
            .filter(EmailSendLog.message_id == message.id)
            .all()
        )
        assert len(logs) == 1
        assert logs[0].status == "sent"
        assert logs[0].superseded_at is None
        assert logs[0].superseded_by is None
