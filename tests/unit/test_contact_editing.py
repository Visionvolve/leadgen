"""Tests for editable contact / company fields + salutation auto-derive + audit log.

BL-1106 (salutation) and BL-1107 (inline-edit + audit) — v25 Phase 5.
"""

from sqlalchemy import text as sa_text

from api.models import db
from tests.conftest import auth_header


def _get_contact_row(contact_id: str):
    return db.session.execute(
        sa_text(
            "SELECT first_name, last_name, email_address, salutation, "
            "salutation_overridden FROM contacts WHERE id = :id"
        ),
        {"id": contact_id},
    ).fetchone()


def _audit_rows(contact_id: str, entity_type: str = "contact"):
    return db.session.execute(
        sa_text(
            """
            SELECT field_name, old_value, new_value
            FROM contact_field_changes
            WHERE entity_type = :et AND entity_id = :id
            ORDER BY field_name
            """
        ),
        {"et": entity_type, "id": contact_id},
    ).fetchall()


class TestSalutationAutoDerive:
    def test_patch_first_name_auto_derives_salutation_when_not_overridden(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        # John Doe (contact 0) starts with no salutation override.
        contact = seed_companies_contacts["contacts"][0]
        contact_id = contact.id

        resp = client.patch(
            f"/api/contacts/{contact_id}",
            json={"first_name": "Jan"},
            headers=headers,
        )
        assert resp.status_code == 200

        row = _get_contact_row(contact_id)
        assert row[0] == "Jan"
        # Czech vocative of "Jan" -> "Jane" (from VOCATIVE_MAP).
        assert row[3] == "Jane"
        assert row[4] is False or row[4] == 0  # SQLite stores False as 0

    def test_patch_salutation_explicit_sets_overridden_flag(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        contact_id = seed_companies_contacts["contacts"][0].id

        resp = client.patch(
            f"/api/contacts/{contact_id}",
            json={"salutation": "Janče"},
            headers=headers,
        )
        assert resp.status_code == 200

        row = _get_contact_row(contact_id)
        assert row[3] == "Janče"
        assert bool(row[4]) is True

    def test_patch_first_name_does_not_re_derive_after_override(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        contact_id = seed_companies_contacts["contacts"][0].id

        # Step 1: user manually overrides salutation.
        r1 = client.patch(
            f"/api/contacts/{contact_id}",
            json={"salutation": "Honzo"},
            headers=headers,
        )
        assert r1.status_code == 200

        # Step 2: edit first_name — salutation must NOT change.
        r2 = client.patch(
            f"/api/contacts/{contact_id}",
            json={"first_name": "Petr"},
            headers=headers,
        )
        assert r2.status_code == 200

        row = _get_contact_row(contact_id)
        assert row[0] == "Petr"
        assert row[3] == "Honzo"  # preserved
        assert bool(row[4]) is True


class TestEmailValidation:
    def test_patch_email_format_invalid_400(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        contact_id = seed_companies_contacts["contacts"][0].id

        resp = client.patch(
            f"/api/contacts/{contact_id}",
            json={"email_address": "not-an-email"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Invalid email" in resp.get_json()["error"]

        # No audit row should be written for the failed update.
        rows = _audit_rows(contact_id)
        assert rows == []

    def test_patch_email_duplicate_409_unless_confirm(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        # John (contacts[0]) = john@acme.com, Jane (contacts[1]) = jane@acme.com
        john_id = seed_companies_contacts["contacts"][0].id
        jane_email = seed_companies_contacts["contacts"][1].email_address

        # First attempt: should 409 with duplicate warning.
        resp = client.patch(
            f"/api/contacts/{john_id}",
            json={"email_address": jane_email},
            headers=headers,
        )
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["warning"] == "duplicate"
        assert body["code"] == "duplicate_email"
        assert body["details"]["existing_name"]

        # John's email should NOT have changed.
        row = _get_contact_row(john_id)
        assert row[2] == "john@acme.com"

        # Retry with confirm_duplicate=true: should succeed.
        resp2 = client.patch(
            f"/api/contacts/{john_id}?confirm_duplicate=true",
            json={"email_address": jane_email},
            headers=headers,
        )
        assert resp2.status_code == 200
        row2 = _get_contact_row(john_id)
        assert row2[2] == jane_email


class TestAuditLog:
    def test_patch_writes_field_change_audit_row(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        contact_id = seed_companies_contacts["contacts"][0].id

        resp = client.patch(
            f"/api/contacts/{contact_id}",
            json={"notes": "First time noted", "job_title": "Founder"},
            headers=headers,
        )
        assert resp.status_code == 200

        rows = _audit_rows(contact_id)
        # Expect at least one row each for notes and job_title.
        fields = {r[0] for r in rows}
        assert "notes" in fields
        assert "job_title" in fields

        # New value should match what was sent.
        notes_row = next(r for r in rows if r[0] == "notes")
        assert notes_row[2] == "First time noted"

    def test_patch_unchanged_field_skips_audit_row(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        contact_id = seed_companies_contacts["contacts"][0].id

        # Seed: John's notes are None. Set notes to "x", then PATCH to "x"
        # again — second PATCH should not generate an audit row.
        client.patch(
            f"/api/contacts/{contact_id}",
            json={"notes": "x"},
            headers=headers,
        )
        rows_before = _audit_rows(contact_id)
        notes_rows_before = [r for r in rows_before if r[0] == "notes"]

        client.patch(
            f"/api/contacts/{contact_id}",
            json={"notes": "x"},  # same value
            headers=headers,
        )
        rows_after = _audit_rows(contact_id)
        notes_rows_after = [r for r in rows_after if r[0] == "notes"]

        assert len(notes_rows_after) == len(notes_rows_before)

    def test_patch_company_name_writes_audit_row(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        company_id = seed_companies_contacts["companies"][0].id

        resp = client.patch(
            f"/api/companies/{company_id}",
            json={"name": "ACME s.r.o."},
            headers=headers,
        )
        assert resp.status_code == 200

        rows = _audit_rows(company_id, entity_type="company")
        name_rows = [r for r in rows if r[0] == "name"]
        assert len(name_rows) == 1
        assert name_rows[0][1] == "Acme Corp"
        assert name_rows[0][2] == "ACME s.r.o."


class TestContactCompanyBadInputHardening:
    """Hotfix v25 — contact/company endpoints must NOT 500 on bad UUID."""

    def test_get_contact_bad_format_returns_400(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/contacts/not-a-uuid", headers=headers)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "invalid_contact_id"}

    def test_patch_contact_bad_format_returns_400(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.patch(
            "/api/contacts/not-a-uuid",
            json={"first_name": "X"},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_patch_contact_unknown_wellformed_returns_404(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        unknown = "00000000-0000-0000-0000-000000000000"
        resp = client.patch(
            f"/api/contacts/{unknown}",
            json={"first_name": "X"},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_get_company_bad_format_returns_400(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get("/api/companies/not-a-uuid", headers=headers)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "invalid_company_id"}

    def test_patch_company_bad_format_returns_400(
        self, client, seed_companies_contacts
    ):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.patch(
            "/api/companies/not-a-uuid",
            json={"name": "X"},
            headers=headers,
        )
        assert resp.status_code == 400
