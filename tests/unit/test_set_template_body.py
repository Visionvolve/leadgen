"""Tests for ``POST /api/campaigns/<id>/set-template-body`` and the
templated branches of ``/generate-preview`` and ``/send-test``.

The endpoint exists for fixed-template transactional campaigns (e.g. the
AITransformers meetup invite) where every contact receives the same HTML
body with only ``{{first_name}}`` / ``{{unsubscribe_url}}`` substituted
per-recipient — no LLM involved. These tests cover:

1. Endpoint writes the supplied body to a new Message for each
   CampaignContact, with status='approved' and the canonical step linked.
2. Re-running updates existing Messages rather than creating duplicates.
3. ``Campaign.generation_config['template_type']`` is set so downstream
   paths know to apply placeholder substitution.
4. ``/generate-preview`` returns the stored body with ``{{first_name}}``
   substituted for templated campaigns (short-circuits the LLM).
"""

from __future__ import annotations

import json

from tests.conftest import auth_header


def _coerce_jsonb(value):
    """In SQLite test DB JSONB columns may be stored as text — coerce to
    a Python dict so assertions work the same on both backends."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return {}


def _headers(client):
    headers = auth_header(client)
    headers["X-Namespace"] = "test-corp"
    return headers


def _create_campaign(client, headers, name="AITransformers Meetup Test"):
    resp = client.post("/api/campaigns", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


def _add_contacts_directly(db, tenant_id, count=3):
    """Create N contacts straight in the DB so the test doesn't depend
    on the icp_filters path (which requires enrichment fixtures)."""
    from api.models import Contact

    contacts = []
    for i in range(count):
        c = Contact(
            tenant_id=tenant_id,
            first_name=f"User{i}",
            last_name="Test",
            email_address=f"user{i}@example.test",
        )
        db.session.add(c)
        contacts.append(c)
    db.session.flush()
    return contacts


def _attach_to_campaign(db, tenant_id, campaign_id, contacts):
    """Attach contacts to a campaign and create the email step."""
    from api.models import CampaignContact, CampaignStep

    step = CampaignStep(
        campaign_id=campaign_id,
        tenant_id=tenant_id,
        position=1,
        channel="email",
        label="Invitation",
        day_offset=0,
    )
    db.session.add(step)

    for c in contacts:
        cc = CampaignContact(
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            contact_id=c.id,
            status="pending",
        )
        db.session.add(cc)
    db.session.flush()
    return step


class TestSetTemplateBody:
    def test_creates_messages_for_all_campaign_contacts(
        self, client, db, seed_companies_contacts, seed_tenant
    ):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)
        contacts = _add_contacts_directly(db, seed_tenant.id, count=4)
        _attach_to_campaign(db, seed_tenant.id, campaign_id, contacts)
        db.session.commit()

        payload = {
            "subject": "Meetup 20 May",
            "body_html": (
                "<p>Hello {{first_name}},</p>"
                "<p>Register: link. <a href='{{unsubscribe_url}}'>unsub</a></p>"
            ),
            "body_text": "Hello {{first_name}}, register at link. Unsub: {{unsubscribe_url}}",
            "from_name": "Michal Ličko",
            "from_email": "michal@visionvolve.ai",
        }
        resp = client.post(
            f"/api/campaigns/{campaign_id}/set-template-body",
            headers=headers,
            json=payload,
        )
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        assert data["ok"] is True
        assert data["messages_created"] == 4
        assert data["messages_updated"] == 0
        assert data["total_contacts"] == 4

        # Verify Messages exist with the supplied body and approved status.
        from api.models import Campaign, CampaignContact, Message

        ccs = (
            db.session.query(CampaignContact)
            .filter(CampaignContact.campaign_id == campaign_id)
            .all()
        )
        assert len(ccs) == 4
        for cc in ccs:
            msg = (
                db.session.query(Message)
                .filter(
                    Message.campaign_contact_id == cc.id,
                    Message.channel == "email",
                )
                .first()
            )
            assert msg is not None
            assert msg.subject == "Meetup 20 May"
            assert "{{first_name}}" in msg.body
            assert msg.status == "approved"
            assert cc.status == "generated"
            assert cc.generated_at is not None

        # Campaign-level state.
        camp = db.session.get(Campaign, campaign_id)
        assert camp.generated_count == 4
        assert camp.status == "review"
        gen_cfg = _coerce_jsonb(camp.generation_config)
        assert gen_cfg.get("template_type") == "aitransformers_meetup"
        sender = _coerce_jsonb(camp.sender_config)
        assert sender.get("from_email") == "michal@visionvolve.ai"
        assert sender.get("from_name") == "Michal Ličko"

    def test_rerun_is_idempotent(
        self, client, db, seed_companies_contacts, seed_tenant
    ):
        """Second call updates the same Messages, never duplicates."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)
        contacts = _add_contacts_directly(db, seed_tenant.id, count=2)
        _attach_to_campaign(db, seed_tenant.id, campaign_id, contacts)
        db.session.commit()

        first = {
            "subject": "First",
            "body_html": "<p>Hi {{first_name}}</p>",
            "from_email": "a@example.test",
            "from_name": "A",
        }
        client.post(
            f"/api/campaigns/{campaign_id}/set-template-body",
            headers=headers,
            json=first,
        )
        second = dict(first, subject="Second", body_html="<p>Hello {{first_name}}</p>")
        resp = client.post(
            f"/api/campaigns/{campaign_id}/set-template-body",
            headers=headers,
            json=second,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["messages_created"] == 0
        assert data["messages_updated"] == 2

        from api.models import CampaignContact, Message

        # Exactly one Message per CampaignContact.
        ccs = (
            db.session.query(CampaignContact)
            .filter(CampaignContact.campaign_id == campaign_id)
            .all()
        )
        for cc in ccs:
            msgs = (
                db.session.query(Message)
                .filter(
                    Message.campaign_contact_id == cc.id,
                    Message.channel == "email",
                )
                .all()
            )
            assert len(msgs) == 1
            assert msgs[0].subject == "Second"
            assert "Hello" in msgs[0].body

    def test_rejects_missing_required_fields(
        self, client, db, seed_companies_contacts, seed_tenant
    ):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        cases = [
            {},
            {"subject": "x", "from_email": "a@b.test"},
            {"subject": "x", "body_html": "<p>x</p>"},
            {"body_html": "<p>x</p>", "from_email": "a@b.test"},
        ]
        for payload in cases:
            resp = client.post(
                f"/api/campaigns/{campaign_id}/set-template-body",
                headers=headers,
                json=payload,
            )
            assert resp.status_code == 400, payload

    def test_returns_404_for_unknown_campaign(self, client, seed_companies_contacts):
        headers = _headers(client)
        resp = client.post(
            "/api/campaigns/00000000-0000-0000-0000-000000000000/set-template-body",
            headers=headers,
            json={
                "subject": "x",
                "body_html": "<p>x</p>",
                "from_email": "a@b.test",
            },
        )
        assert resp.status_code == 404


class TestGeneratePreviewTemplatedShortCircuit:
    def test_returns_stored_body_with_first_name_substituted(
        self, client, db, seed_companies_contacts, seed_tenant
    ):
        """For a templated campaign, preview returns Message.body with
        {{first_name}} replaced by the contact's actual first name —
        without ever hitting the LLM."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        # Create one contact with a known first name.
        from api.models import Contact

        contact = Contact(
            tenant_id=seed_tenant.id,
            first_name="Ada",
            last_name="Lovelace",
            email_address="ada@example.test",
        )
        db.session.add(contact)
        db.session.flush()
        _attach_to_campaign(db, seed_tenant.id, campaign_id, [contact])
        db.session.commit()

        # Run set-template-body to install the templated body.
        payload = {
            "subject": "Meetup 20 May",
            "body_html": (
                "<p>Hello {{first_name}},</p>"
                "<p>See you. <a href='{{unsubscribe_url}}'>unsub</a></p>"
            ),
            "from_email": "michal@visionvolve.ai",
            "from_name": "Michal",
        }
        resp = client.post(
            f"/api/campaigns/{campaign_id}/set-template-body",
            headers=headers,
            json=payload,
        )
        assert resp.status_code == 200

        # /generate-preview must NOT call the LLM (test would crash if it
        # did — no ANTHROPIC_API_KEY mocked). Short-circuit returns the
        # rendered body.
        resp = client.post(
            f"/api/campaigns/{campaign_id}/generate-preview",
            headers=headers,
            json={"contact_id": str(contact.id), "step_position": 1},
        )
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        assert data["templated"] is True
        assert data["template_type"] == "aitransformers_meetup"
        assert data["subject"] == "Meetup 20 May"
        assert "Hello Ada," in data["body"]
        assert "{{first_name}}" not in data["body"]
        # unsubscribe_url is substituted with either an HTTPS URL or a
        # mailto fallback — never the raw placeholder.
        assert "{{unsubscribe_url}}" not in data["body"]
