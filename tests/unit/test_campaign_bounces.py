"""Unit tests for the campaign bounces export endpoints (BL-1102).

Covers:
- /api/campaigns/<id>/bounces (JSON): lists every undeliverable recipient
  (bounced_at set OR status in {'bounced','failed'}), excludes preview +
  superseded rows.
- /api/campaigns/<id>/bounces.csv (CSV): returns text/csv with the
  documented column order and a per-campaign filename.
- Tenant isolation: a campaign in another tenant returns 404, even for
  the same logged-in user.
- 404 for unknown campaign UUID.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.conftest import auth_header


@pytest.fixture
def bounces_campaign(db, seed_tenant, seed_user_with_role):
    """Seed one campaign with a mix of bounced / failed / delivered sends.

    Layout:
    - bouncer@x.com         → hard bounce      (must appear)
    - softie@x.com          → soft bounce      (must appear)
    - failed@x.com          → status=failed    (must appear)
    - delivered@x.com       → status=sent      (must NOT appear)
    - preview@x.com         → status=bounced kind=preview  (must NOT appear)
    - superseded@x.com      → status=failed, superseded by a delivery (must NOT appear)
    """
    from api.models import (
        Campaign,
        CampaignContact,
        Company,
        Contact,
        EmailSendLog,
        Message,
    )

    co = Company(tenant_id=seed_tenant.id, name="Acme Corp")
    db.session.add(co)
    db.session.flush()

    def _contact(email, first="First", last="Last"):
        c = Contact(
            tenant_id=seed_tenant.id,
            company_id=co.id,
            first_name=first,
            last_name=last,
            email_address=email,
        )
        db.session.add(c)
        db.session.flush()
        return c

    bouncer = _contact("bouncer@x.com", "Bo", "Uncer")
    softie = _contact("softie@x.com", "So", "Ftie")
    failer = _contact("failed@x.com", "Fa", "Iled")
    delivered = _contact("delivered@x.com", "De", "Livered")
    previewer = _contact("preview@x.com", "Pre", "View")
    superseded_contact = _contact("superseded@x.com", "Su", "Perseded")

    campaign = Campaign(
        tenant_id=seed_tenant.id,
        name="EventFest 2026",
        status="sending",
    )
    db.session.add(campaign)
    db.session.flush()

    def _add_send(
        contact,
        *,
        status,
        bounced_at=None,
        bounce_type=None,
        kind="production",
        superseded_at=None,
        error=None,
    ):
        cc = CampaignContact(
            campaign_id=campaign.id,
            contact_id=contact.id,
            tenant_id=seed_tenant.id,
            status="sent",
        )
        db.session.add(cc)
        db.session.flush()
        msg = Message(
            tenant_id=seed_tenant.id,
            contact_id=contact.id,
            channel="email",
            sequence_step=1,
            variant="a",
            subject="EventFest",
            body="Hi",
            status="approved",
            campaign_contact_id=cc.id,
        )
        db.session.add(msg)
        db.session.flush()
        log = EmailSendLog(
            tenant_id=seed_tenant.id,
            message_id=msg.id,
            status=status,
            from_email="hana@loserscirque.cz",
            to_email=contact.email_address,
            bounced_at=bounced_at,
            bounce_type=bounce_type,
            kind=kind,
            superseded_at=superseded_at,
            error=error,
            sent_at=datetime(2026, 4, 1, 9, 0, 0, tzinfo=timezone.utc),
        )
        db.session.add(log)
        db.session.flush()
        return log

    _add_send(
        bouncer,
        status="bounced",
        bounced_at=datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc),
        bounce_type="hard",
        error="550 mailbox not found",
    )
    _add_send(
        softie,
        status="bounced",
        bounced_at=datetime(2026, 4, 1, 11, 0, 0, tzinfo=timezone.utc),
        bounce_type="soft",
    )
    _add_send(failer, status="failed", error="connection timeout")
    _add_send(delivered, status="sent")
    _add_send(
        previewer,
        status="bounced",
        bounced_at=datetime(2026, 4, 1, 9, 30, 0, tzinfo=timezone.utc),
        bounce_type="hard",
        kind="preview",
    )
    _add_send(
        superseded_contact,
        status="failed",
        superseded_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc),
    )

    db.session.commit()
    return {"campaign": campaign}


def _auth(client):
    return auth_header(client, email="user@test.com")


class TestCampaignBouncesJson:
    """GET /api/campaigns/<id>/bounces."""

    def test_lists_only_undeliverable_rows(
        self, client, bounces_campaign, seed_user_with_role
    ):
        camp = bounces_campaign["campaign"]
        resp = client.get(f"/api/campaigns/{camp.id}/bounces", headers=_auth(client))
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()

        assert body["campaign_id"] == str(camp.id)
        assert body["campaign_name"] == "EventFest 2026"
        assert body["total"] == 3, body

        emails = {row["email"] for row in body["bounces"]}
        assert emails == {"bouncer@x.com", "softie@x.com", "failed@x.com"}

        # Preview, superseded, and delivered rows are excluded.
        assert "preview@x.com" not in emails
        assert "superseded@x.com" not in emails
        assert "delivered@x.com" not in emails

        # Spot-check the hard-bounce row carries its error + type.
        hard = next(r for r in body["bounces"] if r["email"] == "bouncer@x.com")
        assert hard["bounce_type"] == "hard"
        assert hard["status"] == "bounced"
        assert hard["error_message"].startswith("550")
        assert hard["company"] == "Acme Corp"
        assert hard["first_name"] == "Bo"
        assert hard["last_name"] == "Uncer"

    def test_404_for_unknown_campaign(
        self, client, bounces_campaign, seed_user_with_role
    ):
        resp = client.get(
            "/api/campaigns/00000000-0000-0000-0000-000000000000/bounces",
            headers=_auth(client),
        )
        assert resp.status_code == 404


class TestCampaignBouncesCsv:
    """GET /api/campaigns/<id>/bounces.csv."""

    def test_returns_csv_with_documented_columns(
        self, client, bounces_campaign, seed_user_with_role
    ):
        camp = bounces_campaign["campaign"]
        resp = client.get(
            f"/api/campaigns/{camp.id}/bounces.csv", headers=_auth(client)
        )
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        disposition = resp.headers.get("Content-Disposition", "")
        assert "attachment" in disposition
        assert "bounces-eventfest-2026-" in disposition.lower()

        body = resp.get_data(as_text=True)
        lines = body.strip().splitlines()
        # Header row + 3 bounce rows.
        assert len(lines) == 4, body
        assert lines[0].startswith(
            "Contact ID,Email,First Name,Last Name,Company,"
            "Bounce Type,Bounced At,Status,Error Message"
        )
        assert "bouncer@x.com" in body
        assert "softie@x.com" in body
        assert "failed@x.com" in body
        # Preview + superseded + delivered must not leak into the export.
        assert "preview@x.com" not in body
        assert "superseded@x.com" not in body
        assert "delivered@x.com" not in body


class TestCampaignBouncesTenantIsolation:
    """A foreign-tenant campaign must 404, not leak rows."""

    def test_foreign_tenant_campaign_returns_404(
        self, client, db, bounces_campaign, seed_user_with_role
    ):
        from api.models import Campaign, Tenant

        other_tenant = Tenant(name="Other Inc", slug="other-inc", is_active=True)
        db.session.add(other_tenant)
        db.session.flush()
        foreign_campaign = Campaign(
            tenant_id=other_tenant.id,
            name="Foreign Campaign",
            status="sending",
        )
        db.session.add(foreign_campaign)
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{foreign_campaign.id}/bounces",
            headers=_auth(client),
        )
        assert resp.status_code == 404

        resp_csv = client.get(
            f"/api/campaigns/{foreign_campaign.id}/bounces.csv",
            headers=_auth(client),
        )
        assert resp_csv.status_code == 404
