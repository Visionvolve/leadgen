"""Pagination stability tests for the contacts and companies list endpoints.

Regression coverage for BL-1116: when many rows tie on the primary sort column
(e.g. NULL `department` or NULL `seniority_level`), naive `ORDER BY <col>` is
not deterministic across pages -- the same physical row can show up on page 1
and page 2, which manifests in the UI as duplicate rows after scrolling. The
fix appends a unique tiebreaker (`ct.id ASC` / `c.id ASC`) to every paginated
ORDER BY so pages stay disjoint.
"""

from tests.conftest import auth_header


def _seed_many_contacts(db, tenant_id, owner_id, company_id, n=100, tied_count=50):
    """Seed `n` contacts, `tied_count` of which share NULL nullable fields.

    Returns the list of contact ids in insertion order.
    """
    from api.models import Contact

    ids = []
    for i in range(n):
        # First `tied_count` contacts have NULL department + seniority_level so
        # they tie on those sort columns. Remaining have concrete values.
        is_tied = i < tied_count
        c = Contact(
            tenant_id=tenant_id,
            company_id=company_id,
            owner_id=owner_id,
            first_name=f"First{i:03d}",
            last_name=f"Last{i:03d}",
            job_title="Engineer",
            email_address=f"contact{i:03d}@example.com",
            seniority_level=None if is_tied else "manager",
            department=None if is_tied else "engineering",
            contact_score=50,
        )
        db.session.add(c)
        ids.append(c)
    db.session.commit()
    return [c.id for c in ids]


def _seed_many_companies(db, tenant_id, owner_id, n=100, tied_count=50):
    """Seed `n` companies, `tied_count` of which share NULL tier."""
    from api.models import Company

    rows = []
    for i in range(n):
        is_tied = i < tied_count
        c = Company(
            tenant_id=tenant_id,
            name=f"Co {i:03d}",
            domain=f"co{i:03d}.example.com",
            status="new",
            tier=None if is_tied else "tier_3_silver",
            owner_id=owner_id,
            industry=None if is_tied else "software_saas",
            hq_country=None if is_tied else "Germany",
            triage_score=None if is_tied else 7.0,
        )
        db.session.add(c)
        rows.append(c)
    db.session.commit()
    return [c.id for c in rows]


def _fetch_all_ids(
    client, headers, endpoint, page_size, sort, sort_dir="asc", key="contacts"
):
    """Walk every page of an endpoint and collect ids in order."""
    ids: list[str] = []
    page = 1
    while True:
        resp = client.get(
            f"{endpoint}?page={page}&page_size={page_size}&sort={sort}&sort_dir={sort_dir}",
            headers=headers,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        rows = data.get(key) or []
        for r in rows:
            ids.append(r["id"])
        if page >= data["pages"]:
            break
        page += 1
    return ids


class TestContactsPaginationStable:
    """Across all pages, no contact id should appear twice."""

    def test_no_overlap_sorted_by_nullable_department(
        self, client, db, seed_tenant, seed_super_admin
    ):
        from api.models import Owner, Company, UserTenantRole

        # Give admin a role on the tenant
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
        company = Company(
            tenant_id=seed_tenant.id, name="Acme", domain="acme.com", status="new"
        )
        db.session.add(company)
        db.session.flush()

        _seed_many_contacts(
            db, seed_tenant.id, owner.id, company.id, n=100, tied_count=50
        )

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        ids = _fetch_all_ids(
            client,
            headers,
            "/api/contacts",
            page_size=25,
            sort="department",
            key="contacts",
        )

        # Every page collected: should have 100 total, no duplicates.
        assert len(ids) == 100, f"Expected 100 ids, got {len(ids)}"
        assert len(set(ids)) == 100, (
            f"Duplicate contact ids across pages: {len(ids) - len(set(ids))} duplicates"
        )

    def test_no_overlap_sorted_by_nullable_seniority(
        self, client, db, seed_tenant, seed_super_admin
    ):
        from api.models import Owner, Company, UserTenantRole

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
        company = Company(
            tenant_id=seed_tenant.id, name="Acme", domain="acme.com", status="new"
        )
        db.session.add(company)
        db.session.flush()

        _seed_many_contacts(
            db, seed_tenant.id, owner.id, company.id, n=100, tied_count=50
        )

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        ids = _fetch_all_ids(
            client,
            headers,
            "/api/contacts",
            page_size=25,
            sort="seniority_level",
            key="contacts",
        )

        assert len(ids) == 100
        assert len(set(ids)) == 100, "Duplicate contact ids across pages"

    def test_page_disjoint_with_small_page_size(
        self, client, db, seed_tenant, seed_super_admin
    ):
        """Explicit page-1 vs page-2 disjointness check (smaller surface)."""
        from api.models import Owner, Company, UserTenantRole

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
        company = Company(
            tenant_id=seed_tenant.id, name="Acme", domain="acme.com", status="new"
        )
        db.session.add(company)
        db.session.flush()

        _seed_many_contacts(
            db, seed_tenant.id, owner.id, company.id, n=100, tied_count=50
        )

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        page1 = client.get(
            "/api/contacts?page=1&page_size=50&sort=department",
            headers=headers,
        ).get_json()
        page2 = client.get(
            "/api/contacts?page=2&page_size=50&sort=department",
            headers=headers,
        ).get_json()

        ids1 = {c["id"] for c in page1["contacts"]}
        ids2 = {c["id"] for c in page2["contacts"]}
        assert len(ids1) == 50
        assert len(ids2) == 50
        assert ids1 & ids2 == set(), "Page 1 and Page 2 must be disjoint"


class TestCompaniesPaginationStable:
    """Same check on the companies list endpoint."""

    def test_no_overlap_sorted_by_nullable_tier(
        self, client, db, seed_tenant, seed_super_admin
    ):
        from api.models import Owner, UserTenantRole

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

        _seed_many_companies(db, seed_tenant.id, owner.id, n=100, tied_count=50)

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        ids = _fetch_all_ids(
            client,
            headers,
            "/api/companies",
            page_size=25,
            sort="tier",
            key="companies",
        )

        assert len(ids) == 100
        assert len(set(ids)) == 100, "Duplicate company ids across pages"

    def test_no_overlap_sorted_by_nullable_industry(
        self, client, db, seed_tenant, seed_super_admin
    ):
        from api.models import Owner, UserTenantRole

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

        _seed_many_companies(db, seed_tenant.id, owner.id, n=100, tied_count=50)

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        ids = _fetch_all_ids(
            client,
            headers,
            "/api/companies",
            page_size=25,
            sort="industry",
            key="companies",
        )

        assert len(ids) == 100
        assert len(set(ids)) == 100, "Duplicate company ids across pages"
