"""Unit tests for ``api.services.eventfest_campaign`` (Phase 2 Task 2).

Covers:
1. Campaign created with EventFest config + sender_config from env.
2. Per-email Contact + CampaignContact + Message rows created with
   placeholders intact in the body.
3. Partner token persisted on each CampaignContact.
4. Idempotency — re-running does NOT duplicate rows.
5. CLI script imports cleanly and exposes ``main()``.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def env_vars(monkeypatch):
    """Populate the env vars `provision_eventfest_campaign` requires."""
    monkeypatch.setenv("UA_MAILING_FROM_EMAIL", "hana@loserscirque.cz")
    monkeypatch.setenv("UA_MAILING_FROM_NAME", "Hanka | Losers Cirque Company")
    monkeypatch.setenv("UA_MAILING_REPLY_TO", "hana@unitedarts.cz")
    monkeypatch.setenv("UA_MICROSITE_URL", "https://demo.visionvolve.com")
    monkeypatch.setenv("UA_INVITE_API_KEY", "test-invite-key")


@pytest.fixture
def fake_invites(monkeypatch):
    """Patch ``get_or_create_invite`` to return a deterministic URL per email."""
    calls: list[dict] = []

    def _fake(email, name, microsite_url, api_key):
        calls.append(
            {
                "email": email,
                "name": name,
                "microsite_url": microsite_url,
                "api_key": api_key,
            }
        )
        # Token = first part of email, deterministic.
        token = email.split("@", 1)[0].replace(".", "_")
        return f"{microsite_url}/invite/ptok_{token}"

    monkeypatch.setattr(
        "api.services.eventfest_campaign.get_or_create_invite",
        _fake,
    )
    return calls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProvisionEventfestCampaign:
    """provision_eventfest_campaign(...)"""

    def test_creates_campaign_with_eventfest_config(
        self, app, db, seed_tenant, env_vars, fake_invites
    ):
        """Test 1: Campaign row reflects EventFest config + env-driven sender."""
        from api.models import Campaign
        from api.services.eventfest_campaign import provision_eventfest_campaign

        campaign_id = provision_eventfest_campaign(
            "EventFest 2026",
            ["a@x.com", "b@x.com"],
            seed_tenant.id,
        )

        camp = db.session.get(Campaign, campaign_id)
        assert camp is not None
        assert camp.name == "EventFest 2026"
        assert camp.status == "draft"
        assert camp.language == "cs"

        gen_cfg = camp.generation_config
        if isinstance(gen_cfg, str):
            import json

            gen_cfg = json.loads(gen_cfg)
        assert gen_cfg.get("template_type") == "eventfest"

        sender_cfg = camp.sender_config
        if isinstance(sender_cfg, str):
            import json

            sender_cfg = json.loads(sender_cfg)
        assert sender_cfg.get("from_email") == "hana@loserscirque.cz"
        assert sender_cfg.get("from_name") == "Hanka | Losers Cirque Company"
        assert sender_cfg.get("reply_to") == "hana@unitedarts.cz"

    def test_creates_contacts_campaign_contacts_and_messages(
        self, app, db, seed_tenant, env_vars, fake_invites
    ):
        """Test 2: per-email Contact + CampaignContact + Message rows.

        Each Message has channel='email', status='approved',
        subject=EVENTFEST_SUBJECT, body containing both
        ``{{vocative_name}}`` and ``{{microsite_link}}`` placeholders intact.
        """
        from api.models import CampaignContact, Contact, Message
        from api.services.eventfest_campaign import provision_eventfest_campaign
        from api.services.eventfest_template import EVENTFEST_SUBJECT

        campaign_id = provision_eventfest_campaign(
            "EventFest 2026",
            ["a@x.com", "b@x.com"],
            seed_tenant.id,
        )

        contacts = (
            db.session.query(Contact)
            .filter(Contact.tenant_id == seed_tenant.id)
            .filter(Contact.email_address.in_(["a@x.com", "b@x.com"]))
            .all()
        )
        assert len(contacts) == 2

        ccs = (
            db.session.query(CampaignContact)
            .filter(CampaignContact.campaign_id == campaign_id)
            .all()
        )
        assert len(ccs) == 2

        cc_ids = [cc.id for cc in ccs]
        msgs = (
            db.session.query(Message)
            .filter(Message.campaign_contact_id.in_(cc_ids))
            .all()
        )
        assert len(msgs) == 2
        for msg in msgs:
            assert msg.channel == "email"
            assert msg.status == "approved"
            assert msg.subject == EVENTFEST_SUBJECT
            assert "{{vocative_name}}" in msg.body
            assert "{{microsite_link}}" in msg.body

    def test_persists_partner_tokens_from_microsite(
        self, app, db, seed_tenant, env_vars, fake_invites
    ):
        """Test 3: each CampaignContact carries its UA microsite partner token."""
        from api.models import CampaignContact, Contact
        from api.services.eventfest_campaign import provision_eventfest_campaign

        provision_eventfest_campaign(
            "EventFest 2026",
            ["alice@x.com", "bob@x.com"],
            seed_tenant.id,
        )

        # fake_invites generated tokens like ptok_alice, ptok_bob
        rows = (
            db.session.query(CampaignContact, Contact)
            .join(Contact, Contact.id == CampaignContact.contact_id)
            .all()
        )
        token_by_email = {c.email_address: cc.microsite_partner_token for cc, c in rows}
        assert token_by_email == {
            "alice@x.com": "ptok_alice",
            "bob@x.com": "ptok_bob",
        }

        # Verify the microsite client received the right inputs.
        emails_called = sorted(call["email"] for call in fake_invites)
        assert emails_called == ["alice@x.com", "bob@x.com"]
        for call in fake_invites:
            assert call["microsite_url"] == "https://demo.visionvolve.com"
            assert call["api_key"] == "test-invite-key"

    def test_unreachable_microsite_rolls_back(
        self, app, db, seed_tenant, env_vars, monkeypatch
    ):
        """Test 3b (gap-fix Rule 2): unreachable microsite → rollback, no partial Campaign."""
        from api.models import Campaign
        from api.services.eventfest_campaign import provision_eventfest_campaign

        # Microsite returns None → service must raise + rollback.
        monkeypatch.setattr(
            "api.services.eventfest_campaign.get_or_create_invite",
            lambda **kwargs: None,
        )

        with pytest.raises(RuntimeError, match="microsite invite unreachable"):
            provision_eventfest_campaign(
                "EventFest 2026",
                ["a@x.com"],
                seed_tenant.id,
            )

        # No Campaign row should exist.
        existing = (
            db.session.query(Campaign).filter(Campaign.name == "EventFest 2026").first()
        )
        assert existing is None

    def test_idempotent_second_call(self, app, db, seed_tenant, env_vars, fake_invites):
        """Test 4: re-running with same (name, emails) is a no-op."""
        from api.models import CampaignContact, Contact, Message
        from api.services.eventfest_campaign import provision_eventfest_campaign

        first_id = provision_eventfest_campaign(
            "EventFest 2026", ["a@x.com", "b@x.com"], seed_tenant.id
        )
        second_id = provision_eventfest_campaign(
            "EventFest 2026", ["a@x.com", "b@x.com"], seed_tenant.id
        )

        assert first_id == second_id

        # No duplicates.
        contact_count = (
            db.session.query(Contact)
            .filter(Contact.tenant_id == seed_tenant.id)
            .count()
        )
        assert contact_count == 2

        cc_count = (
            db.session.query(CampaignContact)
            .filter(CampaignContact.campaign_id == first_id)
            .count()
        )
        assert cc_count == 2

        msg_count = (
            db.session.query(Message)
            .join(
                CampaignContact,
                CampaignContact.id == Message.campaign_contact_id,
            )
            .filter(CampaignContact.campaign_id == first_id)
            .count()
        )
        assert msg_count == 2

        # Second call must NOT have re-fetched microsite invites for
        # already-tokenised contacts.
        assert len(fake_invites) == 2  # only the first call's two invites


class TestProvisionCli:
    """scripts/provision_eventfest_campaign.py"""

    def test_cli_imports_and_runs(
        self, app, seed_tenant, env_vars, fake_invites, tmp_path, capsys, monkeypatch
    ):
        """Test 5: CLI invokes the service and prints the campaign URL."""
        # Avoid the CLI rebuilding a Flask app with an in-memory DB different
        # from the test fixture by stubbing create_app to return the test app.
        monkeypatch.setattr(
            "api.create_app",
            lambda: app,
        )

        emails_file = tmp_path / "emails.txt"
        emails_file.write_text("# header comment\nlicko61+p2smoke@gmail.com\n\n")

        # Import inside the test so monkeypatch on create_app is in effect.
        from scripts.provision_eventfest_campaign import main

        rc = main(
            [
                "--name",
                "EventFest 2026 CLI",
                "--tenant",
                str(seed_tenant.id),
                "--file",
                str(emails_file),
                "--dashboard-base",
                "https://leadgen-staging.visionvolve.com",
            ]
        )
        assert rc == 0

        out = capsys.readouterr().out
        assert "Campaign " in out
        assert "Dashboard: https://leadgen-staging.visionvolve.com/campaigns/" in out
