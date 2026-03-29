"""Unit tests for sequence execution model behavior."""

import json
import uuid

from tests.conftest import auth_header


def _headers(client):
    headers = auth_header(client)
    headers["X-Namespace"] = "test-corp"
    return headers


def _create_campaign(client, headers, name="Test Campaign"):
    resp = client.post("/api/campaigns", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


class TestExecutionStatusDefault:
    def test_execution_status_default_pending(self, client, seed_companies_contacts):
        """New steps have execution_status='pending' by default."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={"channel": "email", "label": "Step 1"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["execution_status"] == "pending"


class TestUpdateExecutionStatus:
    def test_update_execution_status_to_active(self, client, seed_companies_contacts):
        """Can update execution_status to 'active' via sequence PATCH."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={"channel": "email", "label": "Step 1"},
        )

        resp = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/1",
            headers=headers,
            json={"execution_status": "active"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["execution_status"] == "active"

    def test_update_execution_status_to_completed_sets_timestamp(
        self, client, seed_companies_contacts
    ):
        """Can set completed_at timestamp along with 'completed' status."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={"channel": "email", "label": "Step 1"},
        )

        resp = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/1",
            headers=headers,
            json={
                "execution_status": "completed",
                "completed_at": "2026-03-12T15:30:00+00:00",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["execution_status"] == "completed"
        assert data["completed_at"] is not None
        assert "2026-03-12" in data["completed_at"]


class TestConditionStored:
    def test_condition_stored_correctly(self, client, seed_companies_contacts):
        """Condition values are persisted through PUT sequence."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.put(
            f"/api/campaigns/{campaign_id}/sequence",
            headers=headers,
            json={
                "steps": [
                    {"channel": "linkedin_connect", "condition": "always"},
                    {"channel": "email", "condition": "no_response"},
                    {"channel": "email", "condition": "opened_not_replied"},
                ]
            },
        )
        assert resp.status_code == 200
        seq = resp.get_json()["sequence"]
        assert seq[0]["condition"] == "always"
        assert seq[1]["condition"] == "no_response"
        assert seq[2]["condition"] == "opened_not_replied"


class TestStepToDictFields:
    def test_step_to_dict_includes_execution_fields(self, client, seed_companies_contacts):
        """to_dict() output includes condition, execution_status, started_at, completed_at."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        client.post(
            f"/api/campaigns/{campaign_id}/steps",
            headers=headers,
            json={"channel": "email", "label": "Step 1"},
        )

        resp = client.get(f"/api/campaigns/{campaign_id}/sequence", headers=headers)
        step = resp.get_json()["sequence"][0]

        # All execution fields present
        assert "condition" in step
        assert "execution_status" in step
        assert "started_at" in step
        assert "completed_at" in step

        # Defaults
        assert step["condition"] == "always"
        assert step["execution_status"] == "pending"
        assert step["started_at"] is None
        assert step["completed_at"] is None


class TestSequenceReplace:
    def test_sequence_replace_clears_old_steps(self, client, seed_companies_contacts):
        """PUT /sequence completely replaces existing steps."""
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        # Create initial steps via CRUD
        for label in ["A", "B", "C"]:
            client.post(
                f"/api/campaigns/{campaign_id}/steps",
                headers=headers,
                json={"channel": "email", "label": label},
            )

        # Verify 3 steps exist
        resp = client.get(f"/api/campaigns/{campaign_id}/sequence", headers=headers)
        assert len(resp.get_json()["sequence"]) == 3

        # Replace with 1 step
        resp = client.put(
            f"/api/campaigns/{campaign_id}/sequence",
            headers=headers,
            json={
                "steps": [
                    {"channel": "linkedin_connect", "condition": "always", "label": "Only Step"}
                ]
            },
        )
        assert resp.status_code == 200
        seq = resp.get_json()["sequence"]
        assert len(seq) == 1
        assert seq[0]["label"] == "Only Step"

        # Verify old steps gone
        resp = client.get(f"/api/campaigns/{campaign_id}/steps", headers=headers)
        assert len(resp.get_json()["steps"]) == 1
