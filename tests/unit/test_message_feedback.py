"""Unit tests for MessageFeedback auto-capture and feedback summary (Phase 4a)."""

import json

from tests.conftest import auth_header


def _setup_campaign_with_messages(db, seed, msg_count=3):
    """Create a campaign with messages linked via campaign_contacts."""
    from api.models import Campaign, CampaignContact, CampaignStep, Message

    tenant_id = seed["tenant"].id
    owner = seed["owners"][0]

    campaign = Campaign(
        tenant_id=tenant_id,
        name="Feedback Test Campaign",
        status="review",
    )
    db.session.add(campaign)
    db.session.flush()

    step = CampaignStep(
        campaign_id=campaign.id,
        tenant_id=tenant_id,
        position=1,
        channel="linkedin_connect",
        day_offset=0,
        label="Step 1",
    )
    db.session.add(step)
    db.session.flush()

    messages = []
    campaign_contacts = []
    for i in range(min(msg_count, len(seed["contacts"]))):
        contact = seed["contacts"][i]
        cc = CampaignContact(
            campaign_id=campaign.id,
            contact_id=contact.id,
            tenant_id=tenant_id,
            status="generated",
        )
        db.session.add(cc)
        db.session.flush()
        campaign_contacts.append(cc)

        m = Message(
            tenant_id=tenant_id,
            contact_id=contact.id,
            owner_id=owner.id,
            channel="linkedin_connect",
            sequence_step=1,
            variant="a",
            subject=f"Subject {i}",
            body=f"Hello {contact.first_name}, original message body.",
            status="draft",
            campaign_contact_id=cc.id,
            campaign_step_id=step.id,
            tag_id=seed["tags"][0].id,
        )
        db.session.add(m)
        messages.append(m)

    db.session.flush()
    db.session.commit()
    return campaign, campaign_contacts, messages


class TestEditFeedbackCapture:
    """Editing a message auto-creates a MessageFeedback record."""

    def test_edit_body_creates_feedback(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts
        campaign, ccs, msgs = _setup_campaign_with_messages(db, seed, msg_count=1)

        msg_id = str(msgs[0].id)

        resp = client.patch(
            f"/api/messages/{msg_id}",
            headers=headers,
            json={
                "body": "Completely rewritten message",
                "edit_reason": "too_formal",
                "edit_reason_text": "Needs a friendlier tone",
            },
        )
        assert resp.status_code == 200

        from api.models import MessageFeedback

        feedbacks = MessageFeedback.query.filter_by(message_id=msg_id).all()
        assert len(feedbacks) == 1
        fb = feedbacks[0]
        assert fb.action == "edited"
        assert fb.campaign_id == str(campaign.id)
        assert fb.edit_reason == "too_formal"
        assert fb.edit_reason_text == "Needs a friendlier tone"
        diff = (
            fb.edit_diff if isinstance(fb.edit_diff, dict) else json.loads(fb.edit_diff)
        )
        assert diff["field"] == "body"
        assert "original message body" in diff["before"]
        assert diff["after"] == "Completely rewritten message"


class TestApproveFeedbackCapture:
    """Approving a message auto-creates a MessageFeedback record."""

    def test_approve_creates_feedback(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts
        campaign, ccs, msgs = _setup_campaign_with_messages(db, seed, msg_count=1)

        msg_id = str(msgs[0].id)

        resp = client.patch(
            f"/api/messages/{msg_id}",
            headers=headers,
            json={"status": "approved"},
        )
        assert resp.status_code == 200

        from api.models import MessageFeedback

        feedbacks = MessageFeedback.query.filter_by(message_id=msg_id).all()
        assert len(feedbacks) == 1
        assert feedbacks[0].action == "approved"
        assert feedbacks[0].campaign_id == str(campaign.id)


class TestRejectFeedbackCapture:
    """Rejecting a message auto-creates a MessageFeedback record."""

    def test_reject_creates_feedback(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts
        campaign, ccs, msgs = _setup_campaign_with_messages(db, seed, msg_count=1)

        msg_id = str(msgs[0].id)

        resp = client.patch(
            f"/api/messages/{msg_id}",
            headers=headers,
            json={"status": "rejected"},
        )
        assert resp.status_code == 200

        from api.models import MessageFeedback

        feedbacks = MessageFeedback.query.filter_by(message_id=msg_id).all()
        assert len(feedbacks) == 1
        assert feedbacks[0].action == "rejected"
        assert feedbacks[0].campaign_id == str(campaign.id)


class TestBatchApproveFeedback:
    """Batch status change to approved creates feedback for each message."""

    def test_batch_approve_creates_feedback(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts
        campaign, ccs, msgs = _setup_campaign_with_messages(db, seed, msg_count=2)

        ids = [str(m.id) for m in msgs]

        resp = client.patch(
            "/api/messages/batch",
            headers=headers,
            json={"ids": ids, "fields": {"status": "approved"}},
        )
        assert resp.status_code == 200

        from api.models import MessageFeedback

        feedbacks = MessageFeedback.query.filter_by(campaign_id=str(campaign.id)).all()
        assert len(feedbacks) == 2
        assert all(f.action == "approved" for f in feedbacks)


class TestFeedbackSummary:
    """GET /api/campaigns/<id>/feedback-summary returns aggregated stats."""

    def test_summary_returns_correct_counts(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts
        campaign, ccs, msgs = _setup_campaign_with_messages(db, seed, msg_count=3)

        # Edit first message
        client.patch(
            f"/api/messages/{msgs[0].id}",
            headers=headers,
            json={
                "body": "Edited body",
                "edit_reason": "too_formal",
            },
        )
        # Approve second message
        client.patch(
            f"/api/messages/{msgs[1].id}",
            headers=headers,
            json={"status": "approved"},
        )
        # Approve third message
        client.patch(
            f"/api/messages/{msgs[2].id}",
            headers=headers,
            json={"status": "approved"},
        )

        resp = client.get(
            f"/api/campaigns/{campaign.id}/feedback-summary",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 3
        assert data["by_action"]["edited"] == 1
        assert data["by_action"]["approved"] == 2
        assert len(data["top_edit_reasons"]) == 1
        assert data["top_edit_reasons"][0][0] == "too_formal"

    def test_empty_feedback_returns_zeroes(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts
        campaign, ccs, msgs = _setup_campaign_with_messages(db, seed, msg_count=1)

        resp = client.get(
            f"/api/campaigns/{campaign.id}/feedback-summary",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 0
        assert data["by_action"] == {}
        assert data["top_edit_reasons"] == []
        assert data["per_step"] == {}

    def test_per_step_approval_rate(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        seed = seed_companies_contacts
        campaign, ccs, msgs = _setup_campaign_with_messages(db, seed, msg_count=3)

        step_id = str(msgs[0].campaign_step_id)

        # Approve 2, edit 1
        client.patch(
            f"/api/messages/{msgs[0].id}",
            headers=headers,
            json={"status": "approved"},
        )
        client.patch(
            f"/api/messages/{msgs[1].id}",
            headers=headers,
            json={"status": "approved"},
        )
        client.patch(
            f"/api/messages/{msgs[2].id}",
            headers=headers,
            json={
                "body": "Edited",
                "edit_reason": "too_casual",
            },
        )

        resp = client.get(
            f"/api/campaigns/{campaign.id}/feedback-summary",
            headers=headers,
        )
        data = resp.get_json()
        assert step_id in data["per_step"]
        step = data["per_step"][step_id]
        assert step["total"] == 3
        assert step["approved"] == 2
        assert step["approval_rate"] == 67  # round(2/3 * 100)

    def test_campaign_not_found(self, client, seed_companies_contacts, db):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.get(
            "/api/campaigns/00000000-0000-0000-0000-000000000000/feedback-summary",
            headers=headers,
        )
        assert resp.status_code == 404
