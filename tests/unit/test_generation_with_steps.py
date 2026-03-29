"""Unit tests for generation reading from campaign_steps (Task 4 + Task 6).

Tests cover:
- Cost estimation prefers campaign_steps over template_config
- Example messages from step config are included in prompt
- Max length from step config is included in prompt
- Auto-migration of template_config to campaign_steps on generation start
"""

from api.services.generation_prompts import build_generation_prompt


class TestAutoMigrateTemplateConfigToSteps:
    def test_auto_migrate_template_config_to_steps(
        self, client, seed_companies_contacts, db
    ):
        """When generation starts and campaign has template_config but no steps,
        auto-create steps from enabled template entries."""
        from tests.conftest import auth_header

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        # Create campaign
        resp = client.post(
            "/api/campaigns",
            headers=headers,
            json={"name": "Legacy Campaign", "channel": "linkedin_message"},
        )
        assert resp.status_code == 201, resp.get_json()
        cid = resp.get_json()["id"]

        # Set template_config via PATCH (legacy way)
        tpl_config = [
            {
                "step": 1,
                "channel": "linkedin_connect",
                "day_offset": 0,
                "label": "Connect",
                "enabled": True,
            },
            {
                "step": 2,
                "channel": "email",
                "day_offset": 5,
                "label": "Email",
                "enabled": True,
                "max_length": 500,
            },
            {
                "step": 3,
                "channel": "call",
                "day_offset": 10,
                "label": "Call",
                "enabled": False,
            },
        ]
        client.patch(
            f"/api/campaigns/{cid}",
            headers=headers,
            json={"template_config": tpl_config},
        )

        # Verify no steps exist yet
        steps_resp = client.get(f"/api/campaigns/{cid}/steps", headers=headers)
        assert steps_resp.status_code == 200
        assert len(steps_resp.get_json()["steps"]) == 0

        # Transition campaign to 'ready' so generate accepts it
        patch_resp = client.patch(
            f"/api/campaigns/{cid}",
            headers=headers,
            json={"status": "ready"},
        )
        assert patch_resp.status_code == 200, f"PATCH failed: {patch_resp.get_json()}"

        # Start generation — will fail (no contacts) but auto-migration runs first
        client.post(
            f"/api/campaigns/{cid}/generate",
            headers=headers,
            json={},
        )

        # Check steps were auto-created from enabled template entries only
        steps_resp = client.get(f"/api/campaigns/{cid}/steps", headers=headers)
        steps = steps_resp.get_json()["steps"]
        assert len(steps) == 2  # Only enabled steps (step 3 disabled)
        assert steps[0]["channel"] == "linkedin_connect"
        assert steps[0]["label"] == "Connect"
        assert steps[0]["position"] == 1
        assert steps[0]["day_offset"] == 0
        assert steps[1]["channel"] == "email"
        assert steps[1]["label"] == "Email"
        assert steps[1]["position"] == 2
        assert steps[1]["day_offset"] == 5
        # max_length should be in config (extra fields go there)
        assert steps[1]["config"].get("max_length") == 500

    def test_no_migration_when_steps_already_exist(
        self, client, seed_companies_contacts, db
    ):
        """When campaign_steps already exist, auto-migration should be skipped."""
        from api.models import CampaignStep
        from tests.conftest import auth_header

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        tenant_id = seed_companies_contacts["tenant"].id

        # Create campaign and set template_config via PATCH
        resp = client.post(
            "/api/campaigns",
            headers=headers,
            json={"name": "Already Has Steps"},
        )
        assert resp.status_code == 201, resp.get_json()
        cid = resp.get_json()["id"]
        client.patch(
            f"/api/campaigns/{cid}",
            headers=headers,
            json={
                "template_config": [
                    {
                        "step": 1,
                        "channel": "email",
                        "day_offset": 0,
                        "label": "Email",
                        "enabled": True,
                    },
                    {
                        "step": 2,
                        "channel": "call",
                        "day_offset": 3,
                        "label": "Call",
                        "enabled": True,
                    },
                ],
            },
        )

        # Manually add one step (simulating steps already created)
        manual_step = CampaignStep(
            campaign_id=cid,
            tenant_id=tenant_id,
            position=1,
            channel="linkedin_message",
            label="Manual Step",
            day_offset=0,
            config={},
        )
        db.session.add(manual_step)
        db.session.commit()

        # Transition to ready
        client.patch(
            f"/api/campaigns/{cid}",
            headers=headers,
            json={"status": "ready"},
        )

        # Start generation
        client.post(
            f"/api/campaigns/{cid}/generate",
            headers=headers,
            json={},
        )

        # Steps should still be just the manual one (no migration)
        steps_resp = client.get(f"/api/campaigns/{cid}/steps", headers=headers)
        steps = steps_resp.get_json()["steps"]
        assert len(steps) == 1
        assert steps[0]["channel"] == "linkedin_message"
        assert steps[0]["label"] == "Manual Step"


class TestCostEstimateWithCampaignSteps:
    def test_cost_estimate_uses_campaign_steps(
        self, client, seed_companies_contacts, db
    ):
        """When campaign_steps exist, cost estimate should use them."""
        from api.models import CampaignStep
        from api.services.message_generator import estimate_generation_cost
        from tests.conftest import auth_header

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        # Create a campaign with legacy template_config (1 enabled step)
        resp = client.post(
            "/api/campaigns", headers=headers, json={"name": "Steps Test"}
        )
        cid = resp.get_json()["id"]
        client.patch(
            f"/api/campaigns/{cid}",
            headers=headers,
            json={
                "template_config": [
                    {"step": 1, "channel": "email", "label": "Legacy", "enabled": True},
                ]
            },
        )

        # Add campaign_steps (2 steps) — these should take priority
        tenant_id = seed_companies_contacts["tenant"].id
        step1 = CampaignStep(
            campaign_id=cid,
            tenant_id=tenant_id,
            position=1,
            channel="linkedin_connect",
            label="LI Invite",
            day_offset=0,
            config={},
        )
        step2 = CampaignStep(
            campaign_id=cid,
            tenant_id=tenant_id,
            position=2,
            channel="email",
            label="Follow-up Email",
            day_offset=3,
            config={"max_length": 500},
        )
        db.session.add_all([step1, step2])
        db.session.commit()

        # Cost estimate with campaign_id should find 2 steps (not 1 from legacy)
        result = estimate_generation_cost(
            template_config=[
                {"step": 1, "channel": "email", "label": "Legacy", "enabled": True},
            ],
            total_contacts=5,
            campaign_id=cid,
        )

        assert result["enabled_steps"] == 2
        assert result["total_messages"] == 10  # 5 contacts * 2 steps
        assert len(result["by_step"]) == 2
        assert result["by_step"][0]["channel"] == "linkedin_connect"
        assert result["by_step"][1]["channel"] == "email"

    def test_cost_estimate_falls_back_to_template_config(self):
        """Without campaign_id, falls back to template_config."""
        from api.services.message_generator import estimate_generation_cost

        template = [
            {"step": 1, "channel": "email", "label": "Email 1", "enabled": True},
            {"step": 2, "channel": "email", "label": "Email 2", "enabled": False},
        ]
        result = estimate_generation_cost(template, 3)

        assert result["enabled_steps"] == 1
        assert result["total_messages"] == 3


class TestBuildPromptWithExamplesAndMaxLength:
    def test_example_messages_in_prompt(self):
        """Example messages from step config should appear in the prompt."""
        examples = [
            {
                "body": "Hey {{first_name}}, loved your talk on AI.",
                "note": "Casual opener",
            },
            {"body": "Hi {{first_name}}, noticed your team is hiring ML engineers."},
        ]

        prompt = build_generation_prompt(
            channel="linkedin_message",
            step_label="LI Message",
            contact_data={"first_name": "Jane"},
            company_data={"name": "Acme"},
            enrichment_data={},
            generation_config={},
            step_number=1,
            total_steps=2,
            example_messages=examples,
        )

        assert "REFERENCE EXAMPLES" in prompt
        assert "loved your talk on AI" in prompt
        assert "(Note: Casual opener)" in prompt
        assert "hiring ML engineers" in prompt

    def test_max_length_in_prompt(self):
        """Max length from step config should appear in the prompt."""
        prompt = build_generation_prompt(
            channel="email",
            step_label="Email 1",
            contact_data={"first_name": "Jane"},
            company_data={"name": "Acme"},
            enrichment_data={},
            generation_config={},
            step_number=1,
            total_steps=1,
            max_length=300,
        )

        assert "LENGTH LIMIT" in prompt
        assert "Maximum 300 characters" in prompt

    def test_reference_assets_in_prompt(self):
        """Reference asset summaries should appear in the prompt."""
        prompt = build_generation_prompt(
            channel="email",
            step_label="Follow-up",
            contact_data={"first_name": "John", "last_name": "Doe"},
            company_data={"name": "Acme"},
            enrichment_data={},
            generation_config={},
            step_number=1,
            total_steps=2,
            reference_assets=[
                {
                    "filename": "case-study.pdf",
                    "content_type": "application/pdf",
                    "summary": "AI consulting saved 40% costs for FinCorp",
                },
            ],
        )
        assert "REFERENCE MATERIALS" in prompt
        assert "case-study.pdf" in prompt
        assert "AI consulting saved 40% costs" in prompt

    def test_no_reference_assets_when_absent(self):
        """When reference_assets is None, section should be absent."""
        prompt = build_generation_prompt(
            channel="email",
            step_label="Email 1",
            contact_data={"first_name": "Jane"},
            company_data={"name": "Acme"},
            enrichment_data={},
            generation_config={},
            step_number=1,
            total_steps=1,
        )
        assert "REFERENCE MATERIALS" not in prompt

    def test_no_examples_no_max_length_when_absent(self):
        """When example_messages and max_length are not set, sections are absent."""
        prompt = build_generation_prompt(
            channel="email",
            step_label="Email 1",
            contact_data={"first_name": "Jane"},
            company_data={"name": "Acme"},
            enrichment_data={},
            generation_config={},
            step_number=1,
            total_steps=1,
        )

        assert "REFERENCE EXAMPLES" not in prompt
        assert "LENGTH LIMIT" not in prompt
