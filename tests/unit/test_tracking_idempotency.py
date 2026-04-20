"""Idempotency tests for /api/tracking/microsite-event (Phase 3 WIRE-02).

Covers:
1. Duplicate POST with identical (token, event, timestamp) tuple returns
   `duplicate: true` on the second call and persists exactly ONE Activity row.
2. Same token+event but different timestamp (1s apart) persists as two
   distinct Activity rows (both `duplicate: false`).
3. Same token+timestamp but different event type persists as two distinct
   Activity rows (both `duplicate: false`).
4. Bypassing the service-layer check and calling `db.session.add` directly
   with the same tuple raises `IntegrityError` (unique partial index from
   migration 060 enforces the invariant as a DB constraint).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from api.models import Activity, Contact, db


@pytest.fixture
def api_key(app):
    """Configure the X-API-Key the tracking endpoint expects."""
    key = "test-tracking-idempotency-key"
    app.config["UA_INVITE_API_KEY"] = key
    yield key
    app.config["UA_INVITE_API_KEY"] = ""


@pytest.fixture
def seed_contact(db, seed_tenant):
    """Create a contact for idempotency tests."""
    contact = Contact(
        tenant_id=seed_tenant.id,
        first_name="Irena",
        last_name="Duplicate",
        email_address="irena@example.com",
    )
    db.session.add(contact)
    db.session.commit()
    return contact


@pytest.fixture
def microsite_unique_index(app, db):
    """Apply the migration 060 unique partial index at test-setup time.

    The test DB is a fresh SQLite instance per-test; the production migration
    runs against Postgres. SQLite supports partial unique indexes, so we issue
    raw ``CREATE UNIQUE INDEX IF NOT EXISTS`` DDL matching migration 060's
    invariant so Test 4 can prove the DB-level enforcement.
    """
    with app.app_context():
        db.session.execute(
            db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "idx_activities_microsite_dedup "
                "ON activities (contact_id, event_type, occurred_at) "
                "WHERE source = 'microsite' AND contact_id IS NOT NULL"
            )
        )
        db.session.commit()
    yield
    with app.app_context():
        try:
            db.session.execute(
                db.text("DROP INDEX IF EXISTS idx_activities_microsite_dedup")
            )
            db.session.commit()
        except Exception:
            db.session.rollback()


def _headers(api_key):
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


def _count_activities(contact_id):
    return Activity.query.filter_by(
        contact_id=contact_id, source="microsite"
    ).count()


class TestTrackingIdempotency:
    """POST /api/tracking/microsite-event idempotency."""

    def test_duplicate_post_is_idempotent(
        self, client, api_key, seed_contact, microsite_unique_index
    ):
        """Test 1: same (token, event, timestamp) → only one Activity row."""
        payload = {
            "token": "t1",
            "event": "invite_redeemed",
            "data": {"email": "irena@example.com"},
            "timestamp": "2026-04-18T12:00:00Z",
        }

        # First POST — persists.
        r1 = client.post(
            "/api/tracking/microsite-event",
            json=payload,
            headers=_headers(api_key),
        )
        assert r1.status_code == 200
        b1 = r1.get_json()
        assert b1["ok"] is True
        assert b1["matched"] is True
        assert b1["duplicate"] is False

        # Second POST (identical) — returns duplicate, no second insert.
        r2 = client.post(
            "/api/tracking/microsite-event",
            json=payload,
            headers=_headers(api_key),
        )
        assert r2.status_code == 200
        b2 = r2.get_json()
        assert b2["ok"] is True
        assert b2["matched"] is True
        assert b2["duplicate"] is True

        with client.application.app_context():
            assert _count_activities(seed_contact.id) == 1

    def test_different_timestamp_is_not_duplicate(
        self, client, api_key, seed_contact, microsite_unique_index
    ):
        """Test 2: same token+event, different timestamp → two rows."""
        base = {
            "token": "t2",
            "event": "product_viewed",
            "data": {"email": "irena@example.com", "product_id": "complicite"},
        }

        r1 = client.post(
            "/api/tracking/microsite-event",
            json={**base, "timestamp": "2026-04-18T12:00:00Z"},
            headers=_headers(api_key),
        )
        r2 = client.post(
            "/api/tracking/microsite-event",
            json={**base, "timestamp": "2026-04-18T12:00:01Z"},
            headers=_headers(api_key),
        )

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.get_json()["duplicate"] is False
        assert r2.get_json()["duplicate"] is False

        with client.application.app_context():
            assert _count_activities(seed_contact.id) == 2

    def test_different_event_type_is_not_duplicate(
        self, client, api_key, seed_contact, microsite_unique_index
    ):
        """Test 3: same token+timestamp, different event → two rows."""
        base = {
            "token": "t3",
            "data": {"email": "irena@example.com"},
            "timestamp": "2026-04-18T12:00:00Z",
        }

        r1 = client.post(
            "/api/tracking/microsite-event",
            json={**base, "event": "invite_redeemed"},
            headers=_headers(api_key),
        )
        r2 = client.post(
            "/api/tracking/microsite-event",
            json={**base, "event": "product_viewed"},
            headers=_headers(api_key),
        )

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.get_json()["duplicate"] is False
        assert r2.get_json()["duplicate"] is False

        with client.application.app_context():
            assert _count_activities(seed_contact.id) == 2

    def test_idempotency_survives_race_via_db_constraint(
        self, client, app, db, seed_contact, microsite_unique_index
    ):
        """Test 4: even if two Activity rows bypass the service-layer check
        and hit the DB directly with the same tuple, the DB unique partial
        index enforces the invariant — IntegrityError on the second commit.
        """
        occurred_at = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)

        with app.app_context():
            # Re-fetch contact inside app context (new session).
            contact = db.session.get(Contact, seed_contact.id)
            assert contact is not None

            a1 = Activity(
                tenant_id=contact.tenant_id,
                contact_id=contact.id,
                activity_name="invite_redeemed",
                activity_type="event",
                source="microsite",
                event_type="invite_redeemed",
                occurred_at=occurred_at,
                timestamp=occurred_at,
                payload={},
            )
            db.session.add(a1)
            db.session.commit()

            # Second identical row → must raise IntegrityError.
            a2 = Activity(
                tenant_id=contact.tenant_id,
                contact_id=contact.id,
                activity_name="invite_redeemed",
                activity_type="event",
                source="microsite",
                event_type="invite_redeemed",
                occurred_at=occurred_at,
                timestamp=occurred_at,
                payload={},
            )
            with pytest.raises(IntegrityError):
                db.session.add(a2)
                db.session.commit()
            db.session.rollback()

            # Final state: exactly one row.
            assert _count_activities(contact.id) == 1
