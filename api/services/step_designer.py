"""AI-powered campaign step designer."""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import anthropic

log = logging.getLogger(__name__)

MODEL = "claude-haiku-3-5-20241022"

DESIGNER_SYSTEM_PROMPT = """You are an expert B2B outreach strategist. Design a multi-step outreach sequence for a campaign.

For each step, specify:
- channel: one of "linkedin_connect", "linkedin_message", "email", "call"
- day_offset: days after the previous step (0 for the first step)
- label: a short descriptive name for the step
- config: object with max_length (int), tone ("formal" or "informal"), and optionally custom_instructions (string)

Return ONLY a JSON object with this exact structure:
{
  "steps": [
    {
      "channel": "linkedin_connect",
      "day_offset": 0,
      "label": "Connection request",
      "config": {"max_length": 300, "tone": "informal", "custom_instructions": ""}
    }
  ],
  "reasoning": "Brief explanation of the sequence strategy"
}

Channel constraints:
- linkedin_connect: max 300 chars, no subject, personal note only
- linkedin_message: max 1900 chars, no subject
- email: no hard limit, has subject line
- call: talking points script, 2000 chars max

Design sequences that are respectful, value-driven, and avoid being pushy. Space steps appropriately (2-5 days between LinkedIn steps, 5-7 for email follow-ups)."""


def design_steps(
    *,
    goal: str,
    channel_preference: Optional[str] = None,
    num_steps: Optional[int] = None,
    campaign_context: Optional[dict] = None,
    feedback_context: Optional[str] = None,
) -> dict:
    """Call Claude to design campaign steps.

    Returns: {"steps": [...], "reasoning": "..."}
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    user_prompt = f"Design an outreach sequence for this goal: {goal}"
    if channel_preference:
        user_prompt += f"\nPreferred channel: {channel_preference}"
    if num_steps:
        user_prompt += f"\nNumber of steps: {num_steps}"
    if campaign_context:
        if campaign_context.get("contact_count"):
            user_prompt += (
                f"\nTarget audience: {campaign_context['contact_count']} contacts"
            )
        if campaign_context.get("industries"):
            user_prompt += (
                f"\nIndustries: {', '.join(campaign_context['industries'][:5])}"
            )
        if campaign_context.get("seniority_levels"):
            user_prompt += (
                f"\nSeniority: {', '.join(campaign_context['seniority_levels'][:5])}"
            )
    if feedback_context:
        user_prompt += f"\n\nLearning from previous campaigns:\n{feedback_context}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=DESIGNER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text
    # Parse JSON from response (handle markdown code blocks)
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    result = json.loads(text.strip())
    return result
