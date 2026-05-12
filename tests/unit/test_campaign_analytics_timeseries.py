"""Unit tests for GET /api/campaigns/<id>/analytics/timeseries endpoint.

Covers BL-1037: bucket-aligned event counts (sent/delivered/opened/clicked/
bounced/unsubscribed) over a time range, for OutreachTab + Echo time-series.
"""

import json
from datetime import datetime, timedelta, timezone

from api.models import (
    Campaign,
    CampaignContact,
    Contact,
    EmailSendLog,
    Message,
    Tenant,
)
from tests.conftest import auth_header


# ─── Helpers ──────────────────────────────────────────────────────────────


def _make_campaign(db, tenant_id, name="TS Campaign"):
    c = Campaign(
        tenant_id=tenant_id,
        name=name,
        status="review",
        generation_config=json.dumps({}),
    )
    db.session.add(c)
    db.session.flush()
    return c


def _make_contact(db, tenant_id, first_name="Test", email=None):
    ct = Contact(
        tenant_id=tenant_id,
        first_name=first_name,
        last_name="User",
        email_address=email or f"{first_name.lower()}@test.com",
    )
    db.session.add(ct)
    db.session.flush()
    return ct


def _make_campaign_contact(db, campaign_id, contact_id, tenant_id):
    cc = CampaignContact(
        campaign_id=campaign_id,
        contact_id=contact_id,
        tenant_id=tenant_id,
        status="generated",
    )
    db.session.add(cc)
    db.session.flush()
    return cc


def _make_message(db, tenant_id, contact_id, campaign_contact_id):
    m = Message(
        tenant_id=tenant_id,
        contact_id=contact_id,
        campaign_contact_id=campaign_contact_id,
        channel="email",
        sequence_step=1,
        body="Hi",
        subject="Subj",
        status="sent",
    )
    db.session.add(m)
    db.session.flush()
    return m


def _make_send_log(
    db,
    tenant_id,
    message_id,
    sent_at=None,
    delivered_at=None,
    opened_at=None,
    clicked_at=None,
    bounced_at=None,
    unsubscribed_at=None,
    status="sent",
):
    log = EmailSendLog(
        tenant_id=tenant_id,
        message_id=message_id,
        status=status,
        from_email="sender@test.com",
        to_email="recipient@test.com",
        sent_at=sent_at,
        delivered_at=delivered_at,
        opened_at=opened_at,
        clicked_at=clicked_at,
        bounced_at=bounced_at,
        unsubscribed_at=unsubscribed_at,
    )
    db.session.add(log)
    db.session.flush()
    return log


def _setup_campaign_with_events(db, tenant_id, events):
    """Create a campaign + one send log per event dict.

    events: list of dicts like {"sent_at": dt, "opened_at": dt, ...}
    """
    campaign = _make_campaign(db, tenant_id)
    for idx, ev in enumerate(events):
        ct = _make_contact(db, tenant_id, first_name=f"C{idx}")
        cc = _make_campaign_contact(db, campaign.id, ct.id, tenant_id)
        m = _make_message(db, tenant_id, ct.id, cc.id)
        _make_send_log(db, tenant_id, m.id, **ev)
    db.session.commit()
    return campaign


# ─── Tests ────────────────────────────────────────────────────────────────


class TestTimeseriesBasics:
    """Bucket counts, default range, empty buckets."""

    def test_empty_campaign_returns_zero_buckets(
        self, client, seed_companies_contacts, db
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/timeseries",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["campaign_id"] == str(campaign.id)
        assert data["range"] == "7d"
        assert data["bucket"] == "day"
        # 7d with day bucket → 7 or 8 buckets depending on boundary alignment
        assert 7 <= len(data["buckets"]) <= 8
        # All buckets zero
        for b in data["buckets"]:
            assert b["sent"] == 0
            assert b["delivered"] == 0
            assert b["opened"] == 0
            assert b["clicked"] == 0
            assert b["bounced"] == 0
            assert b["unsubscribed"] == 0
            # ISO-8601 UTC with trailing Z
            assert b["bucket_start"].endswith("Z")

    def test_events_bucket_into_correct_days(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]

        now = datetime.now(timezone.utc).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        day_ago = now - timedelta(days=1)
        two_days_ago = now - timedelta(days=2)

        campaign = _setup_campaign_with_events(
            db,
            tenant.id,
            [
                # 2 days ago: 1 sent, 1 delivered, 1 opened
                {
                    "sent_at": two_days_ago,
                    "delivered_at": two_days_ago,
                    "opened_at": two_days_ago,
                },
                # 1 day ago: 1 sent, 1 delivered
                {"sent_at": day_ago, "delivered_at": day_ago},
                # Today: 1 sent, 1 delivered, 1 clicked
                {
                    "sent_at": now,
                    "delivered_at": now,
                    "clicked_at": now,
                },
            ],
        )

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/timeseries?range=7d&bucket=day",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()

        totals = {
            "sent": sum(b["sent"] for b in data["buckets"]),
            "delivered": sum(b["delivered"] for b in data["buckets"]),
            "opened": sum(b["opened"] for b in data["buckets"]),
            "clicked": sum(b["clicked"] for b in data["buckets"]),
        }
        assert totals["sent"] == 3
        assert totals["delivered"] == 3
        assert totals["opened"] == 1
        assert totals["clicked"] == 1

    def test_24h_range_uses_hour_buckets_by_default(
        self, client, seed_companies_contacts, db
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]

        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/timeseries?range=24h",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["range"] == "24h"
        assert data["bucket"] == "hour"
        # 24h with hour buckets → 24 or 25 buckets
        assert 24 <= len(data["buckets"]) <= 25

    def test_30d_range_uses_day_buckets(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]

        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/timeseries?range=30d",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["range"] == "30d"
        assert data["bucket"] == "day"
        assert 30 <= len(data["buckets"]) <= 31


class TestTimeseriesTenantIsolation:
    """Cross-tenant access returns 404."""

    def test_foreign_tenant_campaign_returns_404(
        self, client, seed_companies_contacts, db
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        # Create a second tenant with its own campaign
        other = Tenant(name="Other Corp", slug="other-corp", is_active=True)
        db.session.add(other)
        db.session.flush()
        other_campaign = _make_campaign(db, other.id, name="Other TS")
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{other_campaign.id}/analytics/timeseries",
            headers=headers,
        )
        # 404 (not 403) to avoid existence disclosure
        assert resp.status_code == 404


class TestTimeseriesValidation:
    """Invalid query params return 400 with clear errors."""

    def test_invalid_range_returns_400(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/timeseries?range=bogus",
            headers=headers,
        )
        assert resp.status_code == 400
        err = resp.get_json().get("error", "").lower()
        assert "range" in err

    def test_invalid_bucket_returns_400(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/timeseries?bucket=minute",
            headers=headers,
        )
        assert resp.status_code == 400
        err = resp.get_json().get("error", "").lower()
        assert "bucket" in err

    def test_nonexistent_campaign_returns_404(
        self, client, seed_companies_contacts, db
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        # Random UUID that does not exist
        resp = client.get(
            "/api/campaigns/11111111-1111-1111-1111-111111111111/analytics/timeseries",
            headers=headers,
        )
        assert resp.status_code == 404


class TestTimeseriesMetrics:
    """Each metric increments only on its own timestamp."""

    def test_bounced_and_unsubscribed_counted_separately(
        self, client, seed_companies_contacts, db
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]

        now = datetime.now(timezone.utc).replace(
            hour=12, minute=0, second=0, microsecond=0
        )

        campaign = _setup_campaign_with_events(
            db,
            tenant.id,
            [
                {"sent_at": now, "bounced_at": now},
                {"sent_at": now, "delivered_at": now, "unsubscribed_at": now},
            ],
        )

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/timeseries?range=7d&bucket=day",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()

        totals = {
            key: sum(b[key] for b in data["buckets"])
            for key in ("sent", "delivered", "bounced", "unsubscribed")
        }
        assert totals["sent"] == 2
        assert totals["delivered"] == 1
        assert totals["bounced"] == 1
        assert totals["unsubscribed"] == 1


class TestTimeseriesResponseShape:
    """Contract: keys, bucket order, ISO-8601 format."""

    def test_response_keys_and_ordering(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/timeseries?range=7d&bucket=day",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # Top-level contract
        assert set(data.keys()) >= {"campaign_id", "range", "bucket", "buckets"}
        # Buckets in chronological order
        starts = [b["bucket_start"] for b in data["buckets"]]
        assert starts == sorted(starts)
        # Each bucket carries all six metric keys
        expected = {
            "bucket_start",
            "sent",
            "delivered",
            "opened",
            "clicked",
            "bounced",
            "unsubscribed",
        }
        for b in data["buckets"]:
            assert set(b.keys()) == expected


class TestTimeseriesExclusions:
    """Rows that must not appear in the time-series."""

    def test_superseded_rows_excluded(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]

        now = datetime.now(timezone.utc).replace(
            hour=12, minute=0, second=0, microsecond=0
        )

        # One "winning" sent row + one superseded retry row for a single
        # message should count as just one send, not two (BL-1029).
        campaign = _make_campaign(db, tenant.id)
        ct = _make_contact(db, tenant.id, "Rep")
        cc = _make_campaign_contact(db, campaign.id, ct.id, tenant.id)
        m = _make_message(db, tenant.id, ct.id, cc.id)

        # Superseded first attempt (bounced, then retried)
        log1 = _make_send_log(
            db, tenant.id, m.id, sent_at=now, bounced_at=now, status="bounced"
        )
        # Winning retry
        _make_send_log(
            db, tenant.id, m.id, sent_at=now, delivered_at=now, status="delivered"
        )
        # Mark the first attempt as superseded
        log1.superseded_at = now
        db.session.commit()

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/timeseries?range=7d&bucket=day",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        totals = {
            key: sum(b[key] for b in data["buckets"])
            for key in ("sent", "delivered", "bounced")
        }
        # Only the winning row contributes: 1 sent, 1 delivered, 0 bounced
        assert totals["sent"] == 1
        assert totals["delivered"] == 1
        assert totals["bounced"] == 0


class TestTimeseriesLongRange:
    """range=all with an old event returns buckets spanning the whole window."""

    def test_range_all_spans_oldest_event(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant = seed_companies_contacts["tenant"]

        six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)
        campaign = _setup_campaign_with_events(
            db,
            tenant.id,
            [
                {"sent_at": six_months_ago, "delivered_at": six_months_ago},
                {"sent_at": datetime.now(timezone.utc)},
            ],
        )

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/timeseries?range=all&bucket=day",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # At least ~180 day buckets
        assert len(data["buckets"]) >= 180
        totals = {"sent": sum(b["sent"] for b in data["buckets"])}
        assert totals["sent"] == 2
