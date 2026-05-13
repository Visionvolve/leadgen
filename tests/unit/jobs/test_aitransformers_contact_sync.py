"""Unit tests for the AITransformers contact sync (BL-1200).

These tests exercise the sync job at the :func:`process_row` /
:func:`sync_aitransformers_users` level, with the upstream HTTP call
mocked. They run against the SQLite in-memory backend the rest of the
suite uses; the production target is Postgres, which is the only place
``ON CONFLICT DO NOTHING`` is fully exercised.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env_token(monkeypatch):
    """The sync refuses to run without an admin token. Provide one by default."""
    monkeypatch.setenv("AITRANSFORMERS_ADMIN_TOKEN", "test-token")
    yield


@pytest.fixture
def vv_tenant(db):
    """Seed the visionvolve tenant the sync targets by default."""
    from api.models import Tenant

    tenant = Tenant(name="Visionvolve", slug="visionvolve", is_active=True)
    db.session.add(tenant)
    db.session.commit()
    return tenant


@pytest.fixture
def ait_tag(db, vv_tenant):
    """Seed the AITransformers tag inside the visionvolve tenant."""
    from api.models import Tag

    tag = Tag(tenant_id=vv_tenant.id, name="AITransformers", is_active=True)
    db.session.add(tag)
    db.session.commit()
    return tag


def _row(
    iam_id="iam-1",
    email="alice@example.com",
    name="Alice Example",
    role="ml-engineer",
    company="Acme",
    industry="manufacturing",
    company_size="50-200",
    tier="free",
    is_founding_member=False,
    newsletter_subscribed=True,
    maturity_level=3,
):
    return {
        "iam_id": iam_id,
        "email": email,
        "name": name,
        "display_name": None,
        "company": company,
        "industry": industry,
        "role": role,
        "company_size": company_size,
        "maturity_level": maturity_level,
        "tier": tier,
        "is_founding_member": is_founding_member,
        "newsletter_subscribed": newsletter_subscribed,
        "created_at": "2026-04-12T10:30:00Z",
        "updated_at": "2026-05-01T08:00:00Z",
    }


def _new_totals():
    return {
        "created": 0,
        "updated": 0,
        "tagged_new": 0,
        "tagged_existing": 0,
        "skipped": 0,
        "errors": 0,
        "pages_fetched": 0,
        "duration_ms": 0,
        "lock_acquired": True,
    }


def _get_aitransformers_metadata(contact):
    """Pull the aitransformers sub-dict out of ``custom_fields`` (string or dict)."""
    import json

    raw = contact.custom_fields
    if isinstance(raw, str):
        raw = json.loads(raw or "{}")
    if not isinstance(raw, dict):
        return {}
    bucket = raw.get("aitransformers") or {}
    return bucket if isinstance(bucket, dict) else {}


# ---------------------------------------------------------------------------
# process_row — creation path
# ---------------------------------------------------------------------------


class TestProcessRowCreate:
    def test_creates_new_contact(self, app, db, vv_tenant, ait_tag):
        from api.jobs.aitransformers_contact_sync import process_row
        from api.models import Contact, ContactTagAssignment

        totals = _new_totals()
        process_row(vv_tenant.id, ait_tag.id, _row(), totals)

        assert totals["created"] == 1
        assert totals["updated"] == 0
        assert totals["tagged_new"] == 1
        assert totals["tagged_existing"] == 0
        assert totals["skipped"] == 0

        contact = Contact.query.filter_by(tenant_id=vv_tenant.id).first()
        assert contact is not None
        assert contact.email_address == "alice@example.com"
        assert contact.first_name == "Alice"
        assert contact.last_name == "Example"
        assert contact.job_title == "ml-engineer"
        assert contact.import_source == "aitransformers"

        meta = _get_aitransformers_metadata(contact)
        assert meta.get("iam_id") == "iam-1"
        assert meta.get("company") == "Acme"
        assert meta.get("industry") == "manufacturing"
        assert "synced_at" in meta

        # Tag assignment exists exactly once.
        assignments = ContactTagAssignment.query.filter_by(
            contact_id=contact.id, tag_id=ait_tag.id
        ).all()
        assert len(assignments) == 1

    def test_creates_contact_with_only_display_name(self, app, db, vv_tenant, ait_tag):
        """When ``name`` is missing but ``display_name`` is present, use it."""
        from api.jobs.aitransformers_contact_sync import process_row
        from api.models import Contact

        row = _row(name=None)
        row["display_name"] = "Bob"

        totals = _new_totals()
        process_row(vv_tenant.id, ait_tag.id, row, totals)

        contact = Contact.query.filter_by(tenant_id=vv_tenant.id).first()
        assert contact is not None
        assert contact.first_name == "Bob"
        assert contact.last_name == ""

    def test_falls_back_to_email_local_part_when_no_name(
        self, app, db, vv_tenant, ait_tag
    ):
        """``first_name`` is NOT NULL — falls back to local-part of email."""
        from api.jobs.aitransformers_contact_sync import process_row
        from api.models import Contact

        row = _row(name=None)
        row["display_name"] = None

        totals = _new_totals()
        process_row(vv_tenant.id, ait_tag.id, row, totals)

        contact = Contact.query.filter_by(tenant_id=vv_tenant.id).first()
        assert contact is not None
        assert contact.first_name == "alice"


# ---------------------------------------------------------------------------
# process_row — update path
# ---------------------------------------------------------------------------


class TestProcessRowUpdate:
    def test_updates_existing_contact_by_iam_id(self, app, db, vv_tenant, ait_tag):
        """Second sync of the same iam_id reuses the existing contact."""
        from api.jobs.aitransformers_contact_sync import process_row
        from api.models import Contact

        totals = _new_totals()
        process_row(vv_tenant.id, ait_tag.id, _row(), totals)
        # Run a second time — same iam_id, same email.
        process_row(vv_tenant.id, ait_tag.id, _row(), totals)

        contacts = Contact.query.filter_by(tenant_id=vv_tenant.id).all()
        assert len(contacts) == 1

        assert totals["created"] == 1
        assert totals["updated"] == 1
        # First run creates the assignment; second run sees it already there.
        assert totals["tagged_new"] == 1
        assert totals["tagged_existing"] == 1

    def test_adopts_iam_id_when_matched_by_email(self, app, db, vv_tenant, ait_tag):
        """Legacy contact (no iam_id in metadata) matched via email is
        promoted to the AITransformers source on first sync."""
        from api.jobs.aitransformers_contact_sync import process_row
        from api.models import Contact

        legacy = Contact(
            tenant_id=vv_tenant.id,
            first_name="Alice",
            last_name="Example",
            email_address="alice@example.com",
        )
        db.session.add(legacy)
        db.session.commit()

        totals = _new_totals()
        process_row(vv_tenant.id, ait_tag.id, _row(), totals)

        contacts = Contact.query.filter_by(tenant_id=vv_tenant.id).all()
        assert len(contacts) == 1

        merged = contacts[0]
        meta = _get_aitransformers_metadata(merged)
        assert meta.get("iam_id") == "iam-1"
        assert merged.import_source == "aitransformers"
        # Existing fields preserved.
        assert merged.first_name == "Alice"

    def test_fill_if_empty_does_not_overwrite_existing_fields(
        self, app, db, vv_tenant, ait_tag
    ):
        """Manual leadgen edits must survive a resync."""
        from api.jobs.aitransformers_contact_sync import process_row
        from api.models import Contact

        legacy = Contact(
            tenant_id=vv_tenant.id,
            first_name="Custom",
            last_name="Name",
            email_address="alice@example.com",
            job_title="Director (manually set)",
        )
        db.session.add(legacy)
        db.session.commit()

        totals = _new_totals()
        process_row(vv_tenant.id, ait_tag.id, _row(), totals)

        contact = Contact.query.filter_by(tenant_id=vv_tenant.id).first()
        assert contact.first_name == "Custom"
        assert contact.last_name == "Name"
        assert contact.job_title == "Director (manually set)"


# ---------------------------------------------------------------------------
# process_row — tagging idempotency
# ---------------------------------------------------------------------------


class TestTaggingIdempotency:
    def test_no_duplicate_tag_assignment_on_resync(self, app, db, vv_tenant, ait_tag):
        from api.jobs.aitransformers_contact_sync import process_row
        from api.models import ContactTagAssignment

        totals = _new_totals()
        for _ in range(3):
            process_row(vv_tenant.id, ait_tag.id, _row(), totals)

        assignments = ContactTagAssignment.query.filter_by(tag_id=ait_tag.id).all()
        assert len(assignments) == 1
        assert totals["tagged_new"] == 1
        assert totals["tagged_existing"] == 2


# ---------------------------------------------------------------------------
# process_row — skip / error
# ---------------------------------------------------------------------------


class TestProcessRowSkipsAndErrors:
    def test_skips_row_without_email(self, app, db, vv_tenant, ait_tag):
        from api.jobs.aitransformers_contact_sync import process_row
        from api.models import Contact

        totals = _new_totals()
        process_row(vv_tenant.id, ait_tag.id, _row(email=""), totals)

        assert totals["skipped"] == 1
        assert totals["created"] == 0
        assert Contact.query.count() == 0

    def test_skips_row_without_iam_id(self, app, db, vv_tenant, ait_tag):
        from api.jobs.aitransformers_contact_sync import process_row
        from api.models import Contact

        totals = _new_totals()
        process_row(vv_tenant.id, ait_tag.id, _row(iam_id=""), totals)

        assert totals["skipped"] == 1
        assert Contact.query.count() == 0


# ---------------------------------------------------------------------------
# sync_aitransformers_users — full driver, paginated HTTP mocked
# ---------------------------------------------------------------------------


class TestSyncDriver:
    def test_paginates_and_processes_all_rows(self, app, db, vv_tenant, ait_tag):
        from api.jobs.aitransformers_contact_sync import (
            SyncConfig,
            sync_aitransformers_users,
        )
        from api.models import Contact, ContactTagAssignment

        cfg = SyncConfig(
            api_url="https://example.test/api",
            admin_token="t",
            tenant_slug="visionvolve",
            batch_size=2,
            tag_name="AITransformers",
        )

        page1 = {
            "items": [
                _row(iam_id="iam-1", email="alice@example.com"),
                _row(iam_id="iam-2", email="bob@example.com", name="Bob One"),
            ],
            "next_offset": 2,
        }
        page2 = {
            "items": [
                _row(iam_id="iam-3", email="carol@example.com", name="Carol Two"),
            ],
            "next_offset": None,
        }

        with patch(
            "api.jobs.aitransformers_contact_sync._http_get_with_retry",
            side_effect=[page1, page2],
        ):
            totals = sync_aitransformers_users(cfg)

        assert totals["created"] == 3
        assert totals["tagged_new"] == 3
        assert totals["skipped"] == 0
        assert totals["errors"] == 0
        assert totals["pages_fetched"] == 2
        assert Contact.query.count() == 3
        assert ContactTagAssignment.query.filter_by(tag_id=ait_tag.id).count() == 3

    def test_per_row_exception_does_not_abort_batch(
        self, app, db, vv_tenant, ait_tag, caplog
    ):
        from api.jobs.aitransformers_contact_sync import (
            SyncConfig,
            sync_aitransformers_users,
        )
        from api.models import Contact

        cfg = SyncConfig(
            api_url="https://example.test/api",
            admin_token="t",
            tenant_slug="visionvolve",
            batch_size=10,
            tag_name="AITransformers",
        )
        page = {
            "items": [
                _row(iam_id="iam-1", email="ok@example.com"),
                _row(iam_id="iam-2", email="boom@example.com"),
                _row(iam_id="iam-3", email="also-ok@example.com"),
            ],
            "next_offset": None,
        }

        real_process_row = __import__(
            "api.jobs.aitransformers_contact_sync", fromlist=["process_row"]
        ).process_row

        def fake_process_row(tenant_id, tag_id, row, totals):
            if row.get("iam_id") == "iam-2":
                raise RuntimeError("synthetic blow-up")
            return real_process_row(tenant_id, tag_id, row, totals)

        with patch(
            "api.jobs.aitransformers_contact_sync._http_get_with_retry",
            return_value=page,
        ):
            with patch(
                "api.jobs.aitransformers_contact_sync.process_row",
                side_effect=fake_process_row,
            ):
                with caplog.at_level("ERROR"):
                    totals = sync_aitransformers_users(cfg)

        assert totals["errors"] == 1
        assert totals["created"] == 2  # iam-1 + iam-3 succeeded
        assert Contact.query.count() == 2
        assert any("synthetic blow-up" in rec.getMessage() for rec in caplog.records)

    def test_missing_tenant_raises(self, app, db):
        from api.jobs.aitransformers_contact_sync import (
            SyncConfig,
            sync_aitransformers_users,
        )

        cfg = SyncConfig(
            api_url="https://example.test/api",
            admin_token="t",
            tenant_slug="does-not-exist",
            batch_size=10,
            tag_name="AITransformers",
        )

        with pytest.raises(RuntimeError, match="tenant slug 'does-not-exist'"):
            sync_aitransformers_users(cfg)

    def test_creates_tag_when_missing(self, app, db, vv_tenant):
        """If the AITransformers tag doesn't exist yet, it's auto-created."""
        from api.jobs.aitransformers_contact_sync import (
            SyncConfig,
            sync_aitransformers_users,
        )
        from api.models import Tag

        # No ait_tag fixture — verify the job creates it.
        assert (
            Tag.query.filter_by(tenant_id=vv_tenant.id, name="AITransformers").count()
            == 0
        )

        cfg = SyncConfig(
            api_url="https://example.test/api",
            admin_token="t",
            tenant_slug="visionvolve",
            batch_size=10,
            tag_name="AITransformers",
        )
        page = {"items": [_row()], "next_offset": None}

        with patch(
            "api.jobs.aitransformers_contact_sync._http_get_with_retry",
            return_value=page,
        ):
            totals = sync_aitransformers_users(cfg)

        assert totals["created"] == 1
        assert (
            Tag.query.filter_by(tenant_id=vv_tenant.id, name="AITransformers").count()
            == 1
        )


# ---------------------------------------------------------------------------
# HTTP retry
# ---------------------------------------------------------------------------


class TestHttpRetry:
    def test_retries_on_5xx_then_succeeds(self, app, db, vv_tenant, ait_tag):
        """A transient 500 is retried; subsequent 200 returns the page."""
        import requests
        from unittest.mock import MagicMock

        from api.jobs.aitransformers_contact_sync import _http_get_with_retry

        bad = MagicMock(spec=requests.Response)
        bad.status_code = 500
        bad.text = "boom"

        good = MagicMock(spec=requests.Response)
        good.status_code = 200
        good.json.return_value = {"items": [], "next_offset": None}

        with patch(
            "api.jobs.aitransformers_contact_sync.requests.get",
            side_effect=[bad, good],
        ):
            with patch("api.jobs.aitransformers_contact_sync.time.sleep"):
                result = _http_get_with_retry(
                    "https://example.test/x", params={}, headers={}
                )

        assert result == {"items": [], "next_offset": None}

    def test_4xx_raises_immediately(self, app, db):
        import requests
        from unittest.mock import MagicMock

        from api.jobs.aitransformers_contact_sync import _http_get_with_retry

        resp = MagicMock(spec=requests.Response)
        resp.status_code = 401
        resp.text = "unauthorized"

        with patch(
            "api.jobs.aitransformers_contact_sync.requests.get",
            return_value=resp,
        ):
            with pytest.raises(RuntimeError, match="401"):
                _http_get_with_retry("https://example.test/x", params={}, headers={})

    def test_5xx_exhausts_retries_then_raises(self, app, db):
        import requests
        from unittest.mock import MagicMock

        from api.jobs.aitransformers_contact_sync import _http_get_with_retry

        resp = MagicMock(spec=requests.Response)
        resp.status_code = 503
        resp.text = "unavailable"

        with patch(
            "api.jobs.aitransformers_contact_sync.requests.get",
            return_value=resp,
        ):
            with patch("api.jobs.aitransformers_contact_sync.time.sleep"):
                with pytest.raises(RuntimeError, match="503"):
                    _http_get_with_retry(
                        "https://example.test/x", params={}, headers={}
                    )


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_requires_admin_token(self, monkeypatch):
        from api.jobs.aitransformers_contact_sync import load_config

        monkeypatch.delenv("AITRANSFORMERS_ADMIN_TOKEN", raising=False)

        with pytest.raises(RuntimeError, match="AITRANSFORMERS_ADMIN_TOKEN"):
            load_config()

    def test_applies_defaults(self, monkeypatch):
        from api.jobs.aitransformers_contact_sync import (
            DEFAULT_API_URL,
            DEFAULT_BATCH_SIZE,
            DEFAULT_TAG_NAME,
            DEFAULT_TENANT_SLUG,
            load_config,
        )

        monkeypatch.setenv("AITRANSFORMERS_ADMIN_TOKEN", "tok")
        monkeypatch.delenv("AITRANSFORMERS_API_URL", raising=False)
        monkeypatch.delenv("LEADGEN_AITRANSFORMERS_TENANT_SLUG", raising=False)
        monkeypatch.delenv("LEADGEN_AITRANSFORMERS_BATCH_SIZE", raising=False)
        monkeypatch.delenv("LEADGEN_AITRANSFORMERS_TAG_NAME", raising=False)

        cfg = load_config()
        assert cfg.api_url == DEFAULT_API_URL.rstrip("/")
        assert cfg.tenant_slug == DEFAULT_TENANT_SLUG
        assert cfg.batch_size == DEFAULT_BATCH_SIZE
        assert cfg.tag_name == DEFAULT_TAG_NAME
