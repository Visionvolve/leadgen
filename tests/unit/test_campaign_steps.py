"""Unit tests for campaign step CRUD routes."""

import json
from unittest.mock import MagicMock, patch

from tests.conftest import auth_header


def _headers(client):
    headers = auth_header(client)
    headers["X-Namespace"] = "test-corp"
    return headers


def _create_campaign(client, headers, name="Test Campaign"):
    """Create a campaign and return its id."""
    resp = client.post("/api/campaigns", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


class TestListSteps:
    def test_list_steps_empty(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.get(f"/api/campaigns/{campaign_id}/steps", headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["steps"] == []


class TestAddStep:
    def test_add_step(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={
                "channel": "email",
                "day_offset": 0,
                "label": "Cold Email",
                "config": {
                    "tone": "professional",
                    "example_messages": ["Hi {{first_name}}"],
                },
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["channel"] == "email"
        assert data["label"] == "Cold Email"
        assert data["position"] == 1
        assert data["config"]["tone"] == "professional"
        assert data["config"]["example_messages"] == ["Hi {{first_name}}"]
        assert "id" in data

    def test_add_multiple_steps_auto_position(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        # Add first step
        resp1 = client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={"channel": "email", "label": "Step 1"},
        )
        assert resp1.status_code == 201
        assert resp1.get_json()["position"] == 1

        # Add second step — position should auto-increment
        resp2 = client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={"channel": "linkedin_message", "label": "Step 2"},
        )
        assert resp2.status_code == 201
        assert resp2.get_json()["position"] == 2

        # Add third step
        resp3 = client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={"channel": "email", "label": "Step 3"},
        )
        assert resp3.status_code == 201
        assert resp3.get_json()["position"] == 3

        # Verify list order
        resp = client.get(f"/api/campaigns/{campaign_id}/steps", headers=headers)
        steps = resp.get_json()["steps"]
        assert len(steps) == 3
        assert [s["position"] for s in steps] == [1, 2, 3]


class TestUpdateStep:
    def test_update_step(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        # Create step
        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={"channel": "email", "label": "Original"},
        )
        step_id = resp.get_json()["id"]

        # Update it
        resp = client.patch(
            f"/api/campaigns/{campaign_id}/steps/{step_id}",
            headers=headers,
            json={"label": "Updated", "config": {"tone": "casual"}},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["label"] == "Updated"
        assert data["config"]["tone"] == "casual"


class TestDeleteStep:
    def test_delete_step_reorders(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        # Create 3 steps
        ids = []
        for i, label in enumerate(["A", "B", "C"], 1):
            resp = client.post(
                f"/api/campaigns/{campaign_id}/steps",
                headers=headers,
                json={"channel": "email", "label": label},
            )
            ids.append(resp.get_json()["id"])

        # Delete middle step (B, position=2)
        resp = client.delete(
            f"/api/campaigns/{campaign_id}/steps/{ids[1]}", headers=headers
        )
        assert resp.status_code == 200

        # Verify remaining steps reordered: A=1, C=2
        resp = client.get(f"/api/campaigns/{campaign_id}/steps", headers=headers)
        steps = resp.get_json()["steps"]
        assert len(steps) == 2
        assert steps[0]["label"] == "A"
        assert steps[0]["position"] == 1
        assert steps[1]["label"] == "C"
        assert steps[1]["position"] == 2


class TestReorderSteps:
    def test_reorder_steps(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        # Create 3 steps
        ids = []
        for label in ["First", "Second", "Third"]:
            resp = client.post(
                f"/api/campaigns/{campaign_id}/steps",
                headers=headers,
                json={"channel": "email", "label": label},
            )
            ids.append(resp.get_json()["id"])

        # Reorder: Third, First, Second
        resp = client.put(
            f"/api/campaigns/{campaign_id}/steps/reorder",
            headers=headers,
            json={"order": [ids[2], ids[0], ids[1]]},
        )
        assert resp.status_code == 200
        steps = resp.get_json()["steps"]
        assert len(steps) == 3
        assert steps[0]["label"] == "Third"
        assert steps[0]["position"] == 1
        assert steps[1]["label"] == "First"
        assert steps[1]["position"] == 2
        assert steps[2]["label"] == "Second"
        assert steps[2]["position"] == 3


class TestPopulateFromTemplate:
    def test_populate_from_template(self, client, seed_companies_contacts):
        headers = _headers(client)

        # Create a template
        template_steps = [
            {
                "step": 1,
                "channel": "email",
                "label": "Cold Email",
                "config": {"tone": "formal"},
            },
            {
                "step": 2,
                "channel": "linkedin_message",
                "label": "LinkedIn Follow-up",
                "day_offset": 3,
            },
            {
                "step": 3,
                "channel": "email",
                "label": "Email Follow-up",
                "day_offset": 7,
            },
        ]
        resp = client.post(
            "/api/campaign-templates",
            headers=headers,
            json={"name": "Test Template", "steps": template_steps},
        )
        assert resp.status_code == 201
        template_id = resp.get_json()["id"]

        # Create campaign
        campaign_id = _create_campaign(client, headers)

        # Populate from template
        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/from-template",
            headers=headers,
            json={"template_id": template_id},
        )
        assert resp.status_code == 201
        steps = resp.get_json()["steps"]
        assert len(steps) == 3
        assert steps[0]["channel"] == "email"
        assert steps[0]["label"] == "Cold Email"
        assert steps[0]["position"] == 1
        assert steps[1]["channel"] == "linkedin_message"
        assert steps[1]["label"] == "LinkedIn Follow-up"
        assert steps[1]["position"] == 2
        assert steps[2]["channel"] == "email"
        assert steps[2]["label"] == "Email Follow-up"
        assert steps[2]["position"] == 3


class TestAiDesignSteps:
    @patch("api.services.step_designer.anthropic")
    def test_ai_design_returns_proposal(
        self, mock_anthropic, client, seed_companies_contacts
    ):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        # Mock Claude response
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "steps": [
                            {
                                "channel": "linkedin_connect",
                                "day_offset": 0,
                                "label": "Connect",
                                "config": {"max_length": 300, "tone": "informal"},
                            },
                            {
                                "channel": "linkedin_message",
                                "day_offset": 3,
                                "label": "Follow-up",
                                "config": {"max_length": 500, "tone": "informal"},
                            },
                        ],
                        "reasoning": "Start with connection, follow up in 3 days",
                    }
                )
            )
        ]
        mock_anthropic.Anthropic.return_value.messages.create.return_value = (
            mock_response
        )

        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/ai-design",
            headers=headers,
            json={"goal": "3-step LinkedIn outreach for SaaS CTOs"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["steps"]) == 2
        assert data["steps"][0]["channel"] == "linkedin_connect"
        assert data["steps"][1]["label"] == "Follow-up"
        assert "reasoning" in data

    def test_ai_design_missing_goal(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/ai-design",
            headers=headers,
            json={},
        )
        assert resp.status_code == 400
        assert "goal" in resp.get_json()["error"]


class TestAiDesignConfirm:
    def test_confirm_saves_steps(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        # Add an existing step first to verify it gets replaced
        client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={"channel": "email", "label": "Old Step"},
        )

        # Confirm AI-proposed steps
        proposed_steps = [
            {
                "channel": "linkedin_connect",
                "day_offset": 0,
                "label": "Connect",
                "config": {"max_length": 300, "tone": "informal"},
            },
            {
                "channel": "linkedin_message",
                "day_offset": 3,
                "label": "Follow-up",
                "config": {"max_length": 500, "tone": "informal"},
            },
        ]
        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/ai-design/confirm",
            headers=headers,
            json={"steps": proposed_steps},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert len(data["steps"]) == 2
        assert data["steps"][0]["channel"] == "linkedin_connect"
        assert data["steps"][0]["position"] == 1
        assert data["steps"][1]["channel"] == "linkedin_message"
        assert data["steps"][1]["position"] == 2

        # Verify old step was replaced
        resp = client.get(f"/api/campaigns/{campaign_id}/steps", headers=headers)
        assert len(resp.get_json()["steps"]) == 2

    def test_confirm_empty_steps_rejected(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/ai-design/confirm",
            headers=headers,
            json={"steps": []},
        )
        assert resp.status_code == 400
