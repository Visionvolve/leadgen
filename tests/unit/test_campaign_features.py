"""Unit tests for UA campaign features: bulk contact add, campaign language,
step template config, and segment filter query."""

import json

from tests.conftest import auth_header


class TestCampaignLanguageField:
    """Test campaign creation with the new language field."""

    def test_campaign_default_language(self, client, seed_companies_contacts):
        """Campaign should default to 'cs' language."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.post(
            "/api/campaigns", headers=headers, json={"name": "CZ Campaign"}
        )
        assert resp.status_code == 201
        campaign_id = resp.get_json()["id"]

        resp = client.get(f"/api/campaigns/{campaign_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["language"] == "cs"

    def test_campaign_create_with_language(self, client, seed_companies_contacts):
        """Campaign can be created with explicit language."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.post(
            "/api/campaigns",
            headers=headers,
            json={"name": "DE Campaign", "language": "de"},
        )
        assert resp.status_code == 201


class TestStepTemplateConfig:
    """Test that step config supports template_body and template_subject."""

    def test_step_with_template_config(self, client, seed_companies_contacts):
        """Step config should accept template_body and template_subject."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        # Create campaign
        resp = client.post(
            "/api/campaigns", headers=headers, json={"name": "Template Test"}
        )
        assert resp.status_code == 201
        campaign_id = resp.get_json()["id"]

        # Create step with template content in config
        step_config = {
            "template_subject": "Nové programy",
            "template_body": "Dekujeme za spolupráci. Showreel: {{link}}",
            "tone": "professional",
            "language": "cs",
            "personalization_vars": ["link", "contact_name"],
        }
        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={
                "position": 1,
                "day_offset": 0,
                "channel": "email",
                "label": "Intro",
                "condition": "always",
                "config": step_config,
            },
        )
        assert resp.status_code == 201
        step = resp.get_json()

        # Verify config preserved
        config = step.get("config", {})
        if isinstance(config, str):
            config = json.loads(config)
        assert config.get("template_subject") == "Nové programy"
        assert "Dekujeme" in config.get("template_body", "")
        assert config.get("tone") == "professional"

    def test_step_config_without_template(self, client, seed_companies_contacts):
        """Step can be created with empty config (backward compatible)."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            "/api/campaigns", headers=headers, json={"name": "No Template"}
        )
        campaign_id = resp.get_json()["id"]

        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={
                "position": 1,
                "day_offset": 0,
                "channel": "email",
                "label": "Basic",
            },
        )
        assert resp.status_code == 201


class TestBulkContactAddBySegment:
    """Test bulk-add contacts to campaign by company segment."""

    def _setup_segment_data(self, db, seed_companies_contacts):
        """Set segment on a company for filtering."""
        from api.models import Company, Contact

        # Set segment on Acme Corp (has contacts John and Jane)
        companies = Company.query.all()
        for c in companies:
            if c.name == "Acme Corp":
                c.segment = "obec"
            elif c.name == "Beta Inc":
                c.segment = "agentura"
        db.session.commit()

        # Set language on contacts
        contacts = Contact.query.all()
        for ct in contacts:
            ct.language = "cs"
        db.session.commit()

        return companies, contacts

    def test_bulk_add_by_segment(self, client, db, seed_companies_contacts):
        """Bulk add contacts matching segment should work."""
        companies, contacts = self._setup_segment_data(db, seed_companies_contacts)
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        # Create campaign
        resp = client.post(
            "/api/campaigns", headers=headers, json={"name": "Bulk Test"}
        )
        assert resp.status_code == 201
        campaign_id = resp.get_json()["id"]

        # Bulk add contacts with segment=obec
        resp = client.post(
            f"/api/campaigns/{campaign_id}/contacts/bulk",
            headers=headers,
            json={"segment": "obec"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # Acme Corp has 2 contacts (John, Jane) — both should be added
        assert data["added"] == 2
        assert data["skipped"] == 0

    def test_bulk_add_with_language_filter(self, client, db, seed_companies_contacts):
        """Bulk add should respect language filter."""
        companies, contacts = self._setup_segment_data(db, seed_companies_contacts)
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        # Set one contact to 'de' to test filter
        from api.models import Contact

        john = Contact.query.filter_by(first_name="John").first()
        john.language = "de"
        db.session.commit()

        resp = client.post(
            "/api/campaigns", headers=headers, json={"name": "Lang Filter"}
        )
        campaign_id = resp.get_json()["id"]

        # Bulk add with language=cs (should exclude John who is now 'de')
        resp = client.post(
            f"/api/campaigns/{campaign_id}/contacts/bulk",
            headers=headers,
            json={"segment": "obec", "filters": {"language": "cs"}},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["added"] == 1  # Only Jane (cs)

    def test_bulk_add_missing_segment(self, client, db, seed_companies_contacts):
        """Bulk add without segment should return 400."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post("/api/campaigns", headers=headers, json={"name": "No Seg"})
        campaign_id = resp.get_json()["id"]

        resp = client.post(
            f"/api/campaigns/{campaign_id}/contacts/bulk",
            headers=headers,
            json={},
        )
        assert resp.status_code == 400
        assert "segment" in resp.get_json()["error"]

    def test_bulk_add_no_matching_contacts(self, client, db, seed_companies_contacts):
        """Bulk add with non-existent segment should return 0 added."""
        self._setup_segment_data(db, seed_companies_contacts)
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            "/api/campaigns", headers=headers, json={"name": "Empty Seg"}
        )
        campaign_id = resp.get_json()["id"]

        resp = client.post(
            f"/api/campaigns/{campaign_id}/contacts/bulk",
            headers=headers,
            json={"segment": "nonexistent"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["added"] == 0

    def test_bulk_add_skips_duplicates(self, client, db, seed_companies_contacts):
        """Second bulk add should skip already-added contacts."""
        self._setup_segment_data(db, seed_companies_contacts)
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post("/api/campaigns", headers=headers, json={"name": "Dup Test"})
        campaign_id = resp.get_json()["id"]

        # First add
        resp = client.post(
            f"/api/campaigns/{campaign_id}/contacts/bulk",
            headers=headers,
            json={"segment": "obec"},
        )
        assert resp.get_json()["added"] == 2

        # Second add — should skip all
        resp = client.post(
            f"/api/campaigns/{campaign_id}/contacts/bulk",
            headers=headers,
            json={"segment": "obec"},
        )
        data = resp.get_json()
        assert data["added"] == 0
        assert data["skipped"] == 2

    def test_bulk_add_campaign_not_found(self, client, db, seed_companies_contacts):
        """Bulk add to non-existent campaign returns 404."""
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            "/api/campaigns/00000000-0000-0000-0000-000000000000/contacts/bulk",
            headers=headers,
            json={"segment": "obec"},
        )
        assert resp.status_code == 404

    def test_bulk_add_ready_campaign(self, client, db, seed_companies_contacts):
        """Bulk add to a 'ready' campaign should succeed."""
        self._setup_segment_data(db, seed_companies_contacts)
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            "/api/campaigns", headers=headers, json={"name": "Ready Camp"}
        )
        campaign_id = resp.get_json()["id"]

        # Set status to 'ready'
        from api.models import db as _db

        _db.session.execute(
            _db.text("UPDATE campaigns SET status = 'ready' WHERE id = :id"),
            {"id": campaign_id},
        )
        _db.session.commit()

        resp = client.post(
            f"/api/campaigns/{campaign_id}/contacts/bulk",
            headers=headers,
            json={"segment": "obec"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["added"] == 2

    def test_bulk_add_non_draft_campaign(self, client, db, seed_companies_contacts):
        """Bulk add to non-draft campaign returns 400."""
        self._setup_segment_data(db, seed_companies_contacts)
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            "/api/campaigns", headers=headers, json={"name": "Active Camp"}
        )
        campaign_id = resp.get_json()["id"]

        # Manually set status to 'generating' (not draft/ready)
        from api.models import db as _db

        _db.session.execute(
            _db.text("UPDATE campaigns SET status = 'generating' WHERE id = :id"),
            {"id": campaign_id},
        )
        _db.session.commit()

        resp = client.post(
            f"/api/campaigns/{campaign_id}/contacts/bulk",
            headers=headers,
            json={"segment": "obec"},
        )
        assert resp.status_code == 400


class TestCompanySegmentField:
    """Test that companies have the segment field."""

    def test_company_segment_column(self, client, db, seed_companies_contacts):
        """Company model should have segment column."""
        from api.models import Company

        company = Company.query.first()
        assert hasattr(company, "segment")
        # Default should be None
        assert company.segment is None

    def test_company_segment_set(self, client, db, seed_companies_contacts):
        """Company segment can be set and persisted."""
        from api.models import Company

        company = Company.query.first()
        company.segment = "obec"
        db.session.commit()

        reloaded = Company.query.get(company.id)
        assert reloaded.segment == "obec"


class TestContactLastCollaborationField:
    """Test that contacts have last_collaboration_at field."""

    def test_contact_last_collaboration_column(
        self, client, db, seed_companies_contacts
    ):
        """Contact model should have last_collaboration_at column."""
        from api.models import Contact

        contact = Contact.query.first()
        assert hasattr(contact, "last_collaboration_at")
        assert contact.last_collaboration_at is None

    def test_contact_last_collaboration_set(self, client, db, seed_companies_contacts):
        """Contact last_collaboration_at can be set."""
        from datetime import datetime, timezone

        from api.models import Contact

        contact = Contact.query.first()
        now = datetime(2025, 6, 15, tzinfo=timezone.utc)
        contact.last_collaboration_at = now
        db.session.commit()

        reloaded = Contact.query.get(contact.id)
        assert reloaded.last_collaboration_at is not None
