"""Integration tests for the PATCH /api/companies/<id> duplicate-name gate
(BL-1203 / Phase 12).
"""

import json

from sqlalchemy import text

from tests.conftest import auth_header


def _ns_header(client):
    h = auth_header(client)
    h["X-Namespace"] = "test-corp"
    return h


def _company_id_by_name(seed_companies_contacts, name):
    for c in seed_companies_contacts["companies"]:
        if c.name == name:
            return c.id
    raise AssertionError(f"Seed company {name!r} not found")


class TestPatchDuplicateGate:
    def test_clean_rename_returns_200(self, client, db, seed_companies_contacts):
        h = _ns_header(client)
        cid = _company_id_by_name(seed_companies_contacts, "Acme Corp")
        resp = client.patch(
            f"/api/companies/{cid}",
            json={"name": "Acme Renamed Ltd"},
            headers=h,
        )
        assert resp.status_code == 200, resp.get_json()

        row = db.session.execute(
            text("SELECT name, normalized_name FROM companies WHERE id = :id"),
            {"id": cid},
        ).fetchone()
        assert row[0] == "Acme Renamed Ltd"
        # 'Ltd' is a trailing legal suffix → stripped during normalization
        assert row[1] == "acme renamed"

    def test_empty_after_normalize_returns_400(
        self, client, db, seed_companies_contacts
    ):
        h = _ns_header(client)
        cid = _company_id_by_name(seed_companies_contacts, "Acme Corp")
        original = db.session.execute(
            text("SELECT name FROM companies WHERE id = :id"), {"id": cid}
        ).fetchone()[0]

        resp = client.patch(
            f"/api/companies/{cid}",
            json={"name": "   s.r.o.   "},
            headers=h,
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body.get("code") in {"empty_name_after_normalize", "empty_name"}

        # name unchanged
        current = db.session.execute(
            text("SELECT name FROM companies WHERE id = :id"), {"id": cid}
        ).fetchone()[0]
        assert current == original

    def test_collision_returns_409_with_matches(
        self, client, db, seed_companies_contacts
    ):
        """Beta Inc collides with new name 'Acme s.r.o.' if Acme already
        normalizes to 'acme'. Set up by ensuring Acme has normalized_name='acme'.
        """
        # Acme Corp normalizes to 'acme' (the 'corp' suffix is stripped by name_normalize).
        # Sanity check: ensure seed Acme has normalized_name='acme' (the SQLAlchemy
        # listener already populates it on insert via the fixture).
        acme_id = _company_id_by_name(seed_companies_contacts, "Acme Corp")
        acme_norm = db.session.execute(
            text("SELECT normalized_name FROM companies WHERE id = :id"),
            {"id": acme_id},
        ).fetchone()[0]
        assert acme_norm == "acme", (
            f"Seed Acme normalized to {acme_norm!r}; "
            "test expects 'acme' (corp stripped)."
        )

        beta_id = _company_id_by_name(seed_companies_contacts, "Beta Inc")

        h = _ns_header(client)
        resp = client.patch(
            f"/api/companies/{beta_id}",
            json={"name": "Acme s.r.o."},
            headers=h,
        )
        assert resp.status_code == 409, resp.get_json()
        body = resp.get_json()
        assert body["code"] == "duplicate_company_name"
        assert isinstance(body["matches"], list)
        assert len(body["matches"]) == 1
        m = body["matches"][0]
        assert m["id"] == acme_id
        for k in (
            "id",
            "name",
            "domain",
            "status",
            "owner",
            "contact_count",
            "last_activity_at",
        ):
            assert k in m

        # Beta still has its original name + normalized_name
        beta_row = db.session.execute(
            text("SELECT name, normalized_name FROM companies WHERE id = :id"),
            {"id": beta_id},
        ).fetchone()
        assert beta_row[0] == "Beta Inc"
        # 'beta' (the 'Inc' is stripped as trailing suffix)
        assert beta_row[1] == "beta"

    def test_keep_both_query_proceeds_and_audits(
        self, client, db, seed_companies_contacts
    ):
        beta_id = _company_id_by_name(seed_companies_contacts, "Beta Inc")
        h = _ns_header(client)
        resp = client.patch(
            f"/api/companies/{beta_id}?confirm_duplicate=keep_both",
            json={"name": "Acme s.r.o."},
            headers=h,
        )
        assert resp.status_code == 200, resp.get_json()
        row = db.session.execute(
            text("SELECT name, normalized_name FROM companies WHERE id = :id"),
            {"id": beta_id},
        ).fetchone()
        assert row[0] == "Acme s.r.o."
        assert row[1] == "acme"

        audit = db.session.execute(
            text(
                "SELECT new_value, metadata FROM contact_field_changes "
                "WHERE entity_id = :id AND field_name = 'name' "
                "ORDER BY changed_at DESC LIMIT 1"
            ),
            {"id": beta_id},
        ).fetchone()
        assert audit is not None
        assert audit[0] == "Acme s.r.o."
        meta = audit[1]
        if isinstance(meta, str):
            meta = json.loads(meta)
        assert meta.get("note") == "duplicate_kept_intentionally"

    def test_cross_tenant_collision_does_not_block(self, client, db):
        """A T2 company with normalized_name='foo' must NOT block a T1
        rename to 'Foo'."""
        from api.models import Company, Tenant, User, UserTenantRole

        # Tenants
        t1 = Tenant(name="T One", slug="t-one", is_active=True)
        t2 = Tenant(name="T Two", slug="t-two", is_active=True)
        db.session.add_all([t1, t2])
        db.session.flush()

        # Admin user with editor role on T1
        import uuid as _uuid

        iam_id = str(_uuid.uuid4())
        u = User(
            email="x_user@test.com",
            password_hash=None,
            display_name="X",
            is_super_admin=False,
            is_active=True,
            iam_user_id=iam_id,
        )
        db.session.add(u)
        db.session.flush()
        db.session.add(
            UserTenantRole(
                user_id=u.id, tenant_id=t1.id, role="editor", granted_by=u.id
            )
        )

        # T1 has Bar; T2 has Foo (normalized 'foo')
        bar = Company(tenant_id=t1.id, name="Bar")
        t2_foo = Company(tenant_id=t2.id, name="Foo")
        db.session.add_all([bar, t2_foo])
        db.session.commit()

        # Build auth header for T1 user
        from tests.conftest import _make_test_token

        token = _make_test_token(u)
        headers = {"Authorization": f"Bearer {token}", "X-Namespace": "t-one"}

        resp = client.patch(
            f"/api/companies/{bar.id}",
            json={"name": "Foo"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.get_json()
        row = db.session.execute(
            text("SELECT name, normalized_name FROM companies WHERE id = :id"),
            {"id": bar.id},
        ).fetchone()
        assert row[0] == "Foo"
        assert row[1] == "foo"

        # T2 row untouched
        t2_row = db.session.execute(
            text("SELECT name FROM companies WHERE id = :id"),
            {"id": t2_foo.id},
        ).fetchone()
        assert t2_row[0] == "Foo"

    def test_mass_assignment_guard_still_holds(
        self, client, db, seed_companies_contacts
    ):
        h = _ns_header(client)
        cid = _company_id_by_name(seed_companies_contacts, "Gamma LLC")
        original_tenant = db.session.execute(
            text("SELECT tenant_id FROM companies WHERE id = :id"), {"id": cid}
        ).fetchone()[0]

        resp = client.patch(
            f"/api/companies/{cid}",
            json={
                "name": "Gamma Renamed Plc",
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "id": "11111111-1111-1111-1111-111111111111",
            },
            headers=h,
        )
        # 200 because name is valid; tenant_id / id must NOT be persisted
        assert resp.status_code == 200, resp.get_json()
        row = db.session.execute(
            text("SELECT id, tenant_id, name FROM companies WHERE id = :id"),
            {"id": cid},
        ).fetchone()
        assert row[0] == cid
        assert row[1] == original_tenant
        assert row[2] == "Gamma Renamed Plc"
