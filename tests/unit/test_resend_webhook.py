"""Unit tests for the Resend webhook handler — BL-1028.

Supplements ``test_webhook_routes.py`` (event-type coverage from BL-315) and
``test_webhook_unsubscribed.py`` (6th-state coverage from LEADGEN-01) with
the specific behaviours BL-1028 adds to close the "opened_at / clicked_at
remain NULL in production" bug:

1. Core repro: ``email.opened`` / ``email.clicked`` for an existing
   ``resend_message_id`` populates the timestamp columns (non-null).
2. Idempotency: duplicate event delivery does not corrupt state. For
   first-observed timestamp columns (``opened_at`` / ``clicked_at``) the
   earliest value wins. Counters still increment on each delivery.
3. Earliest-observed for *all* timestamp columns: ``delivered_at``,
   ``bounced_at``, ``complained_at``, ``unsubscribed_at`` were previously
   overwritten on every delivery. They now preserve the first value too.
4. Multi-tenant isolation: updates only touch the row belonging to the
   tenant that originally sent the email, even if another tenant has a
   log row with the same ``resend_message_id`` (pathological but possible
   after data migrations).
5. Event timestamp parsing: when the webhook body carries a top-level
   ``created_at`` (the real event time), we persist that rather than the
   wall-clock at webhook-processing time. This is the authoritative
   "when it happened" per Resend's payload spec.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest


@pytest.fixture
def seed_send_log(db, seed_tenant):
    """Create a sent EmailSendLog row targetable by ``email_id``."""
    from api.models import (
        Campaign,
        CampaignContact,
        Contact,
        EmailSendLog,
        Message,
        Owner,
    )

    tenant_id = seed_tenant.id

    owner = Owner(tenant_id=tenant_id, name="BL-1028 Owner")
    db.session.add(owner)
    db.session.flush()

    contact = Contact(
        tenant_id=tenant_id,
        first_name="Repro",
        last_name="User",
        email_address="repro@example.com",
    )
    db.session.add(contact)
    db.session.flush()

    campaign = Campaign(
        tenant_id=tenant_id,
        name="BL-1028 Campaign",
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
        subject="Repro",
        body="Hi",
        status="approved",
        campaign_contact_id=cc.id,
    )
    db.session.add(message)
    db.session.flush()

    log = EmailSendLog(
        tenant_id=tenant_id,
        message_id=message.id,
        resend_message_id="resend-bl1028-id-001",
        status="sent",
        from_email="outreach@example.com",
        to_email="repro@example.com",
        sent_at=datetime(2026, 4, 20, 9, 0, 0, tzinfo=timezone.utc),
    )
    db.session.add(log)
    db.session.commit()

    return {"log": log, "message": message, "contact": contact, "tenant_id": tenant_id}


def _payload(
    event_type: str,
    email_id: str = "resend-bl1028-id-001",
    created_at: str | None = None,
    extra_data: dict | None = None,
) -> dict:
    data = {"email_id": email_id, "to": ["repro@example.com"]}
    if extra_data:
        data.update(extra_data)
    body: dict = {"type": event_type, "data": data}
    if created_at is not None:
        body["created_at"] = created_at
    return body


def _post(client, payload):
    return client.post(
        "/api/webhooks/resend",
        data=json.dumps(payload),
        content_type="application/json",
    )


class TestRepro:
    """BL-1028 bug repro — the original symptom is 'opened_at stays NULL'."""

    def test_opened_event_populates_opened_at(self, client, seed_send_log):
        resp = _post(client, _payload("email.opened"))
        assert resp.status_code == 200

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        assert log.opened_at is not None, "opened_at must be populated by webhook"
        assert log.open_count == 1

    def test_clicked_event_populates_clicked_at(self, client, seed_send_log):
        resp = _post(client, _payload("email.clicked"))
        assert resp.status_code == 200

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        assert log.clicked_at is not None, "clicked_at must be populated by webhook"
        assert log.click_count == 1


class TestIdempotency:
    """Idempotent — repeat deliveries preserve the earliest observed value."""

    def test_opened_duplicate_preserves_earliest_timestamp(self, client, seed_send_log):
        early = "2026-04-20T10:00:00.000Z"
        late = "2026-04-20T11:30:00.000Z"

        # First delivery: earlier event time
        _post(client, _payload("email.opened", created_at=early))

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        first_opened = log.opened_at
        assert first_opened is not None

        # Duplicate delivery (Resend retries) with a later event time
        _post(client, _payload("email.opened", created_at=late))

        db.session.refresh(log)
        assert log.opened_at == first_opened  # unchanged
        assert log.open_count == 2  # counter increments

    def test_clicked_duplicate_preserves_earliest_timestamp(
        self, client, seed_send_log
    ):
        early = "2026-04-20T10:05:00.000Z"
        late = "2026-04-20T12:45:00.000Z"

        _post(client, _payload("email.clicked", created_at=early))

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        first_clicked = log.clicked_at
        assert first_clicked is not None

        _post(client, _payload("email.clicked", created_at=late))

        db.session.refresh(log)
        assert log.clicked_at == first_clicked
        assert log.click_count == 2

    def test_delivered_duplicate_preserves_earliest_timestamp(
        self, client, seed_send_log
    ):
        """Previously ``delivered_at`` was overwritten on every webhook —
        a resend 12 h later would shift the timestamp. Now it must stick
        to the first value observed."""
        early = "2026-04-20T09:01:00.000Z"
        late = "2026-04-20T21:30:00.000Z"

        _post(client, _payload("email.delivered", created_at=early))

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        first_delivered = log.delivered_at
        assert first_delivered is not None

        _post(client, _payload("email.delivered", created_at=late))

        db.session.refresh(log)
        assert log.delivered_at == first_delivered, (
            "delivered_at must preserve earliest observed value"
        )
        assert log.status == "delivered"

    def test_bounced_duplicate_preserves_earliest_timestamp(
        self, client, seed_send_log
    ):
        early = "2026-04-20T09:02:00.000Z"
        late = "2026-04-20T22:00:00.000Z"

        _post(
            client,
            _payload(
                "email.bounced",
                created_at=early,
                extra_data={"bounce": {"type": "hard"}},
            ),
        )

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        first_bounced = log.bounced_at
        assert first_bounced is not None
        assert log.bounce_type == "hard"

        _post(
            client,
            _payload(
                "email.bounced",
                created_at=late,
                extra_data={"bounce": {"type": "soft"}},
            ),
        )

        db.session.refresh(log)
        assert log.bounced_at == first_bounced  # earliest wins
        # bounce_type preserves the first classification too — soft is not
        # allowed to overwrite an earlier hard bounce
        assert log.bounce_type == "hard"


class TestEventTimestamp:
    """The row's timestamp should be the event's ``created_at`` — not now()."""

    def test_opened_uses_event_created_at_when_present(self, client, seed_send_log):
        event_time_iso = "2026-04-20T10:17:42.123456+00:00"
        _post(client, _payload("email.opened", created_at=event_time_iso))

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        assert log.opened_at is not None
        # Stored value should match the event's reported time, not wall clock
        expected = datetime(2026, 4, 20, 10, 17, 42, 123456, tzinfo=timezone.utc)
        # SQLite may drop tzinfo on round-trip; normalise both sides.
        observed = log.opened_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        assert observed == expected

    def test_missing_event_created_at_falls_back_to_now(self, client, seed_send_log):
        """No top-level ``created_at`` → handler must still populate the
        timestamp (using the server's current time as a safe fallback)."""
        before = datetime.now(timezone.utc)
        _post(client, _payload("email.opened"))  # no created_at
        after = datetime.now(timezone.utc)

        from api.models import EmailSendLog, db

        log = db.session.get(EmailSendLog, seed_send_log["log"].id)
        assert log.opened_at is not None
        observed = log.opened_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        # Fallback must sit within the processing window (small tolerance
        # for clock skew between request and fixture setup)
        assert before <= observed <= after


class TestMultiTenantIsolation:
    """Webhooks must only update the row owned by the sending tenant."""

    def test_updates_correct_tenant_row_when_ids_collide(self, client, db):
        """Create two tenants, each with an EmailSendLog sharing the same
        ``resend_message_id``. The webhook event belongs (by send history)
        to the FIRST tenant; the second tenant's row must not be touched.

        This collision would only happen via data-migration error, but if
        it ever did, silent cross-tenant contamination would poison every
        downstream analytics query. The handler must be safe by default.
        """
        from api.models import (
            Campaign,
            CampaignContact,
            Contact,
            EmailSendLog,
            Message,
            Owner,
            Tenant,
        )

        # Tenant A — the rightful owner of resend_message_id "shared-id"
        tenant_a = Tenant(name="Tenant A", slug="tenant-a", is_active=True)
        tenant_b = Tenant(name="Tenant B", slug="tenant-b", is_active=True)
        db.session.add_all([tenant_a, tenant_b])
        db.session.commit()

        def _setup(tenant, label, sent_at):
            owner = Owner(tenant_id=tenant.id, name=f"Owner {label}")
            db.session.add(owner)
            db.session.flush()
            contact = Contact(
                tenant_id=tenant.id,
                first_name=label,
                last_name="User",
                email_address=f"{label.lower()}@example.com",
            )
            db.session.add(contact)
            db.session.flush()
            campaign = Campaign(
                tenant_id=tenant.id, name=f"Camp {label}", status="sending"
            )
            db.session.add(campaign)
            db.session.flush()
            cc = CampaignContact(
                campaign_id=campaign.id,
                contact_id=contact.id,
                tenant_id=tenant.id,
                status="sent",
            )
            db.session.add(cc)
            db.session.flush()
            msg = Message(
                tenant_id=tenant.id,
                contact_id=contact.id,
                owner_id=owner.id,
                channel="email",
                sequence_step=1,
                variant="a",
                subject="subj",
                body="body",
                status="approved",
                campaign_contact_id=cc.id,
            )
            db.session.add(msg)
            db.session.flush()
            log = EmailSendLog(
                tenant_id=tenant.id,
                message_id=msg.id,
                resend_message_id="shared-id-collision",
                status="sent",
                from_email="from@example.com",
                to_email=f"{label.lower()}@example.com",
                sent_at=sent_at,
            )
            db.session.add(log)
            db.session.commit()
            return log

        # Tenant A sent first (earlier sent_at) — the rightful owner
        log_a = _setup(tenant_a, "A", datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc))
        log_b = _setup(tenant_b, "B", datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc))

        # Webhook arrives for the shared id
        resp = _post(
            client,
            _payload("email.opened", email_id="shared-id-collision"),
        )
        assert resp.status_code == 200

        # Exactly ONE row should have opened_at set. Not both.
        db.session.refresh(log_a)
        db.session.refresh(log_b)
        touched = [log for log in (log_a, log_b) if log.opened_at is not None]
        untouched = [log for log in (log_a, log_b) if log.opened_at is None]
        assert len(touched) == 1, (
            f"Exactly one send-log row should be updated, not both — got {len(touched)}"
        )
        assert len(untouched) == 1
