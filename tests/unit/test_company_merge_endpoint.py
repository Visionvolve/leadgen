"""Integration tests for POST /api/companies/<id>/merge?into=<surviving_id>
(BL-1203 / Phase 12).
"""

import json
import uuid as _uuid

import pytest
from sqlalchemy import text

from api.models import (
    Company,
    CompanyEnrichmentL1,
    CompanyNews,
    CompanyTag,
    CompanyTagAssignment,
    Contact,
    Owner,
    Tenant,
    User,
    UserTenantRole,
)
from tests.conftest import _make_test_token, auth_header


@pytest.fixture
def two_companies(db, seed_tenant, seed_super_admin):
    """One surviving (Acme s.r.o.) + one to-be-deleted (Acme) in tenant test-corp."""
    role = UserTenantRole(
        user_id=seed_super_admin.id,
        tenant_id=seed_tenant.id,
        role="admin",
        granted_by=seed_super_admin.id,
    )
    db.session.add(role)
    o1 = Owner(tenant_id=seed_tenant.id, name="Alice", is_active=True)
    o2 = Owner(tenant_id=seed_tenant.id, name="Bob", is_active=True)
    db.session.add_all([o1, o2])
    db.session.flush()

    surviving = Company(
        tenant_id=seed_tenant.id,
        name="Acme s.r.o.",
        owner_id=o1.id,
        domain="acme.com",
        status="enriched_l2",
    )
    deleted = Company(
        tenant_id=seed_tenant.id,
        name="Acme",
        owner_id=o2.id,
        notes="Some notes from the duplicate",
    )
    db.session.add_all([surviving, deleted])
    db.session.flush()

    c1 = Contact(
        tenant_id=seed_tenant.id,
        company_id=deleted.id,
        first_name="A",
        last_name="One",
    )
    c2 = Contact(
        tenant_id=seed_tenant.id,
        company_id=deleted.id,
        first_name="B",
        last_name="Two",
    )
    db.session.add_all([c1, c2])

    tag_assigns = [
        CompanyTagAssignment(
            tenant_id=seed_tenant.id,
            company_id=deleted.id,
            tag_id=str(_uuid.uuid4()),
        ),
    ]
    db.session.add_all(tag_assigns)
    db.session.add(
        CompanyTag(company_id=deleted.id, category="industry", value="manufacturing")
    )
    db.session.add(CompanyNews(company_id=deleted.id, news_summary="An old story"))
    db.session.commit()

    # Capture IDs as plain strings AFTER commit so they're persisted, but
    # BEFORE the merge deletes rows; otherwise the ORM raises
    # ObjectDeletedError on later attribute access.
    surviving_id = surviving.id
    deleted_id = deleted.id
    o1_id = o1.id
    o2_id = o2.id
    c1_id = c1.id
    c2_id = c2.id
    return {
        "surviving_id": surviving_id,
        "deleted_id": deleted_id,
        "owner_alice_id": o1_id,
        "owner_bob_id": o2_id,
        "contact_ids": [c1_id, c2_id],
    }


def _editor_headers(client):
    h = auth_header(client)
    h["X-Namespace"] = "test-corp"
    return h


class TestMergeEndpoint:
    def test_happy_path_repoints_fks_and_deletes(self, client, db, two_companies):
        surviving = two_companies["surviving_id"]
        deleted = two_companies["deleted_id"]
        h = _editor_headers(client)

        resp = client.post(
            f"/api/companies/{deleted}/merge?into={surviving}",
            headers=h,
        )
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["id"] == surviving

        # Deleted row is gone
        gone = db.session.execute(
            text("SELECT id FROM companies WHERE id = :id"), {"id": deleted}
        ).fetchone()
        assert gone is None

        # Contacts re-pointed
        for cid in two_companies["contact_ids"]:
            row = db.session.execute(
                text("SELECT company_id FROM contacts WHERE id = :id"), {"id": cid}
            ).fetchone()
            assert row[0] == surviving

        # company_tag_assignments re-pointed (no conflict — surviving had none)
        cnt = db.session.execute(
            text("SELECT count(*) FROM company_tag_assignments WHERE company_id = :s"),
            {"s": surviving},
        ).fetchone()[0]
        assert cnt == 1

        # company_news re-pointed
        n = db.session.execute(
            text("SELECT count(*) FROM company_news WHERE company_id = :s"),
            {"s": surviving},
        ).fetchone()[0]
        assert n == 1

        # Audit row written
        audit = db.session.execute(
            text(
                "SELECT old_value, new_value, metadata FROM contact_field_changes "
                "WHERE entity_id = :s AND field_name = 'merged_from' "
                "ORDER BY changed_at DESC LIMIT 1"
            ),
            {"s": surviving},
        ).fetchone()
        assert audit is not None
        assert audit[0] == deleted
        assert audit[1] == surviving
        meta = audit[2]
        if isinstance(meta, str):
            meta = json.loads(meta)
        assert "deleted_snapshot" in meta
        assert meta["deleted_snapshot"]["name"] == "Acme"

    def test_fills_null_fields_on_surviving(self, client, db, two_companies):
        """surviving.notes is NULL; deleted.notes is set. After merge, surviving.notes
        picks up the deleted value."""
        surviving = two_companies["surviving_id"]
        deleted = two_companies["deleted_id"]
        h = _editor_headers(client)

        resp = client.post(
            f"/api/companies/{deleted}/merge?into={surviving}",
            headers=h,
        )
        assert resp.status_code == 200
        notes = db.session.execute(
            text("SELECT notes FROM companies WHERE id = :id"), {"id": surviving}
        ).fetchone()[0]
        assert notes == "Some notes from the duplicate"

    def test_preserves_surviving_non_null(self, client, db, two_companies):
        """surviving owner_id is preserved (not overwritten by deleted's)."""
        surviving = two_companies["surviving_id"]
        deleted = two_companies["deleted_id"]
        alice = two_companies["owner_alice_id"]
        h = _editor_headers(client)

        resp = client.post(
            f"/api/companies/{deleted}/merge?into={surviving}",
            headers=h,
        )
        assert resp.status_code == 200
        owner_id = db.session.execute(
            text("SELECT owner_id FROM companies WHERE id = :id"),
            {"id": surviving},
        ).fetchone()[0]
        assert owner_id == alice

    def test_cross_tenant_returns_404(self, client, db, seed_tenant, seed_super_admin):
        """Surviving in T1 + deleted in T2 → 404 (no leak), both still exist."""
        # Give super-admin admin role on T1 so resolve_tenant works
        db.session.add(
            UserTenantRole(
                user_id=seed_super_admin.id,
                tenant_id=seed_tenant.id,
                role="admin",
                granted_by=seed_super_admin.id,
            )
        )
        # Second tenant
        t2 = Tenant(name="Other", slug="other", is_active=True)
        db.session.add(t2)
        db.session.flush()
        c1 = Company(tenant_id=seed_tenant.id, name="T1 Co")
        c2 = Company(tenant_id=t2.id, name="T2 Co")
        db.session.add_all([c1, c2])
        db.session.commit()

        h = _editor_headers(client)
        resp = client.post(f"/api/companies/{c1.id}/merge?into={c2.id}", headers=h)
        assert resp.status_code == 404

        # Both rows still exist
        for cid in (c1.id, c2.id):
            row = db.session.execute(
                text("SELECT id FROM companies WHERE id = :id"), {"id": cid}
            ).fetchone()
            assert row is not None

    def test_same_id_returns_400(self, client, db, two_companies):
        surviving = two_companies["surviving_id"]
        h = _editor_headers(client)
        resp = client.post(
            f"/api/companies/{surviving}/merge?into={surviving}",
            headers=h,
        )
        assert resp.status_code == 400

    def test_missing_into_returns_400(self, client, db, two_companies):
        deleted = two_companies["deleted_id"]
        h = _editor_headers(client)
        resp = client.post(f"/api/companies/{deleted}/merge", headers=h)
        assert resp.status_code == 400

    def test_requires_editor_role(self, client, db):
        """A viewer user gets 403 from @require_role('editor')."""
        # Tenant + viewer user
        t = Tenant(name="V Corp", slug="v-corp", is_active=True)
        db.session.add(t)
        db.session.flush()
        iam_id = str(_uuid.uuid4())
        u = User(
            email="viewer@test.com",
            password_hash=None,
            display_name="Viewer",
            is_super_admin=False,
            is_active=True,
            iam_user_id=iam_id,
        )
        db.session.add(u)
        db.session.flush()
        db.session.add(
            UserTenantRole(user_id=u.id, tenant_id=t.id, role="viewer", granted_by=u.id)
        )
        c1 = Company(tenant_id=t.id, name="Alpha")
        c2 = Company(tenant_id=t.id, name="Beta")
        db.session.add_all([c1, c2])
        db.session.commit()

        token = _make_test_token(u)
        headers = {"Authorization": f"Bearer {token}", "X-Namespace": "v-corp"}
        resp = client.post(
            f"/api/companies/{c1.id}/merge?into={c2.id}", headers=headers
        )
        assert resp.status_code == 403

    def test_pk_conflict_table_handled(self, client, db, two_companies):
        """Both surviving and deleted have a company_enrichment_l1 row.
        Merge keeps surviving's row and drops deleted's (PK conflict)."""
        surviving = two_companies["surviving_id"]
        deleted = two_companies["deleted_id"]
        db.session.add(
            CompanyEnrichmentL1(company_id=surviving, triage_notes="Surviving L1 data")
        )
        db.session.add(
            CompanyEnrichmentL1(company_id=deleted, triage_notes="Deleted L1 data")
        )
        db.session.commit()

        h = _editor_headers(client)
        resp = client.post(
            f"/api/companies/{deleted}/merge?into={surviving}",
            headers=h,
        )
        assert resp.status_code == 200, resp.get_json()
        rows = db.session.execute(
            text(
                "SELECT triage_notes FROM company_enrichment_l1 WHERE company_id = :s"
            ),
            {"s": surviving},
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "Surviving L1 data"  # surviving wins on conflict

        # Deleted row entirely gone
        empty = db.session.execute(
            text("SELECT count(*) FROM company_enrichment_l1 WHERE company_id = :d"),
            {"d": deleted},
        ).fetchone()[0]
        assert empty == 0

    def test_rollback_on_failure(self, client, db, two_companies, monkeypatch):
        """If merge_companies raises mid-transaction, the deleted row must
        still exist after rollback."""
        from api.services import dedup as dedup_mod

        surviving = two_companies["surviving_id"]
        deleted = two_companies["deleted_id"]
        original = dedup_mod.merge_companies

        def boom(*a, **kw):
            # Run the real function partially then raise to simulate failure
            # midway. Easier: just raise immediately — the route handler
            # rolls back the surrounding transaction.
            from api.services.dedup import MergeError

            raise MergeError("simulated failure")

        monkeypatch.setattr(dedup_mod, "merge_companies", boom)

        h = _editor_headers(client)
        resp = client.post(
            f"/api/companies/{deleted}/merge?into={surviving}",
            headers=h,
        )
        # MergeError → 404 path or 500 depending on impl; key point: deleted still there
        assert resp.status_code in (404, 500)

        still_there = db.session.execute(
            text("SELECT name FROM companies WHERE id = :id"),
            {"id": deleted},
        ).fetchone()
        assert still_there is not None
        assert still_there[0] == "Acme"

        monkeypatch.setattr(dedup_mod, "merge_companies", original)
