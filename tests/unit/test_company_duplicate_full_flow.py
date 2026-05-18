"""End-to-end composed test: PATCH-409 → POST /merge → survival check.

Validates that the two halves of Phase 12 (BL-1203) work together when a
client follows the canonical user flow: try to rename, get a 409 with
matches, then call the merge endpoint on the highlighted match.
"""

import json

from sqlalchemy import text

from api.models import Company, Contact, Owner, UserTenantRole
from tests.conftest import auth_header


def _editor_headers(client):
    h = auth_header(client)
    h["X-Namespace"] = "test-corp"
    return h


def test_full_flow_patch_409_then_merge_succeeds(
    client, db, seed_tenant, seed_super_admin
):
    """Operator tries to rename A → 'Bar', gets 409 (B already named Bar
    in this tenant), follows the modal's 'Merge into this one' action.
    Final state: A is gone, B kept its name, A's contacts re-pointed to B,
    audit row contains merged_from + snapshot."""
    db.session.add(
        UserTenantRole(
            user_id=seed_super_admin.id,
            tenant_id=seed_tenant.id,
            role="admin",
            granted_by=seed_super_admin.id,
        )
    )
    owner = Owner(tenant_id=seed_tenant.id, name="Alice", is_active=True)
    db.session.add(owner)
    db.session.flush()

    a = Company(tenant_id=seed_tenant.id, name="Foo", owner_id=owner.id)
    b = Company(tenant_id=seed_tenant.id, name="Bar", owner_id=owner.id)
    db.session.add_all([a, b])
    db.session.flush()

    c1 = Contact(
        tenant_id=seed_tenant.id, company_id=a.id, first_name="X", last_name="One"
    )
    c2 = Contact(
        tenant_id=seed_tenant.id, company_id=a.id, first_name="Y", last_name="Two"
    )
    db.session.add_all([c1, c2])
    db.session.commit()
    a_id = a.id
    b_id = b.id
    c1_id = c1.id
    c2_id = c2.id

    h = _editor_headers(client)

    # Step 1: PATCH A → name='Bar' (collides with B normalized to 'bar')
    patch_resp = client.patch(
        f"/api/companies/{a_id}",
        json={"name": "Bar"},
        headers=h,
    )
    assert patch_resp.status_code == 409, patch_resp.get_json()
    body = patch_resp.get_json()
    assert body["code"] == "duplicate_company_name"
    matches = body["matches"]
    assert len(matches) == 1
    assert matches[0]["id"] == b_id

    # Step 2: client posts merge against the highlighted match
    merge_resp = client.post(
        f"/api/companies/{a_id}/merge?into={b_id}",
        headers=h,
    )
    assert merge_resp.status_code == 200, merge_resp.get_json()
    surviving = merge_resp.get_json()
    assert surviving["id"] == b_id

    # Step 3: A is gone
    gone = db.session.execute(
        text("SELECT id FROM companies WHERE id = :id"), {"id": a_id}
    ).fetchone()
    assert gone is None

    # Step 4: B kept name 'Bar' and normalized 'bar'
    b_row = db.session.execute(
        text("SELECT name, normalized_name FROM companies WHERE id = :id"),
        {"id": b_id},
    ).fetchone()
    assert b_row[0] == "Bar"
    assert b_row[1] == "bar"

    # Step 5: A's contacts now point at B
    for cid in (c1_id, c2_id):
        row = db.session.execute(
            text("SELECT company_id FROM contacts WHERE id = :id"), {"id": cid}
        ).fetchone()
        assert row[0] == b_id

    # Step 6: audit row written for the merge with deleted_snapshot
    audit = db.session.execute(
        text(
            "SELECT old_value, new_value, metadata FROM contact_field_changes "
            "WHERE entity_id = :s AND field_name = 'merged_from' "
            "ORDER BY changed_at DESC LIMIT 1"
        ),
        {"s": b_id},
    ).fetchone()
    assert audit is not None
    assert audit[0] == a_id
    assert audit[1] == b_id
    meta = audit[2]
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert "deleted_snapshot" in meta
    assert meta["deleted_snapshot"]["name"] == "Foo"
