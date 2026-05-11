"""Tests for BL-1026 preview pollution guard.

Verifies:
  1. `EmailSendLog.kind` defaults to 'production' on normal inserts.
  2. Campaign analytics (`GET /api/campaigns/:id/analytics`) excludes
     rows with `kind='preview'` from sending/engagement/timeline rollups.
  3. Per-recipient timeline (`GET /api/campaigns/:id/recipients`) excludes
     preview rows so the drill-down does not show preview events as if
     they were real partner engagement.
  4. Engagement (opened/clicked) on a preview row does not inflate the
     campaign's rates.
  5. The `send-test` endpoint, when it successfully dispatches, tags the
     resulting `EmailSendLog` row with `kind='preview'`.
"""

import json
from unittest.mock import patch

from api.models import (
    Campaign,
    CampaignContact,
    Contact,
    EmailSendLog,
    Message,
    Owner,
)
from tests.conftest import auth_header


def _make_campaign(db, tenant_id, name="Preview Test Campaign"):
    c = Campaign(
        tenant_id=tenant_id,
        name=name,
        status="review",
        generation_config=json.dumps({}),
        sender_config=json.dumps(
            {"from_email": "from@example.com", "from_name": "Alice"}
        ),
    )
    db.session.add(c)
    db.session.flush()
    return c


def _make_contact(db, tenant_id, first="P", email="p@example.com"):
    ct = Contact(
        tenant_id=tenant_id,
        first_name=first,
        last_name="Test",
        email_address=email,
    )
    db.session.add(ct)
    db.session.flush()
    return ct


def _make_cc(db, campaign_id, contact_id, tenant_id):
    cc = CampaignContact(
        campaign_id=campaign_id,
        contact_id=contact_id,
        tenant_id=tenant_id,
        status="generated",
    )
    db.session.add(cc)
    db.session.flush()
    return cc


def _make_message(db, tenant_id, contact_id, cc_id, owner_id):
    m = Message(
        tenant_id=tenant_id,
        contact_id=contact_id,
        campaign_contact_id=cc_id,
        owner_id=owner_id,
        channel="email",
        sequence_step=1,
        body="Hello",
        subject="Hi",
        status="approved",
        generation_cost_usd=0.01,
    )
    db.session.add(m)
    db.session.flush()
    return m


class TestEmailSendLogKindColumn:
    """The `kind` column defaults to 'production' on new rows."""

    def test_new_row_defaults_to_production(self, app, db, seed_tenant):
        owner = Owner(tenant_id=seed_tenant.id, name="Owner", is_active=True)
        db.session.add(owner)
        db.session.flush()

        ct = _make_contact(db, seed_tenant.id)
        campaign = _make_campaign(db, seed_tenant.id)
        cc = _make_cc(db, campaign.id, ct.id, seed_tenant.id)
        msg = _make_message(db, seed_tenant.id, ct.id, cc.id, owner.id)

        log = EmailSendLog(
            tenant_id=seed_tenant.id,
            message_id=msg.id,
            status="sent",
            from_email="from@example.com",
            to_email="p@example.com",
        )
        db.session.add(log)
        db.session.commit()

        fetched = db.session.get(EmailSendLog, log.id)
        assert fetched.kind == "production"

    def test_preview_row_stored_and_queryable(self, app, db, seed_tenant):
        owner = Owner(tenant_id=seed_tenant.id, name="Owner", is_active=True)
        db.session.add(owner)
        db.session.flush()

        ct = _make_contact(db, seed_tenant.id)
        campaign = _make_campaign(db, seed_tenant.id)
        cc = _make_cc(db, campaign.id, ct.id, seed_tenant.id)
        msg = _make_message(db, seed_tenant.id, ct.id, cc.id, owner.id)

        log = EmailSendLog(
            tenant_id=seed_tenant.id,
            message_id=msg.id,
            status="sent",
            kind="preview",
            from_email="from@example.com",
            to_email="operator@example.com",
        )
        db.session.add(log)
        db.session.commit()

        # Audit: preview rows MUST be persisted (not deleted).
        fetched = (
            db.session.query(EmailSendLog)
            .filter(EmailSendLog.kind == "preview")
            .first()
        )
        assert fetched is not None
        assert str(fetched.id) == str(log.id)


class TestAnalyticsExcludePreview:
    """`GET /api/campaigns/:id/analytics` filters out kind='preview' rows."""

    def _seed(self, db, tenant, mix_preview=True):
        owner = Owner(tenant_id=tenant.id, name="Owner", is_active=True)
        db.session.add(owner)
        db.session.flush()

        ct = _make_contact(db, tenant.id, first="Real", email="real@example.com")
        campaign = _make_campaign(db, tenant.id)
        cc = _make_cc(db, campaign.id, ct.id, tenant.id)

        # Two real sends — one delivered + opened + clicked, one bounced.
        m1 = _make_message(db, tenant.id, ct.id, cc.id, owner.id)
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        db.session.add(
            EmailSendLog(
                tenant_id=tenant.id,
                message_id=m1.id,
                status="sent",
                kind="production",
                from_email="from@example.com",
                to_email="real@example.com",
                sent_at=now,
                delivered_at=now,
                opened_at=now,
                open_count=1,
                clicked_at=now,
                click_count=1,
            )
        )
        m2 = _make_message(db, tenant.id, ct.id, cc.id, owner.id)
        db.session.add(
            EmailSendLog(
                tenant_id=tenant.id,
                message_id=m2.id,
                status="bounced",
                kind="production",
                from_email="from@example.com",
                to_email="real@example.com",
                bounced_at=now,
                bounce_type="hard",
            )
        )

        if mix_preview:
            # Three preview sends with aggressive engagement — should be
            # entirely excluded from the rollup.
            for _ in range(3):
                mp = _make_message(db, tenant.id, ct.id, cc.id, owner.id)
                db.session.add(
                    EmailSendLog(
                        tenant_id=tenant.id,
                        message_id=mp.id,
                        status="sent",
                        kind="preview",
                        from_email="from@example.com",
                        to_email="operator@example.com",
                        sent_at=now,
                        delivered_at=now,
                        opened_at=now,
                        open_count=5,
                        clicked_at=now,
                        click_count=5,
                    )
                )
        db.session.commit()
        return campaign

    def test_email_counts_exclude_preview(
        self, client, db, seed_tenant, seed_companies_contacts
    ):
        campaign = self._seed(db, seed_tenant)
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.get(f"/api/campaigns/{campaign.id}/analytics", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()

        # Only the 2 production rows should be in `email.total`.
        assert data["sending"]["email"]["total"] == 2
        assert data["sending"]["email"]["sent"] == 1
        assert data["sending"]["email"]["bounced"] == 1

    def test_engagement_excludes_preview(
        self, client, db, seed_tenant, seed_companies_contacts
    ):
        campaign = self._seed(db, seed_tenant)
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.get(f"/api/campaigns/{campaign.id}/analytics", headers=headers)
        data = resp.get_json()

        # Only the 1 production open + click — preview would add 3 more
        # opens and 3 more clicks with inflated counts.
        assert data["engagement"]["opened"] == 1
        assert data["engagement"]["clicked"] == 1
        assert data["engagement"]["total_opens"] == 1
        assert data["engagement"]["total_clicks"] == 1

    def test_rates_not_inflated_by_preview(
        self, client, db, seed_tenant, seed_companies_contacts
    ):
        campaign_with = self._seed(db, seed_tenant, mix_preview=True)
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        with_preview = client.get(
            f"/api/campaigns/{campaign_with.id}/analytics", headers=headers
        ).get_json()

        # With 1 delivered + 1 opened → 100% open rate.  If preview
        # rows leaked in (3 extra delivered + 3 extra opened) we would
        # still get ~100%, so assert on counts not percentages here.
        # Bounce rate uses email_total as denominator: bounced=1 /
        # total=2 = 50% (not 1/5=20% if previews leaked in).
        assert with_preview["engagement"]["bounce_rate"] == 50.0


class TestRecipientsTimelineExcludesPreview:
    """Per-recipient drill-down must not surface preview events."""

    def test_preview_events_absent_from_timeline(
        self, client, db, seed_tenant, seed_companies_contacts
    ):
        owner = Owner(tenant_id=seed_tenant.id, name="Owner", is_active=True)
        db.session.add(owner)
        db.session.flush()

        ct = _make_contact(db, seed_tenant.id)
        campaign = _make_campaign(db, seed_tenant.id)
        cc = _make_cc(db, campaign.id, ct.id, seed_tenant.id)

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        # Production message — one event.
        m_prod = _make_message(db, seed_tenant.id, ct.id, cc.id, owner.id)
        db.session.add(
            EmailSendLog(
                tenant_id=seed_tenant.id,
                message_id=m_prod.id,
                status="sent",
                kind="production",
                from_email="from@example.com",
                to_email="p@example.com",
                sent_at=now,
            )
        )

        # Preview message — fake click that must NOT show up.
        m_prev = _make_message(db, seed_tenant.id, ct.id, cc.id, owner.id)
        db.session.add(
            EmailSendLog(
                tenant_id=seed_tenant.id,
                message_id=m_prev.id,
                status="sent",
                kind="preview",
                from_email="from@example.com",
                to_email="operator@example.com",
                sent_at=now,
                clicked_at=now,
            )
        )
        db.session.commit()

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get(f"/api/campaigns/{campaign.id}/recipients", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()

        all_event_types = [
            ev["type"] for rec in data["recipients"] for ev in rec.get("timeline", [])
        ]
        # Exactly one "sent" event (production), zero "clicked" events
        # (those came from the preview row).
        assert all_event_types.count("sent") == 1
        assert "clicked" not in all_event_types


class TestSendTestTagsPreview:
    """The /send-test endpoint writes an EmailSendLog row with kind='preview'."""

    def test_send_test_logs_preview_row(
        self, client, db, seed_tenant, seed_companies_contacts
    ):
        from api.models import Tenant

        # Tenant needs a resend_api_key in settings for the test route.
        tenant = db.session.get(Tenant, seed_tenant.id)
        tenant.settings = json.dumps({"resend_api_key": "re_test"})
        db.session.commit()

        owner = Owner(tenant_id=seed_tenant.id, name="Owner", is_active=True)
        db.session.add(owner)
        db.session.flush()

        ct = _make_contact(db, seed_tenant.id)
        campaign = _make_campaign(db, seed_tenant.id)
        cc = _make_cc(db, campaign.id, ct.id, seed_tenant.id)
        msg = _make_message(db, seed_tenant.id, ct.id, cc.id, owner.id)

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        with patch("resend.Emails.send") as mocked:
            mocked.return_value = {"id": "re_123"}
            resp = client.post(
                f"/api/campaigns/{campaign.id}/send-test",
                headers=headers,
                json={"message_id": str(msg.id)},
            )

        assert resp.status_code == 200, resp.get_json()

        preview_rows = (
            db.session.query(EmailSendLog).filter(EmailSendLog.kind == "preview").all()
        )
        assert len(preview_rows) == 1
        assert preview_rows[0].resend_message_id == "re_123"
        assert preview_rows[0].status == "sent"
