"""Unit tests for campaign sequence (execution-focused) endpoints."""

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


def _add_step(client, headers, campaign_id, **kwargs):
    """Add a step and return the response data."""
    payload = {"channel": "email", "day_offset": 0, "label": "Step"}
    payload.update(kwargs)
    resp = client.post(
        f"/api/campaigns/{campaign_id}/steps", headers=headers, json=payload
    )
    assert resp.status_code == 201
    return resp.get_json()


class TestGetSequence:
    def test_get_sequence_returns_execution_info(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        # Add a step via normal CRUD
        _add_step(client, headers, campaign_id, channel="linkedin_connect", label="Connect")

        resp = client.get(f"/api/campaigns/{campaign_id}/sequence", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "sequence" in data
        assert len(data["sequence"]) == 1

        step = data["sequence"][0]
        assert step["channel"] == "linkedin_connect"
        assert step["condition"] == "always"
        assert step["execution_status"] == "pending"
        assert step["started_at"] is None
        assert step["completed_at"] is None


class TestPutSequence:
    def test_put_sequence_replaces_steps(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        # Add an existing step that should be replaced
        _add_step(client, headers, campaign_id, label="Old Step")

        # Replace with new sequence
        resp = client.put(
            f"/api/campaigns/{campaign_id}/sequence",
            headers=headers,
            json={
                "steps": [
                    {
                        "position": 1,
                        "channel": "linkedin_connect",
                        "day_offset": 0,
                        "condition": "always",
                    },
                    {
                        "position": 2,
                        "channel": "email",
                        "day_offset": 3,
                        "condition": "no_response",
                    },
                ]
            },
        )
        assert resp.status_code == 200
        seq = resp.get_json()["sequence"]
        assert len(seq) == 2
        assert seq[0]["channel"] == "linkedin_connect"
        assert seq[0]["condition"] == "always"
        assert seq[0]["execution_status"] == "pending"
        assert seq[1]["channel"] == "email"
        assert seq[1]["condition"] == "no_response"
        assert seq[1]["day_offset"] == 3

        # Verify old step is gone
        resp = client.get(f"/api/campaigns/{campaign_id}/sequence", headers=headers)
        assert len(resp.get_json()["sequence"]) == 2

    def test_put_sequence_empty_rejected(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.put(
            f"/api/campaigns/{campaign_id}/sequence",
            headers=headers,
            json={"steps": []},
        )
        assert resp.status_code == 400


class TestPatchSequenceStep:
    def test_patch_sequence_step_updates_condition(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        _add_step(client, headers, campaign_id, channel="email", label="Step 1")

        resp = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/1",
            headers=headers,
            json={"condition": "no_response", "execution_status": "active"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["condition"] == "no_response"
        assert data["execution_status"] == "active"

    def test_patch_sequence_step_not_found(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        resp = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/99",
            headers=headers,
            json={"condition": "no_response"},
        )
        assert resp.status_code == 404

    def test_patch_sequence_step_updates_timestamps(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        _add_step(client, headers, campaign_id, channel="email", label="Step 1")

        resp = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/1",
            headers=headers,
            json={
                "execution_status": "active",
                "started_at": "2026-03-12T10:00:00+00:00",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["execution_status"] == "active"
        assert data["started_at"] is not None

    def test_patch_no_valid_fields(self, client, seed_companies_contacts):
        headers = _headers(client)
        campaign_id = _create_campaign(client, headers)

        _add_step(client, headers, campaign_id, channel="email", label="Step 1")

        resp = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/1",
            headers=headers,
            json={"label": "new label"},  # label is not an allowed field here
        )
        assert resp.status_code == 400
