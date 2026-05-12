"""Unit tests for campaign reach reporting (BL-1114, milestone v25 phase 11).

Covers:

- Aggregation correctness: seeded EmailSendLog rows yield the expected
  ``totals`` and ``rates`` blocks.
- Zero-division handling when ``targeted`` or ``sent`` is 0.
- Per-language breakdown sums back to total sent (CS + EN fallback +
  unlabelled non-templated rows).
- Tenant isolation: a campaign in tenant B is invisible to tenant A
  (returns 404).
- Timeline emits one row per UTC day, with sent/opened/clicked counted
  against the send day.
- Preview + superseded rows are excluded from the aggregation.
- Tenant-wide summary endpoint returns the rollup ordered by ``sent``
  descending.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.conftest import auth_header


@pytest.fixture
def reach_campaign(db, seed_tenant, seed_user_with_role):
    """Seed one campaign with 10 EmailSendLog rows spanning multiple
    event types, two template languages, and two send days.

    Layout (10 production rows + 2 excluded rows):

    targeted = 12   (campaign.total_contacts)

    Production rows (kind='production', superseded_at IS NULL):
      1. sent + delivered + opened + clicked          (cs, lang_fallback=False, day=01)
      2. sent + delivered + opened                    (cs, fallback=False, day=01)
      3. sent + delivered + opened                    (cs, fallback=False, day=01)
      4. sent + delivered                             (cs, fallback=False, day=02)
      5. sent + delivered                             (en, fallback=False, day=02)
      6. sent + delivered + opened + clicked          (en, fallback=False, day=02)
      7. sent + delivered + opened + unsubscribed     (cs, fallback=True,  day=02)
      8. sent + bounced (hard)                        (cs, fallback=False, day=02)
      9. sent + delivered + complained                (en, fallback=False, day=02)
      10. sent (non-templated, no language)            (None, None,          day=02)

    Excluded rows:
      11. PREVIEW (kind='preview', should NEVER count)
      12. SUPERSEDED (superseded_at IS NOT NULL, should NEVER count)

    Expected aggregates over the 10 production rows:
      targeted     = 12 (campaign.total_contacts)
      sent         = 10
      delivered    = 9 (rows 1-7, 9, 10 — row 8 bounced)
      opened       = 5 (rows 1,2,3,6,7)
      clicked      = 2 (rows 1,6)
      bounced      = 1 (row 8)
      complained   = 1 (row 9)
      unsubscribed = 1 (row 7)
    """
    from api.models import (
        Campaign,
        CampaignContact,
        Company,
        Contact,
        EmailSendLog,
        Message,
    )

    co = Company(tenant_id=seed_tenant.id, name="Reach Co")
    db.session.add(co)
    db.session.flush()

    campaign = Campaign(
        tenant_id=seed_tenant.id,
        name="Reach Test Campaign",
        status="sending",
        total_contacts=12,
    )
    db.session.add(campaign)
    db.session.flush()

    def _row(
        email,
        *,
        sent_at,
        delivered_at=None,
        opened_at=None,
        clicked_at=None,
        bounced_at=None,
        bounce_type=None,
        complained_at=None,
        unsubscribed_at=None,
        template_language=None,
        template_language_fallback=None,
        kind="production",
        superseded_at=None,
        status="sent",
    ):
        contact = Contact(
            tenant_id=seed_tenant.id,
            company_id=co.id,
            first_name="First",
            last_name="Last",
            email_address=email,
        )
        db.session.add(contact)
        db.session.flush()
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
            subject="hi",
            body="hi",
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
            to_email=email,
            sent_at=sent_at,
            delivered_at=delivered_at,
            opened_at=opened_at,
            clicked_at=clicked_at,
            bounced_at=bounced_at,
            bounce_type=bounce_type,
            complained_at=complained_at,
            unsubscribed_at=unsubscribed_at,
            template_language=template_language,
            template_language_fallback=template_language_fallback,
            kind=kind,
            superseded_at=superseded_at,
        )
        db.session.add(log)
        db.session.flush()
        return log

    day1 = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc)

    # 1
    _row(
        "a@x.com",
        sent_at=day1,
        delivered_at=day1,
        opened_at=day1,
        clicked_at=day1,
        template_language="cs",
        template_language_fallback=False,
    )
    # 2
    _row(
        "b@x.com",
        sent_at=day1,
        delivered_at=day1,
        opened_at=day1,
        template_language="cs",
        template_language_fallback=False,
    )
    # 3
    _row(
        "c@x.com",
        sent_at=day1,
        delivered_at=day1,
        opened_at=day1,
        template_language="cs",
        template_language_fallback=False,
    )
    # 4
    _row(
        "d@x.com",
        sent_at=day2,
        delivered_at=day2,
        template_language="cs",
        template_language_fallback=False,
    )
    # 5
    _row(
        "e@x.com",
        sent_at=day2,
        delivered_at=day2,
        template_language="en",
        template_language_fallback=False,
    )
    # 6
    _row(
        "f@x.com",
        sent_at=day2,
        delivered_at=day2,
        opened_at=day2,
        clicked_at=day2,
        template_language="en",
        template_language_fallback=False,
    )
    # 7 — fallback row
    _row(
        "g@x.com",
        sent_at=day2,
        delivered_at=day2,
        opened_at=day2,
        unsubscribed_at=day2,
        template_language="cs",
        template_language_fallback=True,
    )
    # 8 — bounced
    _row(
        "h@x.com",
        sent_at=day2,
        bounced_at=day2,
        bounce_type="hard",
        template_language="cs",
        template_language_fallback=False,
        status="bounced",
    )
    # 9 — complained
    _row(
        "i@x.com",
        sent_at=day2,
        delivered_at=day2,
        complained_at=day2,
        template_language="en",
        template_language_fallback=False,
    )
    # 10 — non-templated (no language)
    _row("j@x.com", sent_at=day2, delivered_at=day2)

    # 11 — preview (excluded)
    _row(
        "preview@x.com",
        sent_at=day2,
        delivered_at=day2,
        opened_at=day2,
        clicked_at=day2,
        template_language="cs",
        template_language_fallback=False,
        kind="preview",
    )
    # 12 — superseded (excluded)
    _row(
        "superseded@x.com",
        sent_at=day2,
        bounced_at=day2,
        bounce_type="soft",
        template_language="cs",
        template_language_fallback=False,
        superseded_at=day2,
        status="bounced",
    )

    db.session.commit()
    return {"campaign": campaign, "tenant": seed_tenant}


def _auth(client):
    return auth_header(client, email="user@test.com")


class TestCampaignReachJson:
    """GET /api/campaigns/<id>/reach."""

    def test_totals_match_seed(self, client, reach_campaign):
        camp = reach_campaign["campaign"]
        resp = client.get(f"/api/campaigns/{camp.id}/reach", headers=_auth(client))
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()

        assert body["campaign_id"] == str(camp.id)
        t = body["totals"]
        assert t["targeted"] == 12
        assert t["sent"] == 10
        assert t["delivered"] == 9
        assert t["opened"] == 5
        assert t["clicked"] == 2
        assert t["bounced"] == 1
        assert t["complained"] == 1
        assert t["unsubscribed"] == 1

    def test_rates_use_correct_denominators(self, client, reach_campaign):
        camp = reach_campaign["campaign"]
        resp = client.get(f"/api/campaigns/{camp.id}/reach", headers=_auth(client))
        assert resp.status_code == 200
        r = resp.get_json()["rates"]
        # sent_rate       = sent(10) / targeted(12)
        assert r["send_rate"] == round(10 / 12, 4)
        # delivery_rate   = delivered(9) / sent(10)
        assert r["delivery_rate"] == round(9 / 10, 4)
        # open_rate       = opened(5) / delivered(9)
        assert r["open_rate"] == round(5 / 9, 4)
        # click_rate      = clicked(2) / delivered(9)
        assert r["click_rate"] == round(2 / 9, 4)
        # bounce_rate     = bounced(1) / sent(10)
        assert r["bounce_rate"] == round(1 / 10, 4)
        # complaint_rate  = complained(1) / delivered(9)
        assert r["complaint_rate"] == round(1 / 9, 4)
        # unsubscribe_rate= unsub(1) / delivered(9)
        assert r["unsubscribe_rate"] == round(1 / 9, 4)

    def test_zero_division_when_no_sends(
        self, db, seed_tenant, seed_user_with_role, client
    ):
        """A campaign with zero sends still returns a valid 0% rates block."""
        from api.models import Campaign

        c = Campaign(
            tenant_id=seed_tenant.id, name="Empty", total_contacts=0, status="draft"
        )
        db.session.add(c)
        db.session.commit()
        resp = client.get(f"/api/campaigns/{c.id}/reach", headers=_auth(client))
        assert resp.status_code == 200
        body = resp.get_json()
        for rate in body["rates"].values():
            assert rate == 0.0
        assert body["totals"]["sent"] == 0
        assert body["timeline"] == []
        assert body["by_language"] == []

    def test_per_language_sums_to_templated_sent(self, client, reach_campaign):
        """Per-language sent counts should sum to (total sent − unlabelled)."""
        camp = reach_campaign["campaign"]
        resp = client.get(f"/api/campaigns/{camp.id}/reach", headers=_auth(client))
        body = resp.get_json()
        # Row 10 is unlabelled (no language) — 9 templated rows remain.
        templated_sent = sum(b["sent"] for b in body["by_language"])
        assert templated_sent == 9
        # The fallback row (#7) should be its own bucket with fallback=True.
        fallback_rows = [b for b in body["by_language"] if b["fallback"] is True]
        assert len(fallback_rows) == 1
        assert fallback_rows[0]["language"] == "cs"
        assert fallback_rows[0]["sent"] == 1

    def test_timeline_one_row_per_utc_day(self, client, reach_campaign):
        camp = reach_campaign["campaign"]
        resp = client.get(f"/api/campaigns/{camp.id}/reach", headers=_auth(client))
        timeline = resp.get_json()["timeline"]
        # Two seeded days. Day-1 has 3 sends (a,b,c), 3 opens, 1 click.
        # Day-2 has 7 sends (d,e,f,g,h,i,j), 2 opens (f,g), 1 click (f).
        assert len(timeline) == 2
        d1 = next(t for t in timeline if t["date"] == "2026-05-01")
        d2 = next(t for t in timeline if t["date"] == "2026-05-02")
        assert d1 == {"date": "2026-05-01", "sent": 3, "opened": 3, "clicked": 1}
        assert d2 == {"date": "2026-05-02", "sent": 7, "opened": 2, "clicked": 1}

    def test_preview_and_superseded_excluded(self, client, reach_campaign):
        """Sanity check — preview + superseded rows must not inflate counts."""
        camp = reach_campaign["campaign"]
        resp = client.get(f"/api/campaigns/{camp.id}/reach", headers=_auth(client))
        body = resp.get_json()
        # Preview row would have added +1 clicked; if it leaked the count
        # would be 3 not 2.
        assert body["totals"]["clicked"] == 2
        # Superseded row would have added a 2nd bounce.
        assert body["totals"]["bounced"] == 1

    def test_tenant_isolation(self, db, client, reach_campaign):
        """A campaign in tenant B is invisible to tenant A.

        We seed a second tenant with its own campaign, then attempt to
        read it using tenant-A's credentials. The endpoint must return
        404 (and never leak the campaign's existence).
        """
        from api.models import Campaign, Tenant

        # Tenant B + its campaign
        tb = Tenant(name="Other Corp", slug="other-corp", is_active=True)
        db.session.add(tb)
        db.session.flush()
        camp_b = Campaign(
            tenant_id=tb.id,
            name="Cross-tenant",
            status="sending",
            total_contacts=5,
        )
        db.session.add(camp_b)

        # User scoped only to tenant A — make sure the auth_header user
        # has no role on tenant B.
        db.session.commit()

        # The default seed_user_with_role only has a role on tenant A
        # (Test Corp). Hit tenant B's campaign with that user's token.
        resp = client.get(f"/api/campaigns/{camp_b.id}/reach", headers=_auth(client))
        assert resp.status_code == 404, resp.get_json()

    def test_unknown_campaign_returns_404(self, client, reach_campaign):
        import uuid

        resp = client.get(f"/api/campaigns/{uuid.uuid4()}/reach", headers=_auth(client))
        assert resp.status_code == 404


class TestCampaignReachSummary:
    """GET /api/campaigns/reach/summary."""

    def test_summary_includes_all_tenant_campaigns(self, client, reach_campaign, db):
        """Every campaign in the caller's tenant appears, sent-desc sorted."""
        from api.models import Campaign

        empty = Campaign(
            tenant_id=reach_campaign["tenant"].id,
            name="Zzz Empty One",
            status="draft",
            total_contacts=0,
        )
        db.session.add(empty)
        db.session.commit()

        resp = client.get("/api/campaigns/reach/summary", headers=_auth(client))
        assert resp.status_code == 200
        body = resp.get_json()
        names = [c["name"] for c in body["campaigns"]]
        assert "Reach Test Campaign" in names
        assert "Zzz Empty One" in names
        # The campaign with sends comes first (sent=10 > sent=0).
        assert body["campaigns"][0]["name"] == "Reach Test Campaign"
        assert body["campaigns"][0]["totals"]["sent"] == 10

    def test_summary_excludes_other_tenants(self, client, reach_campaign, db):
        """Summary must never include campaigns from other tenants."""
        from api.models import Campaign, Tenant

        tb = Tenant(name="Foreign Corp", slug="foreign-corp", is_active=True)
        db.session.add(tb)
        db.session.flush()
        db.session.add(
            Campaign(tenant_id=tb.id, name="Foreign Campaign", status="draft")
        )
        db.session.commit()

        resp = client.get("/api/campaigns/reach/summary", headers=_auth(client))
        names = [c["name"] for c in resp.get_json()["campaigns"]]
        assert "Foreign Campaign" not in names


class TestCampaignReachBadInputHardening:
    """Hotfix v25 — endpoints must NOT 500 on malformed campaign_id."""

    def test_reach_bad_campaign_id_returns_400(self, client, reach_campaign):
        resp = client.get("/api/campaigns/not-a-uuid/reach", headers=_auth(client))
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "invalid_campaign_id"}

    def test_reach_unknown_wellformed_campaign_id_returns_404(
        self, client, reach_campaign
    ):
        unknown = "00000000-0000-0000-0000-000000000000"
        resp = client.get(f"/api/campaigns/{unknown}/reach", headers=_auth(client))
        assert resp.status_code == 404
