"""Tests for per-contact ref tokens — BL-1104 (Milestone v25, Phase 7).

Covers:

* Idempotent issuance — re-POSTing returns the same token.
* Editor-or-above is required to issue a token.
* Public preferences lookup returns the variant + first name and is
  unauthenticated.
* Public visit endpoint bumps visit_count + writes an Activity row.
* Expired tokens 404 from public endpoints.
* Cross-tenant lookup is impossible — preferences look up by token alone
  so there is no tenant-bearing input to abuse; we assert two tenants can
  hold separate tokens that don't collide.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone


from api.models import Activity, RefToken, UserTenantRole, db
from tests.conftest import auth_header


def _set_editor_role(seed_companies_contacts, seed_user_with_role):
    """Upgrade the regular seed user to editor on the tenant. Helper for
    role-gating tests where the seed default is viewer."""
    role = UserTenantRole.query.filter_by(
        user_id=seed_user_with_role.id,
        tenant_id=seed_companies_contacts["tenant"].id,
    ).first()
    if role:
        role.role = "editor"
        db.session.commit()


class TestRefTokenIssuance:
    def test_editor_can_issue_with_prices_token(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        contact_id = seed_companies_contacts["contacts"][0].id

        resp = client.post(
            f"/api/contacts/{contact_id}/ref-token",
            json={"variant": "with_prices"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.get_json()
        body = resp.get_json()
        assert body["variant"] == "with_prices"
        assert body["reused"] is False
        assert len(body["token"]) == 32
        assert "ref=" in body["url"]
        assert body["token"] in body["url"]

    def test_issuance_is_idempotent_for_same_variant(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        contact_id = seed_companies_contacts["contacts"][0].id

        r1 = client.post(
            f"/api/contacts/{contact_id}/ref-token",
            json={"variant": "without_prices"},
            headers=headers,
        )
        assert r1.status_code == 201
        token1 = r1.get_json()["token"]

        r2 = client.post(
            f"/api/contacts/{contact_id}/ref-token",
            json={"variant": "without_prices"},
            headers=headers,
        )
        assert r2.status_code == 200
        body2 = r2.get_json()
        assert body2["token"] == token1
        assert body2["reused"] is True

    def test_different_variants_get_different_tokens(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        contact_id = seed_companies_contacts["contacts"][0].id

        r_with = client.post(
            f"/api/contacts/{contact_id}/ref-token",
            json={"variant": "with_prices"},
            headers=headers,
        )
        r_without = client.post(
            f"/api/contacts/{contact_id}/ref-token",
            json={"variant": "without_prices"},
            headers=headers,
        )
        assert r_with.status_code == 201
        assert r_without.status_code == 201
        assert r_with.get_json()["token"] != r_without.get_json()["token"]

    def test_viewer_cannot_issue_token(
        self, client, seed_user_with_role, seed_companies_contacts
    ):
        # seed_user_with_role is a viewer on the tenant by default.
        headers = auth_header(client, email="user@test.com")
        headers["X-Namespace"] = "test-corp"
        contact_id = seed_companies_contacts["contacts"][0].id

        resp = client.post(
            f"/api/contacts/{contact_id}/ref-token",
            json={"variant": "with_prices"},
            headers=headers,
        )
        assert resp.status_code == 403

    def test_invalid_variant_400(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        contact_id = seed_companies_contacts["contacts"][0].id

        resp = client.post(
            f"/api/contacts/{contact_id}/ref-token",
            json={"variant": "free"},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_unknown_contact_404(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        bogus = str(uuid.uuid4())
        resp = client.post(
            f"/api/contacts/{bogus}/ref-token",
            json={"variant": "with_prices"},
            headers=headers,
        )
        assert resp.status_code == 404


class TestPublicPreferences:
    def test_lookup_returns_variant_and_first_name(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        contact = seed_companies_contacts["contacts"][0]

        create = client.post(
            f"/api/contacts/{contact.id}/ref-token",
            json={"variant": "without_prices"},
            headers=headers,
        )
        token = create.get_json()["token"]

        # PUBLIC — no auth headers.
        resp = client.get(f"/api/ref-tokens/{token}/preferences")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["variant"] == "without_prices"
        assert body["contact_first_name"] == contact.first_name
        assert body["contact_id"] == contact.id
        assert body["tenant_id"] == seed_companies_contacts["tenant"].id

    def test_unknown_token_404(self, client):
        resp = client.get(
            "/api/ref-tokens/ABCDEFGHIJKLMNOPQRSTUVWXYZ012345/preferences"
        )
        assert resp.status_code == 404

    def test_expired_token_404(self, client, seed_companies_contacts):
        # Seed a token directly with an expiry in the past.
        contact = seed_companies_contacts["contacts"][0]
        expired = RefToken(
            token="EXPIRED" + "0" * 25,
            tenant_id=seed_companies_contacts["tenant"].id,
            contact_id=contact.id,
            variant="with_prices",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.session.add(expired)
        db.session.commit()

        resp = client.get(f"/api/ref-tokens/{expired.token}/preferences")
        assert resp.status_code == 404


class TestPublicVisit:
    def test_visit_increments_counter_and_writes_activity(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        contact_id = seed_companies_contacts["contacts"][0].id

        create = client.post(
            f"/api/contacts/{contact_id}/ref-token",
            json={"variant": "with_prices"},
            headers=headers,
        )
        token = create.get_json()["token"]

        # Three visits (PUBLIC).
        for _ in range(3):
            r = client.post(f"/api/ref-tokens/{token}/visit")
            assert r.status_code == 204

        # Reload the row and check counters.
        tok = db.session.get(RefToken, token)
        assert tok.visit_count == 3
        assert tok.first_visited_at is not None
        assert tok.last_visited_at is not None
        # last_visited_at >= first_visited_at (allow equality for fast runs).
        assert tok.last_visited_at >= tok.first_visited_at

        # Listing endpoint reflects the visit count.
        list_resp = client.get(
            f"/api/contacts/{contact_id}/ref-tokens", headers=headers
        )
        assert list_resp.status_code == 200
        tokens = list_resp.get_json()["tokens"]
        assert len(tokens) >= 1
        match = next(t for t in tokens if t["token"] == token)
        assert match["visit_count"] == 3

        # An Activity row was written.
        activities = Activity.query.filter_by(external_id=token).all()
        assert len(activities) == 3
        for a in activities:
            assert a.event_type == "catalog_ref_visited"
            assert a.source == "ua_microsite_ref"
            assert a.contact_id == contact_id

    def test_visit_on_expired_token_404(self, client, seed_companies_contacts):
        contact = seed_companies_contacts["contacts"][0]
        expired = RefToken(
            token="EXPIRED2" + "0" * 24,
            tenant_id=seed_companies_contacts["tenant"].id,
            contact_id=contact.id,
            variant="with_prices",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.session.add(expired)
        db.session.commit()

        r = client.post(f"/api/ref-tokens/{expired.token}/visit")
        assert r.status_code == 404


class TestCrossTenant:
    def test_two_tenants_have_independent_tokens(self, client, seed_companies_contacts):
        """Cross-tenant safety: each token resolves to its own tenant + contact
        via the token itself (no tenant-bearing query input to confuse)."""
        from api.models import Tenant, Contact

        # Insert a second tenant with its own contact directly.
        other = Tenant(name="Other Corp", slug="other-corp", is_active=True)
        db.session.add(other)
        db.session.flush()

        other_contact = Contact(
            tenant_id=other.id,
            first_name="Pavel",
            last_name="Novak",
            email_address="pavel@other.test",
        )
        db.session.add(other_contact)
        db.session.flush()

        other_tok = RefToken(
            token="OTHERTENANT" + "0" * 21,
            tenant_id=other.id,
            contact_id=other_contact.id,
            variant="with_prices",
        )
        db.session.add(other_tok)

        # And one for the seeded tenant's contact.
        first_contact = seed_companies_contacts["contacts"][0]
        own_tok = RefToken(
            token="OWNTENANT" + "0" * 23,
            tenant_id=seed_companies_contacts["tenant"].id,
            contact_id=first_contact.id,
            variant="without_prices",
        )
        db.session.add(own_tok)
        db.session.commit()

        # Each preferences lookup returns the matching tenant_id only.
        r1 = client.get(f"/api/ref-tokens/{other_tok.token}/preferences")
        r2 = client.get(f"/api/ref-tokens/{own_tok.token}/preferences")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.get_json()["tenant_id"] == other.id
        assert r2.get_json()["tenant_id"] == seed_companies_contacts["tenant"].id
        assert r1.get_json()["contact_first_name"] == "Pavel"
        assert r2.get_json()["contact_first_name"] == first_contact.first_name

    def test_list_endpoint_scoped_to_resolved_tenant(
        self, client, seed_companies_contacts
    ):
        """The authenticated list endpoint refuses contacts outside the
        resolved tenant — operator cannot list tokens for someone else's
        contact even if they know the contact_id."""
        from api.models import Tenant, Contact

        other = Tenant(name="Other Corp 2", slug="other-corp-2", is_active=True)
        db.session.add(other)
        db.session.flush()
        other_contact = Contact(
            tenant_id=other.id,
            first_name="Eva",
            last_name="X",
            email_address="eva@x.test",
        )
        db.session.add(other_contact)
        db.session.commit()

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.get(
            f"/api/contacts/{other_contact.id}/ref-tokens", headers=headers
        )
        assert resp.status_code == 404


class TestRefTokenBadInputHardening:
    """Hotfix v25 — endpoints must NOT 500 on malformed path params.

    Reproduces the bug class fixed in PR #175 for /api/unsubscribe.
    Without format-validation a malformed UUID/token would reach the
    PostgreSQL driver and trip InvalidTextRepresentation → Flask 500.
    SQLite (used in tests) tolerates the bad string, so we assert on
    the expected 400/404 returned by the format check itself rather
    than relying on the driver to crash.
    """

    def test_preferences_bogus_token_returns_400(self, client):
        resp = client.get("/api/ref-tokens/bogus/preferences")
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "invalid_token"}

    def test_preferences_wellformed_unknown_token_returns_404(self, client):
        # 32 uppercase base32 chars — passes format check, but no row exists.
        resp = client.get(
            "/api/ref-tokens/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/preferences"
        )
        assert resp.status_code == 404

    def test_visit_bogus_token_returns_400(self, client):
        resp = client.post("/api/ref-tokens/not-a-token/visit")
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "invalid_token"}

    def test_visit_wellformed_unknown_token_returns_404(self, client):
        resp = client.post("/api/ref-tokens/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/visit")
        assert resp.status_code == 404

    def test_create_ref_token_bad_contact_id_returns_400(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.post(
            "/api/contacts/not-a-uuid/ref-token",
            json={"variant": "with_prices"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "invalid_contact_id"}

    def test_list_ref_tokens_bad_contact_id_returns_400(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/contacts/not-a-uuid/ref-tokens", headers=headers)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "invalid_contact_id"}
