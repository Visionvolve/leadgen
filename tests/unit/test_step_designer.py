"""Unit tests for api/services/step_designer.py — AI step designer service."""

import json
from unittest.mock import MagicMock, patch

from api.services.step_designer import design_steps


def _mock_anthropic_response(text):
    """Build a mock Anthropic messages.create() response."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


class TestDesignSteps:
    @patch("api.services.step_designer.anthropic")
    def test_design_steps_calls_anthropic(self, mock_anthropic_mod):
        """design_steps() calls Anthropic and returns parsed JSON with steps + reasoning."""
        payload = {
            "steps": [
                {
                    "channel": "linkedin_connect",
                    "day_offset": 0,
                    "label": "Connect",
                    "config": {"max_length": 300, "tone": "informal"},
                },
                {
                    "channel": "email",
                    "day_offset": 5,
                    "label": "Follow-up email",
                    "config": {"max_length": 1000, "tone": "formal"},
                },
            ],
            "reasoning": "Start with LinkedIn, then email follow-up",
        }
        mock_client = _mock_anthropic_response(json.dumps(payload))
        mock_anthropic_mod.Anthropic.return_value = mock_client

        result = design_steps(goal="Reach SaaS CTOs")

        assert result["steps"] == payload["steps"]
        assert result["reasoning"] == payload["reasoning"]
        assert len(result["steps"]) == 2

        # Verify Anthropic was called
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-3-5-20241022"
        assert "SaaS CTOs" in call_kwargs["messages"][0]["content"]

    @patch("api.services.step_designer.anthropic")
    def test_design_steps_with_all_params(self, mock_anthropic_mod):
        """All optional params (channel_preference, num_steps, campaign_context,
        feedback_context) are included in the prompt sent to Anthropic."""
        payload = {
            "steps": [
                {"channel": "email", "day_offset": 0, "label": "Email", "config": {}}
            ],
            "reasoning": "Email only",
        }
        mock_client = _mock_anthropic_response(json.dumps(payload))
        mock_anthropic_mod.Anthropic.return_value = mock_client

        result = design_steps(
            goal="Book demos",
            channel_preference="email",
            num_steps=3,
            campaign_context={
                "contact_count": 50,
                "industries": ["software_saas", "fintech"],
                "seniority_levels": ["c_level", "vp"],
            },
            feedback_context="Previous emails were too long",
        )

        assert result["steps"] is not None

        prompt_text = mock_client.messages.create.call_args[1]["messages"][0]["content"]
        assert "email" in prompt_text.lower()
        assert "3" in prompt_text
        assert "50 contacts" in prompt_text
        assert "software_saas" in prompt_text
        assert "c_level" in prompt_text
        assert "Previous emails were too long" in prompt_text

    @patch("api.services.step_designer.anthropic")
    def test_design_steps_handles_markdown_json(self, mock_anthropic_mod):
        """Response wrapped in ```json ... ``` is parsed correctly."""
        payload = {
            "steps": [
                {
                    "channel": "linkedin_message",
                    "day_offset": 0,
                    "label": "DM",
                    "config": {"max_length": 500, "tone": "informal"},
                }
            ],
            "reasoning": "Direct message approach",
        }
        raw_text = f"Here is the design:\n```json\n{json.dumps(payload)}\n```\nHope this helps!"
        mock_client = _mock_anthropic_response(raw_text)
        mock_anthropic_mod.Anthropic.return_value = mock_client

        result = design_steps(goal="LinkedIn outreach")

        assert len(result["steps"]) == 1
        assert result["steps"][0]["channel"] == "linkedin_message"
        assert result["reasoning"] == "Direct message approach"

    @patch("api.services.step_designer.anthropic")
    def test_design_steps_handles_bare_code_block(self, mock_anthropic_mod):
        """Response wrapped in ``` ... ``` (no json tag) is parsed correctly."""
        payload = {
            "steps": [
                {
                    "channel": "call",
                    "day_offset": 0,
                    "label": "Call",
                    "config": {"max_length": 2000, "tone": "formal"},
                }
            ],
            "reasoning": "Phone first",
        }
        raw_text = f"```\n{json.dumps(payload)}\n```"
        mock_client = _mock_anthropic_response(raw_text)
        mock_anthropic_mod.Anthropic.return_value = mock_client

        result = design_steps(goal="Phone outreach")
        assert result["steps"][0]["channel"] == "call"
