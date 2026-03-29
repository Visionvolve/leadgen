"""Unit tests for AI design routes: POST /ai-design and POST /ai-design/confirm."""

from tests.conftest import auth_header


def _headers(client):
    headers = auth_header(client)
    headers["X-Namespace"] = "test-corp"
    return headers


def _create_campaign(client, headers, name="Test Campaign"):
    resp = client.post("/api/campaigns", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


class TestAiDesignRequiresGoal:
    def test_ai_design_requires_goal(self, client, seed_companies_contacts):
        """POST /ai-design without goal returns 400."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/ai-design",
            headers=headers,
            json={},
        )
        assert resp.status_code == 400
        assert "goal" in resp.get_json()["error"]

    def test_ai_design_requires_goal_null(self, client, seed_companies_contacts):
        """POST /ai-design with goal=null returns 400."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/ai-design",
            headers=headers,
            json={"goal": None},
        )
        assert resp.status_code == 400


class TestAiDesignConfirmSavesSteps:
    def test_ai_design_confirm_saves_steps(self, client, seed_companies_contacts):
        """POST /confirm with steps array creates CampaignStep rows and clears existing."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        # Add an existing step that should be replaced
        client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={"channel": "email", "label": "Old Step"},
        )

        # Confirm AI-proposed steps
        proposed = [
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
            {
                "channel": "email",
                "day_offset": 7,
                "label": "Email",
                "config": {"max_length": 1000, "tone": "formal"},
            },
        ]
        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/ai-design/confirm",
            headers=headers,
            json={"steps": proposed},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert len(data["steps"]) == 3

        # Verify positions are sequential
        assert [s["position"] for s in data["steps"]] == [1, 2, 3]

        # Verify channels match
        assert data["steps"][0]["channel"] == "linkedin_connect"
        assert data["steps"][1]["channel"] == "linkedin_message"
        assert data["steps"][2]["channel"] == "email"

        # Verify old step was replaced (only 3 steps total)
        resp = client.get(f"/api/campaigns/{campaign_id}/steps", headers=headers)
        assert len(resp.get_json()["steps"]) == 3


class TestAiDesignConfirmRequiresSteps:
    def test_ai_design_confirm_requires_steps(self, client, seed_companies_contacts):
        """POST /confirm without steps returns 400."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/ai-design/confirm",
            headers=headers,
            json={},
        )
        assert resp.status_code == 400
        assert "steps" in resp.get_json()["error"]

    def test_ai_design_confirm_empty_list_rejected(
        self, client, seed_companies_contacts
    ):
        """POST /confirm with empty steps list returns 400."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/ai-design/confirm",
            headers=headers,
            json={"steps": []},
        )
        assert resp.status_code == 400
