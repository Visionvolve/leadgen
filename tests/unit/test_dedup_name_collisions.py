"""Unit tests for find_name_collisions (BL-1203 / Phase 12)."""

import pytest

from api.models import Company, Contact, Owner, Tenant
from api.services.dedup import find_name_collisions
from api.services.name_normalize import normalize_company_name


@pytest.fixture
def two_tenants(db):
    """Two tenants with predictable IDs, returned as a dict."""
    t1 = Tenant(name="Tenant One", slug="tenant-one", is_active=True)
    t2 = Tenant(name="Tenant Two", slug="tenant-two", is_active=True)
    db.session.add_all([t1, t2])
    db.session.commit()
    return {"t1": t1, "t2": t2}


@pytest.fixture
def collision_fixture(db, two_tenants):
    """Create the dedup-test data:
    T1: Foo, Foo s.r.o. (both normalize to 'foo'); Bar
    T2: Foo (normalizes to 'foo' — must NOT appear in T1 queries).
    """
    t1, t2 = two_tenants["t1"], two_tenants["t2"]
    o1 = Owner(tenant_id=t1.id, name="Owner T1", is_active=True)
    db.session.add(o1)
    db.session.flush()

    foo1 = Company(tenant_id=t1.id, name="Foo", normalized_name="foo")
    foo2 = Company(
        tenant_id=t1.id, name="Foo s.r.o.", normalized_name="foo", owner_id=o1.id
    )
    bar = Company(tenant_id=t1.id, name="Bar", normalized_name="bar")
    t2_foo = Company(tenant_id=t2.id, name="Foo", normalized_name="foo")
    db.session.add_all([foo1, foo2, bar, t2_foo])
    db.session.flush()

    # Two contacts on foo2 so contact_count > 0 in at least one match
    c1 = Contact(tenant_id=t1.id, company_id=foo2.id, first_name="A", last_name="One")
    c2 = Contact(tenant_id=t1.id, company_id=foo2.id, first_name="B", last_name="Two")
    db.session.add_all([c1, c2])
    db.session.commit()
    return {
        "t1": t1,
        "t2": t2,
        "foo1": foo1,
        "foo2": foo2,
        "bar": bar,
        "t2_foo": t2_foo,
    }


def test_returns_both_t1_foo_rows_not_t2(collision_fixture):
    t1 = collision_fixture["t1"]
    rows = find_name_collisions(t1.id, "foo")
    ids = {r["id"] for r in rows}
    assert ids == {collision_fixture["foo1"].id, collision_fixture["foo2"].id}
    assert collision_fixture["t2_foo"].id not in ids


def test_exclude_id_filters_self(collision_fixture):
    t1 = collision_fixture["t1"]
    excluded = collision_fixture["foo1"].id
    rows = find_name_collisions(t1.id, "foo", exclude_id=excluded)
    assert len(rows) == 1
    assert rows[0]["id"] == collision_fixture["foo2"].id


def test_empty_normalized_short_circuits(collision_fixture):
    t1 = collision_fixture["t1"]
    assert find_name_collisions(t1.id, "") == []
    # also None-like falsy
    assert find_name_collisions(t1.id, None) == []  # type: ignore[arg-type]


def test_bar_lookup(collision_fixture):
    t1 = collision_fixture["t1"]
    rows = find_name_collisions(t1.id, "bar")
    assert len(rows) == 1
    assert rows[0]["id"] == collision_fixture["bar"].id


def test_tenant_isolation_t2(collision_fixture):
    t2 = collision_fixture["t2"]
    rows = find_name_collisions(t2.id, "foo")
    assert len(rows) == 1
    assert rows[0]["id"] == collision_fixture["t2_foo"].id


def test_summary_shape(collision_fixture):
    t1 = collision_fixture["t1"]
    rows = find_name_collisions(t1.id, "foo")
    for r in rows:
        assert set(r.keys()) == {
            "id",
            "name",
            "domain",
            "status",
            "owner",
            "contact_count",
            "last_activity_at",
        }


def test_owner_dict_when_set_or_none(collision_fixture):
    t1 = collision_fixture["t1"]
    rows = find_name_collisions(t1.id, "foo")
    by_id = {r["id"]: r for r in rows}
    foo1_id = collision_fixture["foo1"].id
    foo2_id = collision_fixture["foo2"].id
    # foo1 has no owner
    assert by_id[foo1_id]["owner"] is None
    # foo2 has owner
    assert by_id[foo2_id]["owner"] is not None
    assert by_id[foo2_id]["owner"]["name"] == "Owner T1"


def test_contact_count_reflects_join(collision_fixture):
    t1 = collision_fixture["t1"]
    rows = find_name_collisions(t1.id, "foo")
    by_id = {r["id"]: r for r in rows}
    foo1_id = collision_fixture["foo1"].id
    foo2_id = collision_fixture["foo2"].id
    assert by_id[foo1_id]["contact_count"] == 0
    assert by_id[foo2_id]["contact_count"] == 2


def test_normalize_then_collision_roundtrip(collision_fixture):
    """The PATCH-handler will compute normalize_company_name first; ensure
    that combined flow returns the same set."""
    t1 = collision_fixture["t1"]
    norm = normalize_company_name("Foo S.R.O.")
    assert norm == "foo"
    rows = find_name_collisions(t1.id, norm)
    assert len(rows) == 2
