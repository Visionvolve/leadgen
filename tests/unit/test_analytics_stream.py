"""Unit tests for GET /api/campaigns/<id>/analytics/stream (SSE).

BL-1039 — live analytics Server-Sent Events stream.

Tests exercise the generator function directly (not the HTTP client) so we
can monkeypatch ``time.sleep`` / ``time.time`` to step through the polling
loop deterministically without waiting 5+ seconds per assertion.
"""

import json

from api.models import (
    Campaign,
    CampaignContact,
    Contact,
    EmailSendLog,
    Message,
)
from api.routes.campaign_routes import (
    _analytics_stream_gen,
    _compute_campaign_analytics,
    _compute_analytics_delta,
)
from tests.conftest import auth_header


# ── helpers ──────────────────────────────────────────────────────────────


def _make_campaign(db, tenant_id, name="Stream Campaign"):
    c = Campaign(
        tenant_id=tenant_id,
        name=name,
        status="review",
        generation_config=json.dumps({}),
    )
    db.session.add(c)
    db.session.flush()
    return c


def _make_contact(db, tenant_id, first_name, email="user@test.com"):
    ct = Contact(
        tenant_id=tenant_id,
        first_name=first_name,
        last_name="Test",
        email_address=email,
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


def _make_message(db, tenant_id, contact_id, cc_id, status="sent", step=1):
    m = Message(
        tenant_id=tenant_id,
        contact_id=contact_id,
        campaign_contact_id=cc_id,
        channel="email",
        sequence_step=step,
        body="Hello",
        subject="Hi",
        status=status,
    )
    db.session.add(m)
    db.session.flush()
    return m


def _make_log(db, tenant_id, message_id, **kwargs):
    log = EmailSendLog(
        tenant_id=tenant_id,
        message_id=message_id,
        status=kwargs.pop("status", "delivered"),
        from_email="sender@test.com",
        to_email="user@test.com",
        **kwargs,
    )
    db.session.add(log)
    return log


def _parse_sse_event(chunk):
    """Parse one SSE message into (event, data) tuple.

    An SSE comment line starting with ':' returns ('heartbeat', '').
    """
    if chunk.startswith(":"):
        return ("heartbeat", chunk.split("\n", 1)[0].lstrip(":").strip())

    event = None
    data_lines = []
    for line in chunk.rstrip("\n").split("\n"):
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    data = "\n".join(data_lines)
    return (event, data)


class _FakeClock:
    """Replaces time.time with a manually advanced monotonic counter.

    Use with ``monkeypatch.setattr("api.routes.campaign_routes.time.time", clock)``.
    """

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# ── tests ────────────────────────────────────────────────────────────────


class TestComputeAnalyticsHelper:
    """_compute_campaign_analytics returns the same shape as the HTTP endpoint."""

    def test_empty_campaign_returns_zeros(self, client, seed_companies_contacts, db):
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        result = _compute_campaign_analytics(campaign.id, tenant.id)

        assert result is not None
        assert result["messages"]["total"] == 0
        assert result["engagement"]["opened"] == 0
        assert result["engagement"]["delivered"] == 0
        assert result["timeline"]["created_at"] is not None
        # Shape sanity — keys required by spec §5.8 payload
        for key in (
            "messages",
            "sending",
            "contacts",
            "cost",
            "engagement",
            "timeline",
            "microsite",
        ):
            assert key in result

    def test_returns_none_for_other_tenant(self, client, seed_companies_contacts, db):
        """Tenant isolation: campaign belongs to tenant A, query as tenant B → None."""
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        # Different tenant_id → no match
        result = _compute_campaign_analytics(campaign.id, "other-tenant-id")
        assert result is None

    def test_returns_none_for_missing_campaign(self, client, seed_companies_contacts):
        tenant = seed_companies_contacts["tenant"]
        result = _compute_campaign_analytics(
            "00000000-0000-0000-0000-000000000000", tenant.id
        )
        assert result is None


class TestComputeAnalyticsDelta:
    """_compute_analytics_delta surfaces only changed engagement counters."""

    def test_no_change_returns_empty(self):
        snap = {
            "engagement": {"opened": 1, "clicked": 2, "delivered": 3},
            "messages": {"total": 5},
        }
        assert _compute_analytics_delta(snap, snap) == {}

    def test_engagement_delta_reports_absolute_and_change(self):
        prev = {
            "engagement": {"opened": 1, "clicked": 2, "delivered": 3},
            "messages": {"total": 5},
        }
        curr = {
            "engagement": {"opened": 3, "clicked": 2, "delivered": 4},
            "messages": {"total": 6},
        }

        delta = _compute_analytics_delta(prev, curr)

        # Only changed keys appear
        assert "opened" in delta["engagement"]
        assert delta["engagement"]["opened"]["value"] == 3
        assert delta["engagement"]["opened"]["change"] == 2
        assert delta["engagement"]["delivered"]["change"] == 1
        assert "clicked" not in delta["engagement"]
        # Messages total also reported
        assert delta["messages"]["total"]["change"] == 1

    def test_delta_resolves_dotted_parent_path(self):
        """``sending.email`` in _STREAM_DELTA_KEYS is a path (traversed),
        NOT a flat dict key. A change in ``snapshot["sending"]["email"]``
        must surface under ``delta["sending"]["email"][...]``.

        Regression guard for code review Nit #5: if the resolver treated
        ``"sending.email"`` as a flat key, the lookup would always miss
        and sending-channel deltas would silently drop.
        """
        prev = {
            "sending": {
                "email": {"sent": 1, "delivered": 1, "bounced": 0},
                "linkedin": {"sent": 0},
            },
            "engagement": {"opened": 0},
            "messages": {"total": 1},
            "microsite": {"visits": 0},
        }
        curr = {
            "sending": {
                "email": {"sent": 3, "delivered": 2, "bounced": 1},
                "linkedin": {"sent": 0},
            },
            "engagement": {"opened": 0},
            "messages": {"total": 1},
            "microsite": {"visits": 0},
        }

        delta = _compute_analytics_delta(prev, curr)

        # Dotted parent produces nested output under "sending" → "email"
        assert "sending" in delta, (
            "dotted parent 'sending.email' must produce a 'sending' key in delta"
        )
        assert "email" in delta["sending"], (
            "changed sending-channel counters must surface under sending.email"
        )
        assert delta["sending"]["email"]["sent"]["value"] == 3
        assert delta["sending"]["email"]["sent"]["change"] == 2
        assert delta["sending"]["email"]["delivered"]["change"] == 1
        assert delta["sending"]["email"]["bounced"]["change"] == 1
        # Unchanged keys must NOT appear
        assert "engagement" not in delta
        assert "messages" not in delta
        assert "microsite" not in delta


class TestAnalyticsStreamGenerator:
    """_analytics_stream_gen yields SSE-formatted chunks."""

    def test_first_chunk_is_snapshot(
        self, client, seed_companies_contacts, db, monkeypatch
    ):
        """Initial yield must be an ``event: snapshot`` frame with full metrics."""
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        # Stop the loop after the initial snapshot by raising GeneratorExit.
        gen = _analytics_stream_gen(campaign.id, tenant.id, poll_interval=0.01)
        first = next(gen)
        gen.close()

        event, data = _parse_sse_event(first)
        assert event == "snapshot"
        payload = json.loads(data)
        assert payload["campaign_id"] == campaign.id
        assert "metrics" in payload
        assert payload["metrics"]["engagement"]["opened"] == 0

    def test_heartbeat_emitted_when_no_change(
        self, client, seed_companies_contacts, db, monkeypatch
    ):
        """After ``heartbeat_interval`` seconds with no metric change, a ``:heartbeat`` is emitted."""
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        clock = _FakeClock(start=1000.0)
        monkeypatch.setattr("api.routes.campaign_routes.time.time", clock)

        # Sleep must be a no-op but advance the fake clock so the heartbeat
        # threshold is crossed on the next iteration.
        def fake_sleep(seconds):
            clock.advance(seconds)

        monkeypatch.setattr("api.routes.campaign_routes.time.sleep", fake_sleep)

        gen = _analytics_stream_gen(
            campaign.id,
            tenant.id,
            poll_interval=31,  # sleep advances clock past 30s heartbeat threshold
            heartbeat_interval=30,
            posthog_refresh_interval=9999,
        )
        chunks = []
        # Consume: snapshot + one polling cycle
        chunks.append(next(gen))
        chunks.append(next(gen))
        gen.close()

        first_event, _ = _parse_sse_event(chunks[0])
        second_event, _ = _parse_sse_event(chunks[1])
        assert first_event == "snapshot"
        assert second_event == "heartbeat"

    def test_update_emitted_when_counters_change(
        self, client, seed_companies_contacts, db, monkeypatch
    ):
        """When engagement counters change between polls, an ``update`` event fires."""
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        ct = _make_contact(db, tenant.id, "Alice")
        cc = _make_campaign_contact(db, campaign.id, ct.id, tenant.id)
        msg = _make_message(db, tenant.id, ct.id, cc.id)
        db.session.commit()

        # Snapshot ids before entering the generator — the generator's
        # ``finally: db.session.remove()`` will detach ORM instances on
        # close.
        campaign_id_val = campaign.id
        tenant_id_val = tenant.id
        msg_id_val = msg.id

        clock = _FakeClock()
        monkeypatch.setattr("api.routes.campaign_routes.time.time", clock)

        # Arrange: the generator will call time.sleep once between the
        # snapshot and the first poll. While "sleeping" we mutate the DB
        # to simulate a webhook arrival, then the next poll observes the
        # delta and emits ``update``.
        from datetime import datetime

        def fake_sleep(seconds):
            # Mutate DB inside the fake sleep — this simulates a webhook
            # writing a new row while the stream is idle.
            _make_log(
                db,
                tenant_id_val,
                msg_id_val,
                status="delivered",
                opened_at=datetime.utcnow(),
                delivered_at=datetime.utcnow(),
            )
            db.session.commit()
            clock.advance(seconds)

        monkeypatch.setattr("api.routes.campaign_routes.time.sleep", fake_sleep)

        gen = _analytics_stream_gen(
            campaign_id_val,
            tenant_id_val,
            poll_interval=1,
            heartbeat_interval=9999,
            posthog_refresh_interval=9999,
        )
        chunks = [next(gen), next(gen)]
        gen.close()

        first_event, _ = _parse_sse_event(chunks[0])
        second_event, second_data = _parse_sse_event(chunks[1])
        assert first_event == "snapshot"
        assert second_event == "update"

        payload = json.loads(second_data)
        assert payload["campaign_id"] == campaign_id_val
        assert "delta" in payload
        assert payload["delta"]["engagement"]["opened"]["value"] == 1
        assert payload["delta"]["engagement"]["opened"]["change"] == 1

    def test_generator_exit_closes_cleanly(
        self, client, seed_companies_contacts, db, monkeypatch
    ):
        """GeneratorExit on client disconnect must not propagate as an exception."""
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        monkeypatch.setattr("api.routes.campaign_routes.time.sleep", lambda s: None)

        gen = _analytics_stream_gen(campaign.id, tenant.id, poll_interval=1)
        _ = next(gen)  # prime
        # Simulate client disconnect
        gen.close()  # must not raise

    def test_transient_db_error_does_not_kill_stream(
        self, client, seed_companies_contacts, db, monkeypatch
    ):
        """A transient ``OperationalError`` during a poll must be skipped,
        not propagated. The next successful poll must still emit a delta.

        Guards against RDS failover / connection-drop scenarios killing
        every open SSE stream on the fleet.
        """
        from datetime import datetime

        from sqlalchemy.exc import OperationalError

        from api.routes import campaign_routes

        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        ct = _make_contact(db, tenant.id, "Alice")
        cc = _make_campaign_contact(db, campaign.id, ct.id, tenant.id)
        msg = _make_message(db, tenant.id, ct.id, cc.id)
        db.session.commit()

        campaign_id_val = campaign.id
        tenant_id_val = tenant.id
        msg_id_val = msg.id

        clock = _FakeClock()
        monkeypatch.setattr("api.routes.campaign_routes.time.time", clock)
        monkeypatch.setattr(
            "api.routes.campaign_routes.time.sleep",
            lambda s: clock.advance(s),
        )

        # Wrap the real helper so that the FIRST poll call (call #2 — the
        # initial snapshot is call #1) raises OperationalError, and the
        # second poll (call #3) returns real data after we've written a
        # new row.
        real_compute = campaign_routes._compute_campaign_analytics
        call_count = {"n": 0}

        def flaky_compute(campaign_id, tenant_id):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise OperationalError(
                    "SELECT ...", {}, Exception("connection reset by peer")
                )
            # Before call #3 (second poll), persist a new delivered row so
            # a delta is observable after recovery.
            if call_count["n"] == 3:
                _make_log(
                    db,
                    tenant_id_val,
                    msg_id_val,
                    status="delivered",
                    delivered_at=datetime.utcnow(),
                    opened_at=datetime.utcnow(),
                )
                db.session.commit()
            return real_compute(campaign_id, tenant_id)

        monkeypatch.setattr(
            "api.routes.campaign_routes._compute_campaign_analytics",
            flaky_compute,
        )

        gen = _analytics_stream_gen(
            campaign_id_val,
            tenant_id_val,
            poll_interval=1,
            heartbeat_interval=9999,
            posthog_refresh_interval=9999,
        )
        # First yield: snapshot (call #1)
        snapshot_chunk = next(gen)
        # Second yield: after OperationalError (call #2, skipped) and
        # then a successful poll (call #3) that sees a new row — update.
        update_chunk = next(gen)
        gen.close()

        snap_event, _ = _parse_sse_event(snapshot_chunk)
        upd_event, upd_data = _parse_sse_event(update_chunk)
        assert snap_event == "snapshot"
        assert upd_event == "update", (
            "stream must recover from transient OperationalError and "
            "emit an update after a subsequent successful poll"
        )

        payload = json.loads(upd_data)
        assert payload["delta"]["engagement"]["delivered"]["value"] == 1
        # Sanity: the flaky helper was hit three times (snapshot + skipped + recovery)
        assert call_count["n"] == 3


class TestAnalyticsStreamEndpoint:
    """HTTP integration — the route wires auth + tenant validation correctly."""

    def test_missing_campaign_returns_404(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.get(
            "/api/campaigns/00000000-0000-0000-0000-000000000000/analytics/stream",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_cross_tenant_returns_404(self, client, seed_companies_contacts, db):
        """A user scoped to tenant B cannot open a stream for tenant A's campaign."""
        tenant = seed_companies_contacts["tenant"]
        campaign = _make_campaign(db, tenant.id)
        db.session.commit()

        from api.models import Tenant, User, UserTenantRole
        import uuid

        other_tenant = Tenant(name="Other", slug="other-corp", is_active=True)
        db.session.add(other_tenant)
        db.session.flush()

        other_user = User(
            email="other@test.com",
            password_hash=None,
            display_name="Other User",
            is_super_admin=False,
            is_active=True,
            iam_user_id=str(uuid.uuid4()),
        )
        db.session.add(other_user)
        db.session.flush()
        db.session.add(
            UserTenantRole(
                user_id=other_user.id,
                tenant_id=other_tenant.id,
                role="viewer",
                granted_by=other_user.id,
            )
        )
        db.session.commit()

        headers = auth_header(client, email="other@test.com")
        headers["X-Namespace"] = "other-corp"

        resp = client.get(
            f"/api/campaigns/{campaign.id}/analytics/stream", headers=headers
        )
        assert resp.status_code == 404

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/campaigns/abc/analytics/stream")
        assert resp.status_code == 401
