"""Unit tests for the Resend reconciler (BL-1045).

The reconciler backfills engagement timestamps on ``email_send_log`` rows
whose webhook never fired (or fired before BL-1028's earliest-observed
guarantee landed). It queries Resend's ``GET /emails/{id}`` endpoint and
sets the column matched by the API's ``last_event`` field — but it is
strictly additive: non-NULL columns are never overwritten.

These tests exercise the core mapping logic, earliest-observed preservation,
HTTP error handling, and scoping by time window.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixture: seed a single send log row tied to a tenant with a Resend key.
# ---------------------------------------------------------------------------


@pytest.fixture
def seed_reconciler(db, seed_tenant):
    """Create a Tenant + Message + EmailSendLog with NULL engagement columns.

    Returns a dict with ``tenant``, ``log``, and ``api_key`` so tests can
    mutate fields before calling the reconciler.
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

    tenant = db.session.get(Tenant, seed_tenant.id)
    tenant.settings = json.dumps({"resend_api_key": "re_test_key_123"})

    owner = Owner(tenant_id=tenant.id, name="Reconciler Owner")
    db.session.add(owner)
    db.session.flush()

    contact = Contact(
        tenant_id=tenant.id,
        first_name="Recon",
        last_name="User",
        email_address="recon@example.com",
    )
    db.session.add(contact)
    db.session.flush()

    campaign = Campaign(tenant_id=tenant.id, name="Recon Campaign", status="sending")
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

    message = Message(
        tenant_id=tenant.id,
        contact_id=contact.id,
        owner_id=owner.id,
        channel="email",
        sequence_step=1,
        variant="a",
        subject="Recon",
        body="Hi",
        status="approved",
        campaign_contact_id=cc.id,
    )
    db.session.add(message)
    db.session.flush()

    now = datetime.now(timezone.utc)
    log = EmailSendLog(
        tenant_id=tenant.id,
        message_id=message.id,
        resend_message_id="resend-recon-id-001",
        status="sent",
        from_email="outreach@example.com",
        to_email="recon@example.com",
        sent_at=now - timedelta(days=2),
        created_at=now - timedelta(days=2),
    )
    db.session.add(log)
    db.session.commit()

    return {
        "tenant": tenant,
        "log": log,
        "api_key": "re_test_key_123",
    }


def _mock_resend_response(status_code: int, json_body: dict | None = None):
    """Build a mock ``requests.Response``-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    return resp


# ---------------------------------------------------------------------------
# Mapping: last_event → correct column populated.
# ---------------------------------------------------------------------------


class TestLastEventMapping:
    """Each ``last_event`` value lands on the matching timestamp column."""

    @pytest.mark.parametrize(
        "last_event,column",
        [
            ("delivered", "delivered_at"),
            ("opened", "opened_at"),
            ("clicked", "clicked_at"),
            ("bounced", "bounced_at"),
            ("complained", "complained_at"),
            ("unsubscribed", "unsubscribed_at"),
        ],
    )
    def test_last_event_populates_matching_column(
        self, app, db, seed_reconciler, last_event, column
    ):
        from api.jobs.resend_reconciler import reconcile_send_logs
        from api.models import EmailSendLog

        event_ts = "2026-04-19T10:30:00Z"
        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            mock_get.return_value = _mock_resend_response(
                200,
                {"last_event": last_event, "last_event_at": event_ts},
            )
            stats = reconcile_send_logs(
                tenant_id=seed_reconciler["tenant"].id,
                api_key=seed_reconciler["api_key"],
            )

        assert stats["rows_checked"] == 1
        assert stats["rows_updated"] == 1
        assert stats["errors"] == 0

        log = db.session.get(EmailSendLog, seed_reconciler["log"].id)
        assert getattr(log, column) is not None
        # Every other engagement column must remain untouched.
        other_cols = {
            "delivered_at",
            "opened_at",
            "clicked_at",
            "bounced_at",
            "complained_at",
            "unsubscribed_at",
        } - {column}
        for oc in other_cols:
            assert getattr(log, oc) is None, f"{oc} should not have been written"

    def test_unknown_last_event_is_skipped(self, app, db, seed_reconciler):
        """Unknown ``last_event`` values (e.g. ``failed``) are a no-op."""
        from api.jobs.resend_reconciler import reconcile_send_logs
        from api.models import EmailSendLog

        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            mock_get.return_value = _mock_resend_response(200, {"last_event": "failed"})
            stats = reconcile_send_logs(
                tenant_id=seed_reconciler["tenant"].id,
                api_key=seed_reconciler["api_key"],
            )

        assert stats["rows_checked"] == 1
        assert stats["rows_updated"] == 0

        log = db.session.get(EmailSendLog, seed_reconciler["log"].id)
        for col in (
            "delivered_at",
            "opened_at",
            "clicked_at",
            "bounced_at",
            "complained_at",
            "unsubscribed_at",
        ):
            assert getattr(log, col) is None

    def test_missing_last_event_field_is_skipped(self, app, db, seed_reconciler):
        """Response without a ``last_event`` field does nothing."""
        from api.jobs.resend_reconciler import reconcile_send_logs

        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            mock_get.return_value = _mock_resend_response(200, {})
            stats = reconcile_send_logs(
                tenant_id=seed_reconciler["tenant"].id,
                api_key=seed_reconciler["api_key"],
            )

        assert stats["rows_updated"] == 0


# ---------------------------------------------------------------------------
# Earliest-observed invariant (BL-1028 compatibility).
# ---------------------------------------------------------------------------


class TestEarliestObserved:
    """The reconciler never overwrites existing non-NULL timestamps."""

    def test_existing_opened_at_is_preserved(self, app, db, seed_reconciler):
        from api.jobs.resend_reconciler import reconcile_send_logs
        from api.models import EmailSendLog

        # Pre-populate opened_at with an earlier value (simulate webhook fired).
        original_ts = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        log = db.session.get(EmailSendLog, seed_reconciler["log"].id)
        log.opened_at = original_ts
        db.session.commit()

        later_ts = "2026-04-19T10:30:00Z"
        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            mock_get.return_value = _mock_resend_response(
                200,
                {"last_event": "opened", "last_event_at": later_ts},
            )
            stats = reconcile_send_logs(
                tenant_id=seed_reconciler["tenant"].id,
                api_key=seed_reconciler["api_key"],
            )

        # Row was inspected but not mutated.
        assert stats["rows_checked"] == 1
        assert stats["rows_updated"] == 0

        log = db.session.get(EmailSendLog, seed_reconciler["log"].id)
        # SQLite (used in tests) doesn't preserve tzinfo across persistence,
        # so compare naive vs naive.
        assert log.opened_at.replace(tzinfo=None) == original_ts.replace(tzinfo=None)

    def test_row_with_all_timestamps_set_is_not_queried(self, app, db, seed_reconciler):
        """Rows with every engagement column populated are excluded by the query."""
        from api.jobs.resend_reconciler import reconcile_send_logs
        from api.models import EmailSendLog

        ts = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        log = db.session.get(EmailSendLog, seed_reconciler["log"].id)
        log.delivered_at = ts
        log.opened_at = ts
        log.clicked_at = ts
        log.bounced_at = ts
        log.complained_at = ts
        log.unsubscribed_at = ts
        db.session.commit()

        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            stats = reconcile_send_logs(
                tenant_id=seed_reconciler["tenant"].id,
                api_key=seed_reconciler["api_key"],
            )
            assert mock_get.call_count == 0

        assert stats["rows_checked"] == 0


# ---------------------------------------------------------------------------
# HTTP error paths.
# ---------------------------------------------------------------------------


class TestHttpErrorPaths:
    """Transient / terminal HTTP conditions are handled gracefully."""

    def test_404_is_silent(self, app, db, seed_reconciler):
        """Resend 404 — email may have been purged — is not counted as error."""
        from api.jobs.resend_reconciler import reconcile_send_logs

        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            mock_get.return_value = _mock_resend_response(404)
            stats = reconcile_send_logs(
                tenant_id=seed_reconciler["tenant"].id,
                api_key=seed_reconciler["api_key"],
            )

        assert stats["rows_checked"] == 1
        assert stats["rows_updated"] == 0
        assert stats["errors"] == 0

    def test_500_is_logged_and_counted(self, app, db, seed_reconciler, caplog):
        """Resend 500 increments errors but the loop continues."""
        from api.jobs.resend_reconciler import reconcile_send_logs

        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            mock_get.return_value = _mock_resend_response(500)
            with caplog.at_level("WARNING"):
                stats = reconcile_send_logs(
                    tenant_id=seed_reconciler["tenant"].id,
                    api_key=seed_reconciler["api_key"],
                )

        assert stats["rows_checked"] == 1
        assert stats["rows_updated"] == 0
        assert stats["errors"] == 1
        # Some record of the 500 must reach the logs.
        assert any("500" in rec.getMessage() for rec in caplog.records)

    def test_request_exception_is_logged_and_counted(self, app, db, seed_reconciler):
        """A thrown RequestException during GET is caught and counted."""
        import requests
        from api.jobs.resend_reconciler import reconcile_send_logs

        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            mock_get.side_effect = requests.ConnectionError("boom")
            stats = reconcile_send_logs(
                tenant_id=seed_reconciler["tenant"].id,
                api_key=seed_reconciler["api_key"],
            )

        assert stats["rows_checked"] == 1
        assert stats["errors"] == 1


# ---------------------------------------------------------------------------
# Window and scoping.
# ---------------------------------------------------------------------------


class TestWindowAndScoping:
    """Older rows are excluded, and tenant scoping is respected."""

    def test_old_rows_outside_window_are_skipped(self, app, db, seed_reconciler):
        from api.jobs.resend_reconciler import reconcile_send_logs
        from api.models import EmailSendLog

        # Age the row out of a 7-day window.
        log = db.session.get(EmailSendLog, seed_reconciler["log"].id)
        log.created_at = datetime.now(timezone.utc) - timedelta(days=45)
        db.session.commit()

        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            stats = reconcile_send_logs(
                tenant_id=seed_reconciler["tenant"].id,
                api_key=seed_reconciler["api_key"],
                window_days=7,
            )
            assert mock_get.call_count == 0

        assert stats["rows_checked"] == 0

    def test_rows_without_resend_message_id_are_skipped(self, app, db, seed_reconciler):
        """Rows sent via Gmail (no ``resend_message_id``) are excluded."""
        from api.jobs.resend_reconciler import reconcile_send_logs
        from api.models import EmailSendLog

        log = db.session.get(EmailSendLog, seed_reconciler["log"].id)
        log.resend_message_id = None
        db.session.commit()

        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            stats = reconcile_send_logs(
                tenant_id=seed_reconciler["tenant"].id,
                api_key=seed_reconciler["api_key"],
            )
            assert mock_get.call_count == 0

        assert stats["rows_checked"] == 0

    def test_other_tenants_rows_are_not_touched(self, app, db, seed_reconciler):
        """Reconciler scoped to tenant A does not touch tenant B's rows."""
        from api.jobs.resend_reconciler import reconcile_send_logs
        from api.models import (
            Contact,
            EmailSendLog,
            Message,
            Owner,
            Tenant,
        )

        other = Tenant(name="Other", slug="other", is_active=True)
        db.session.add(other)
        db.session.flush()
        other_owner = Owner(tenant_id=other.id, name="Other Owner")
        db.session.add(other_owner)
        db.session.flush()
        other_contact = Contact(
            tenant_id=other.id,
            first_name="Other",
            last_name="Person",
            email_address="other@example.com",
        )
        db.session.add(other_contact)
        db.session.flush()
        other_msg = Message(
            tenant_id=other.id,
            contact_id=other_contact.id,
            owner_id=other_owner.id,
            channel="email",
            sequence_step=1,
            variant="a",
            subject="x",
            body="y",
            status="approved",
        )
        db.session.add(other_msg)
        db.session.flush()
        other_log = EmailSendLog(
            tenant_id=other.id,
            message_id=other_msg.id,
            resend_message_id="other-tenant-id",
            status="sent",
            from_email="o@o.com",
            to_email="other@example.com",
            sent_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.session.add(other_log)
        db.session.commit()

        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            mock_get.return_value = _mock_resend_response(200, {"last_event": "opened"})
            stats = reconcile_send_logs(
                tenant_id=seed_reconciler["tenant"].id,
                api_key=seed_reconciler["api_key"],
            )

        # Only the primary tenant's row should have been checked.
        assert stats["rows_checked"] == 1
        other_log_refetched = db.session.get(EmailSendLog, other_log.id)
        assert other_log_refetched.opened_at is None


# ---------------------------------------------------------------------------
# Timestamp fallback.
# ---------------------------------------------------------------------------


class TestTimestampFallback:
    """When the Resend response omits ``last_event_at``, fall back to
    the row's ``created_at`` so the column is never written as NULL."""

    def test_falls_back_to_row_created_at_when_no_event_ts(
        self, app, db, seed_reconciler
    ):
        from api.jobs.resend_reconciler import reconcile_send_logs
        from api.models import EmailSendLog

        with patch("api.jobs.resend_reconciler.requests.get") as mock_get:
            mock_get.return_value = _mock_resend_response(200, {"last_event": "opened"})
            stats = reconcile_send_logs(
                tenant_id=seed_reconciler["tenant"].id,
                api_key=seed_reconciler["api_key"],
            )

        assert stats["rows_updated"] == 1
        log = db.session.get(EmailSendLog, seed_reconciler["log"].id)
        assert log.opened_at is not None


# ---------------------------------------------------------------------------
# Multi-tenant driver: reconcile_all_tenants.
# ---------------------------------------------------------------------------


class TestReconcileAllTenants:
    """Iterator entry point skips tenants with no resend_api_key configured."""

    def test_only_tenants_with_resend_key_are_processed(self, app, db, seed_reconciler):
        from api.jobs.resend_reconciler import reconcile_all_tenants
        from api.models import Tenant

        # Add a tenant without a resend_api_key — must be skipped.
        no_key = Tenant(name="NoKey", slug="no-key", is_active=True, settings="{}")
        db.session.add(no_key)
        db.session.commit()

        with patch("api.jobs.resend_reconciler.reconcile_send_logs") as mock_recon:
            mock_recon.return_value = {
                "rows_checked": 0,
                "rows_updated": 0,
                "errors": 0,
            }
            summary = reconcile_all_tenants()

        # Only the tenant that has a key should have been visited.
        called_tenants = {
            call.kwargs.get("tenant_id") for call in mock_recon.call_args_list
        }
        assert seed_reconciler["tenant"].id in called_tenants
        assert no_key.id not in called_tenants
        assert summary["tenants_processed"] == 1
        assert summary["tenants_skipped"] >= 1
