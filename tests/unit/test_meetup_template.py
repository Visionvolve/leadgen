"""Tests for meetup template creating sequence steps with execution defaults."""

import json

from tests.conftest import auth_header


def _headers(client):
    headers = auth_header(client)
    headers["X-Namespace"] = "test-corp"
    return headers


def _create_campaign(client, headers, name="Test Campaign"):
    resp = client.post("/api/campaigns", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


class TestMeetupTemplate:
    def test_meetup_template_creates_sequence_with_conditions(
        self, client, seed_companies_contacts
    ):
        """When populating from the meetup template, steps get condition and
        execution_status set correctly."""
        headers = _headers(client)

        # Create a template with meetup-style steps (including condition)
        meetup_steps = [
            {
                "step": 1,
                "channel": "linkedin_connect",
                "label": "LinkedIn Connect",
                "day_offset": 0,
                "condition": "always",
            },
            {
                "step": 2,
                "channel": "email",
                "label": "Email Follow-up",
                "day_offset": 3,
                "condition": "no_response",
            },
        ]
        resp = client.post(
            "/api/campaign-templates",
            headers=headers,
            json={
                "name": "Meetup Dual LinkedIn + Email",
                "steps": meetup_steps,
            },
        )
        assert resp.status_code == 201
        template_id = resp.get_json()["id"]

        # Create campaign and populate from template
        campaign_id = _create_campaign(client, headers)
        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/from-template",
            headers=headers,
            json={"template_id": template_id},
        )
        assert resp.status_code == 201
        steps = resp.get_json()["steps"]

        assert len(steps) == 2

        # Step 1: LinkedIn connect, always, pending
        assert steps[0]["channel"] == "linkedin_connect"
        assert steps[0]["day_offset"] == 0
        assert steps[0]["condition"] == "always"
        assert steps[0]["execution_status"] == "pending"
        assert steps[0]["started_at"] is None
        assert steps[0]["completed_at"] is None

        # Step 2: Email follow-up, no_response condition, pending
        assert steps[1]["channel"] == "email"
        assert steps[1]["day_offset"] == 3
        assert steps[1]["condition"] == "no_response"
        assert steps[1]["execution_status"] == "pending"

    def test_template_without_condition_defaults_to_always(
        self, client, seed_companies_contacts
    ):
        """Templates without explicit condition field default to 'always'."""
        headers = _headers(client)

        # Template steps without condition field
        simple_steps = [
            {"step": 1, "channel": "email", "label": "Cold Email", "day_offset": 0},
        ]
        resp = client.post(
            "/api/campaign-templates",
            headers=headers,
            json={"name": "Simple Template", "steps": simple_steps},
        )
        assert resp.status_code == 201
        template_id = resp.get_json()["id"]

        campaign_id = _create_campaign(client, headers)
        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps/from-template",
            headers=headers,
            json={"template_id": template_id},
        )
        assert resp.status_code == 201
        steps = resp.get_json()["steps"]
        assert steps[0]["condition"] == "always"
        assert steps[0]["execution_status"] == "pending"
