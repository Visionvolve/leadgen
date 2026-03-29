"""Message generation engine for campaigns.

Generates personalized outreach messages for each contact in a campaign
using Claude API. Runs as a background thread with progress tracking.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from decimal import Decimal

from ..models import Asset, CampaignStep, Message, MessageFeedback, db
from .generation_prompts import (
    SYSTEM_PROMPT,
    build_generation_prompt,
    CHANNEL_CONSTRAINTS,
)
from .llm_logger import log_llm_usage, compute_cost

logger = logging.getLogger(__name__)

# Generation model config
GENERATION_MODEL = "claude-haiku-3-5-20241022"
GENERATION_PROVIDER = "anthropic"

# Estimated tokens per message (for cost estimation)
EST_INPUT_TOKENS = 800
EST_OUTPUT_TOKENS = 200

# BL-181: A/B variant angles for multi-variant generation
VARIANT_ANGLES = [
    {
        "key": "pain",
        "label": "Pain-focused",
        "instruction": "Focus on a specific pain point or challenge the prospect likely faces. "
        "Lead with the problem, then position the solution.",
    },
    {
        "key": "opportunity",
        "label": "Opportunity-focused",
        "instruction": "Focus on a growth opportunity or competitive advantage the prospect could gain. "
        "Lead with the upside potential, not the problem.",
    },
    {
        "key": "social_proof",
        "label": "Social proof",
        "instruction": "Lead with credibility — mention relevant case studies, industry recognition, "
        "or similar companies that benefited. Focus on trust and validation.",
    },
]

VARIANT_LETTERS = ["A", "B", "C"]


def _parse_step_config(config) -> dict:
    """Safely parse a CampaignStep.config value to a dict.

    Handles JSONB (already a dict), JSON strings (SQLite compat), and None.
    """
    if isinstance(config, dict):
        return config
    if isinstance(config, str):
        try:
            parsed = json.loads(config)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def estimate_generation_cost(
    template_config: list,
    total_contacts: int,
    variant_count: int = 1,
    campaign_id: str | None = None,
    tenant_id: str | None = None,
) -> dict:
    """Estimate the cost of generating messages for a campaign.

    Returns dict with total_cost, per_contact_cost, total_messages, and breakdown.

    Args:
        variant_count: Number of A/B variants per message (1-3). Default 1.
        campaign_id: Optional campaign ID to check for campaign_steps.
        tenant_id: Optional tenant ID for tenant-scoped queries.
    """
    variant_count = max(1, min(int(variant_count), 3))

    # Prefer campaign_steps over legacy template_config
    if campaign_id:
        step_filter = {"campaign_id": campaign_id}
        if tenant_id:
            step_filter["tenant_id"] = str(tenant_id)
        campaign_steps = (
            CampaignStep.query.filter_by(**step_filter)
            .order_by(CampaignStep.position)
            .all()
        )
    else:
        campaign_steps = []

    if campaign_steps:
        enabled_steps = [
            {
                "step": s.position,
                "channel": s.channel,
                "label": s.label,
                "enabled": True,
                "day_offset": s.day_offset,
                "campaign_step_id": s.id,
                **_parse_step_config(s.config),
            }
            for s in campaign_steps
        ]
    else:
        enabled_steps = [s for s in template_config if s.get("enabled")]
    total_messages = len(enabled_steps) * total_contacts * variant_count

    per_message_cost = compute_cost(
        GENERATION_PROVIDER,
        GENERATION_MODEL,
        EST_INPUT_TOKENS,
        EST_OUTPUT_TOKENS,
    )
    total_cost = per_message_cost * total_messages
    per_contact_cost = per_message_cost * len(enabled_steps) * variant_count

    step_breakdown = [
        {
            "step": s.get("step"),
            "label": s.get("label"),
            "channel": s.get("channel"),
            "count": total_contacts * variant_count,
            "cost": float(per_message_cost * total_contacts * variant_count),
        }
        for s in enabled_steps
    ]

    return {
        "total_cost": float(total_cost),
        "estimated_cost": float(total_cost),
        "per_contact_cost": float(per_contact_cost),
        "total_messages": total_messages,
        "enabled_steps": len(enabled_steps),
        "total_contacts": total_contacts,
        "variant_count": variant_count,
        "model": GENERATION_MODEL,
        "breakdown": step_breakdown,
        "by_step": step_breakdown,
    }


def start_generation(app, campaign_id: str, tenant_id: str, user_id: str = None):
    """Start message generation in a background thread.

    Args:
        app: Flask app instance (for application context)
        campaign_id: UUID of the campaign
        tenant_id: UUID of the tenant
        user_id: optional UUID of the user who triggered generation
    """
    thread = threading.Thread(
        target=_run_generation,
        args=(app, campaign_id, tenant_id, user_id),
        daemon=True,
    )
    thread.start()
    return thread


def _run_generation(app, campaign_id: str, tenant_id: str, user_id: str):
    """Background thread: generate messages for all contacts in campaign."""
    with app.app_context():
        try:
            _generate_all(campaign_id, tenant_id, user_id)
        except Exception:
            logger.exception("Generation failed for campaign %s", campaign_id)
            # Mark campaign as review (partial results available)
            try:
                db.session.execute(
                    db.text("UPDATE campaigns SET status = 'review' WHERE id = :id"),
                    {"id": campaign_id},
                )
                db.session.commit()
            except Exception:
                logger.exception("Failed to update campaign status after error")


def _load_strategy_data(tenant_id: str) -> dict | None:
    """Load the tenant's playbook strategy extracted_data and content.

    Returns the extracted_data dict (with an extra 'strategy_content' key
    containing relevant sections from the strategy document) or None if no
    playbook exists.
    """
    row = db.session.execute(
        db.text("""
            SELECT extracted_data, content
            FROM strategy_documents
            WHERE tenant_id = :t
            ORDER BY updated_at DESC
            LIMIT 1
        """),
        {"t": tenant_id},
    ).fetchone()

    if not row or (not row[0] and not row[1]):
        return None

    data = row[0]
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            data = {}

    if not data:
        data = {}

    # Attach relevant sections from the strategy document content
    strategy_content = row[1] if row[1] else ""
    if strategy_content:
        # Extract messaging-relevant sections (truncate to avoid prompt bloat)
        relevant = _extract_messaging_sections(strategy_content)
        if relevant:
            data["strategy_content"] = relevant

    # Only return if there's meaningful content
    if not any(data.values()):
        return None

    return data


def _extract_messaging_sections(content: str, max_chars: int = 2000) -> str:
    """Extract messaging-relevant sections from strategy document markdown.

    Looks for sections on value proposition, messaging, competitive positioning,
    and channel strategy. Returns a concatenation of those sections, truncated
    to max_chars for prompt efficiency.
    """
    import re

    # Section headers that contain messaging-relevant content
    RELEVANT_KEYWORDS = [
        "value proposition",
        "messaging",
        "competitive",
        "positioning",
        "channel strategy",
        "buyer persona",
        "pain point",
        "proof point",
        "tone",
        "outreach",
        "90-day",
        "action plan",
    ]

    # Split into sections by markdown headings
    sections = re.split(r"(?m)^(#{1,3}\s+.+)$", content)
    relevant_parts = []

    for i, section in enumerate(sections):
        # Check if this is a heading that matches our keywords
        header_match = re.match(r"^#{1,3}\s+(.+)$", section.strip())
        if header_match:
            header_text = header_match.group(1).lower()
            if any(kw in header_text for kw in RELEVANT_KEYWORDS):
                # Include this heading and the next section (body)
                body = sections[i + 1].strip() if i + 1 < len(sections) else ""
                if body:
                    relevant_parts.append(f"{section.strip()}\n{body}")

    result = "\n\n".join(relevant_parts)

    # Truncate to avoid prompt bloat
    if len(result) > max_chars:
        result = result[:max_chars] + "..."

    return result


def _load_feedback_signals(
    campaign_id: str, step_channel: str, campaign_step_id: str | None = None
) -> dict | None:
    """Load learning signals from previous feedback for a campaign step.

    Collects approved message bodies as positive examples, top edit reasons
    as correction guidance, and rejected message bodies as negative examples.
    Prefers feedback from the same campaign_step, falls back to same channel.

    Returns a dict with approved_examples, common_edits, rejected_patterns
    or None if no feedback exists.
    """
    # Get feedback entries for this campaign
    feedbacks = (
        MessageFeedback.query.filter_by(campaign_id=campaign_id)
        .order_by(MessageFeedback.created_at.desc())
        .all()
    )
    if not feedbacks:
        return None

    # Collect message bodies by action, preferring same step then same channel
    approved_bodies = []
    rejected_bodies = []
    edit_reasons: dict[str, int] = {}

    for f in feedbacks:
        msg = db.session.get(Message, f.message_id)
        if not msg:
            continue

        # Check if this feedback is from the same step or same channel
        same_step = campaign_step_id and msg.campaign_step_id == campaign_step_id
        same_channel = msg.channel == step_channel

        if not (same_step or same_channel):
            continue

        if f.action == "approved" and msg.body:
            # Prioritize same-step matches
            priority = 0 if same_step else 1
            approved_bodies.append((priority, msg.body))
        elif f.action == "rejected" and msg.body:
            priority = 0 if same_step else 1
            rejected_bodies.append((priority, msg.body))

        if f.edit_reason:
            edit_reasons[f.edit_reason] = edit_reasons.get(f.edit_reason, 0) + 1

    # Sort by priority (same-step first) and take top N
    approved_bodies.sort(key=lambda x: x[0])
    rejected_bodies.sort(key=lambda x: x[0])

    approved_examples = [body for _, body in approved_bodies[:3]]
    rejected_patterns = [body for _, body in rejected_bodies[:2]]
    common_edits = sorted(edit_reasons.items(), key=lambda x: -x[1])[:3]

    if not approved_examples and not rejected_patterns and not common_edits:
        return None

    signals: dict = {}
    if approved_examples:
        signals["approved_examples"] = approved_examples
    if common_edits:
        signals["common_edits"] = common_edits
    if rejected_patterns:
        signals["rejected_patterns"] = rejected_patterns
    return signals


def _generate_all(campaign_id: str, tenant_id: str, user_id: str):
    """Core generation loop: iterate contacts × steps."""
    # Load campaign config
    campaign = db.session.execute(
        db.text("""
            SELECT template_config, generation_config, owner_id
            FROM campaigns WHERE id = :id AND tenant_id = :t
        """),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not campaign:
        logger.error("Campaign %s not found", campaign_id)
        return

    template_config = (
        json.loads(campaign[0]) if isinstance(campaign[0], str) else (campaign[0] or [])
    )
    generation_config = (
        json.loads(campaign[1]) if isinstance(campaign[1], str) else (campaign[1] or {})
    )
    owner_id = campaign[2]

    # Prefer campaign_steps over legacy template_config
    campaign_steps = (
        CampaignStep.query.filter_by(campaign_id=campaign_id, tenant_id=str(tenant_id))
        .order_by(CampaignStep.position)
        .all()
    )

    if campaign_steps:
        enabled_steps = [
            {
                "step": s.position,
                "channel": s.channel,
                "label": s.label,
                "enabled": True,
                "day_offset": s.day_offset,
                "campaign_step_id": s.id,
                **_parse_step_config(s.config),
            }
            for s in campaign_steps
        ]
    else:
        # Fallback to legacy template_config
        enabled_steps = [s for s in template_config if s.get("enabled")]

    if not enabled_steps:
        logger.warning("No enabled steps for campaign %s", campaign_id)
        db.session.execute(
            db.text("UPDATE campaigns SET status = 'review' WHERE id = :id"),
            {"id": campaign_id},
        )
        db.session.commit()
        return

    total_steps = len(enabled_steps)

    # Load playbook strategy data and snapshot it in generation_config
    strategy_data = _load_strategy_data(tenant_id)
    if strategy_data:
        generation_config["strategy_snapshot"] = strategy_data
        db.session.execute(
            db.text("""
                UPDATE campaigns
                SET generation_config = :gc
                WHERE id = :id
            """),
            {"gc": json.dumps(generation_config), "id": campaign_id},
        )
        db.session.commit()

    # Load contacts
    contacts = db.session.execute(
        db.text("""
            SELECT
                cc.id AS cc_id, cc.contact_id,
                ct.first_name, ct.last_name, ct.job_title,
                ct.email_address, ct.linkedin_url,
                ct.seniority_level, ct.department,
                ct.company_id
            FROM campaign_contacts cc
            JOIN contacts ct ON cc.contact_id = ct.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                AND cc.status NOT IN ('excluded', 'generated', 'failed')
            ORDER BY ct.contact_score DESC NULLS LAST
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    total_contacts = len(contacts)
    generated_count = 0
    total_cost = Decimal("0")

    for i, contact_row in enumerate(contacts):
        # Check for cancellation before each contact
        cancel_row = db.session.execute(
            db.text("SELECT generation_config FROM campaigns WHERE id = :id"),
            {"id": campaign_id},
        ).fetchone()
        if cancel_row:
            cancel_config = (
                json.loads(cancel_row[0])
                if isinstance(cancel_row[0], str)
                else (cancel_row[0] or {})
            )
            if cancel_config.get("cancelled"):
                logger.info(
                    "Generation cancelled for campaign %s after %d contacts",
                    campaign_id,
                    generated_count,
                )
                return

        cc_id = contact_row[0]
        contact_id = str(contact_row[1])

        try:
            # Mark contact as generating
            db.session.execute(
                db.text(
                    "UPDATE campaign_contacts SET status = 'generating' WHERE id = :id"
                ),
                {"id": cc_id},
            )
            db.session.commit()

            # Load enrichment data
            contact_data = {
                "first_name": contact_row[2],
                "last_name": contact_row[3],
                "job_title": contact_row[4],
                "email_address": contact_row[5],
                "linkedin_url": contact_row[6],
                "seniority_level": contact_row[7],
                "department": contact_row[8],
            }
            company_id = str(contact_row[9]) if contact_row[9] else None
            company_data, enrichment_data = _load_enrichment_context(
                contact_id, company_id
            )

            # BL-181: variant_count from generation_config (default 1, max 3)
            variant_count = min(int(generation_config.get("variant_count", 1)), 3)

            # Generate each enabled step
            contact_cost = Decimal("0")
            for step in enabled_steps:
                # Load feedback signals for this step (once per step per contact batch)
                step_feedback = _load_feedback_signals(
                    campaign_id,
                    step["channel"],
                    step.get("campaign_step_id"),
                )

                # Generate variant A (always — default/no angle)
                vg_id = str(uuid.uuid4()) if variant_count > 1 else None
                msg_cost = _generate_single_message(
                    campaign_id=campaign_id,
                    tenant_id=tenant_id,
                    cc_id=cc_id,
                    contact_id=contact_id,
                    owner_id=owner_id,
                    contact_data=contact_data,
                    company_data=company_data,
                    enrichment_data=enrichment_data,
                    generation_config=generation_config,
                    step=step,
                    total_steps=total_steps,
                    user_id=user_id,
                    strategy_data=strategy_data,
                    variant_letter="a",
                    variant_group_id=vg_id,
                    feedback_signals=step_feedback,
                )
                contact_cost += msg_cost

                # Generate additional variants B, C with different angles
                for vi in range(1, variant_count):
                    angle = (
                        VARIANT_ANGLES[vi - 1] if vi - 1 < len(VARIANT_ANGLES) else None
                    )
                    letter = (
                        VARIANT_LETTERS[vi].lower()
                        if vi < len(VARIANT_LETTERS)
                        else chr(ord("a") + vi)
                    )
                    msg_cost = _generate_single_message(
                        campaign_id=campaign_id,
                        tenant_id=tenant_id,
                        cc_id=cc_id,
                        contact_id=contact_id,
                        owner_id=owner_id,
                        contact_data=contact_data,
                        company_data=company_data,
                        enrichment_data=enrichment_data,
                        generation_config=generation_config,
                        step=step,
                        total_steps=total_steps,
                        user_id=user_id,
                        strategy_data=strategy_data,
                        variant_letter=letter,
                        variant_group_id=vg_id,
                        variant_angle=angle,
                        feedback_signals=step_feedback,
                    )
                    contact_cost += msg_cost

            # Mark contact as generated
            db.session.execute(
                db.text("""
                    UPDATE campaign_contacts
                    SET status = 'generated', generation_cost = :cost, generated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {"cost": float(contact_cost), "id": cc_id},
            )
            generated_count += 1
            total_cost += contact_cost

        except Exception:
            logger.exception(
                "Generation failed for contact %s in campaign %s",
                contact_id,
                campaign_id,
            )
            db.session.rollback()
            db.session.execute(
                db.text("""
                    UPDATE campaign_contacts
                    SET status = 'failed', error = 'Generation error'
                    WHERE id = :id
                """),
                {"id": cc_id},
            )

        # Update campaign progress
        db.session.execute(
            db.text("""
                UPDATE campaigns
                SET generated_count = :gc, generation_cost = :cost
                WHERE id = :id
            """),
            {"gc": generated_count, "cost": float(total_cost), "id": campaign_id},
        )
        db.session.commit()

        # Small delay between contacts to avoid rate limits
        if i < total_contacts - 1:
            time.sleep(0.5)

    # Mark campaign as review
    db.session.execute(
        db.text("""
            UPDATE campaigns
            SET status = 'review', generation_completed_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """),
        {"id": campaign_id},
    )
    db.session.commit()

    logger.info(
        "Generation complete: campaign=%s contacts=%d messages=%d cost=$%.4f",
        campaign_id,
        generated_count,
        generated_count * total_steps,
        float(total_cost),
    )


def _load_enrichment_context(contact_id: str, company_id: str) -> tuple[dict, dict]:
    """Load company and enrichment data for a contact.

    BL-173: Enhanced to include company_size, verified_employees,
    verified_revenue, and richer L2/person fields for grounded
    message personalization.
    """
    company_data = {}
    enrichment_data = {"l2": {}, "person": {}}

    if company_id:
        row = db.session.execute(
            db.text("""
                SELECT name, domain, industry, hq_country, summary,
                       company_size, verified_employees, verified_revenue_eur_m,
                       tier, business_model
                FROM companies WHERE id = :id
            """),
            {"id": company_id},
        ).fetchone()
        if row:
            company_data = {
                "name": row[0],
                "domain": row[1],
                "industry": row[2],
                "hq_country": row[3],
                "summary": row[4],
                "company_size": row[5],
                "employee_count": str(int(row[6])) if row[6] else None,
                "revenue_eur_m": str(round(float(row[7]), 1)) if row[7] else None,
                "tier": row[8],
                "business_model": row[9],
            }

        # BL-173: Load full L2 enrichment for grounded personalization
        l2_row = db.session.execute(
            db.text("""
                SELECT company_intel, recent_news, ai_opportunities,
                       pain_hypothesis, key_products, customer_segments,
                       competitors, tech_stack, hiring_signals,
                       digital_initiatives, pitch_framing, growth_signals,
                       expansion, ma_activity
                FROM company_enrichment_l2 WHERE company_id = :id
            """),
            {"id": company_id},
        ).fetchone()
        if l2_row:
            enrichment_data["l2"] = {
                "company_intel": l2_row[0],
                "recent_news": l2_row[1],
                "ai_opportunities": l2_row[2],
                "pain_hypothesis": l2_row[3],
                "key_products": l2_row[4],
                "customer_segments": l2_row[5],
                "competitors": l2_row[6],
                "tech_stack": l2_row[7],
                "hiring_signals": l2_row[8],
                "digital_initiatives": l2_row[9],
                "pitch_framing": l2_row[10],
                "growth_signals": l2_row[11],
                "expansion": l2_row[12],
                "ma_activity": l2_row[13],
            }

    # BL-173: Load richer person enrichment for grounded personalization
    person_row = db.session.execute(
        db.text("""
            SELECT person_summary, relationship_synthesis,
                   career_trajectory, speaking_engagements, publications,
                   ai_champion_score, authority_score
            FROM contact_enrichment WHERE contact_id = :id
        """),
        {"id": contact_id},
    ).fetchone()
    if person_row:
        enrichment_data["person"] = {
            "person_summary": person_row[0],
            "relationship_synthesis": person_row[1],
            "career_trajectory": person_row[2],
            "speaking_engagements": person_row[3],
            "publications": person_row[4],
            "ai_champion_score": person_row[5],
            "authority_score": person_row[6],
        }

    return company_data, enrichment_data


def _generate_single_message(
    *,
    campaign_id: str,
    tenant_id: str,
    cc_id: str,
    contact_id: str,
    owner_id: str,
    contact_data: dict,
    company_data: dict,
    enrichment_data: dict,
    generation_config: dict,
    step: dict,
    total_steps: int,
    user_id: str,
    strategy_data: dict | None = None,
    variant_letter: str = "a",
    variant_group_id: str | None = None,
    variant_angle: dict | None = None,
    feedback_signals: dict | None = None,
) -> Decimal:
    """Generate a single message for one contact x one step.

    Calls Claude API, parses response, saves Message, logs cost.
    Returns the cost of this generation call.

    Args:
        variant_letter: The variant label (a, b, c).
        variant_group_id: UUID linking variants of the same step/contact.
        variant_angle: Optional angle dict with 'key', 'label', 'instruction'.
        feedback_signals: Optional learning signals from previous feedback.
    """
    # Build per-message instruction from variant angle
    angle_instruction = variant_angle["instruction"] if variant_angle else None

    # Load reference assets for this step
    reference_assets = []
    asset_ids = step.get("asset_ids", [])
    asset_modes = step.get("asset_mode", {})
    if asset_ids:
        ref_ids = [aid for aid in asset_ids if asset_modes.get(aid) == "reference"]
        if ref_ids:
            assets = Asset.query.filter(Asset.id.in_(ref_ids)).all()
            reference_assets = [
                {
                    "filename": a.filename,
                    "content_type": a.content_type,
                    "summary": (a.metadata_ or {}).get(
                        "summary", f"[{a.filename} — no summary available]"
                    ),
                }
                for a in assets
            ]

    prompt = build_generation_prompt(
        channel=step["channel"],
        step_label=step.get("label", f"Step {step['step']}"),
        contact_data=contact_data,
        company_data=company_data,
        enrichment_data=enrichment_data,
        generation_config=generation_config,
        step_number=step["step"],
        total_steps=total_steps,
        strategy_data=strategy_data,
        per_message_instruction=angle_instruction,
        example_messages=step.get("example_messages"),
        max_length=step.get("max_length"),
        reference_assets=reference_assets or None,
        feedback_signals=feedback_signals,
    )

    start_time = time.time()

    # Call Claude API
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=GENERATION_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    duration_ms = int((time.time() - start_time) * 1000)

    # Parse response
    raw_text = response.content[0].text
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        # Try to extract JSON from response
        import re

        match = re.search(r"\{[^}]+\}", raw_text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
        else:
            parsed = {"body": raw_text}

    subject = parsed.get("subject")
    body = parsed.get("body", raw_text)

    # Enforce channel constraints
    constraints = CHANNEL_CONSTRAINTS.get(step["channel"], {})
    max_chars = constraints.get("max_chars", 5000)
    if len(body) > max_chars:
        body = body[:max_chars]

    # Log cost
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = compute_cost(
        GENERATION_PROVIDER, GENERATION_MODEL, input_tokens, output_tokens
    )

    log_llm_usage(
        tenant_id=tenant_id,
        operation="message_generation",
        model=GENERATION_MODEL,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider=GENERATION_PROVIDER,
        user_id=user_id,
        duration_ms=duration_ms,
        metadata={
            "campaign_id": campaign_id,
            "contact_id": contact_id,
            "channel": step["channel"],
            "step": step["step"],
            "variant": variant_letter,
            "variant_angle": variant_angle["key"] if variant_angle else None,
        },
    )

    # Save message
    msg = Message(
        tenant_id=tenant_id,
        contact_id=contact_id,
        owner_id=owner_id,
        channel=step["channel"],
        sequence_step=step["step"],
        variant=variant_letter,
        label=step.get("label"),
        subject=subject,
        body=body,
        status="draft",
        tone=generation_config.get("tone", "professional"),
        language=generation_config.get("language", "en"),
        generation_cost_usd=float(cost),
        campaign_contact_id=cc_id,
        variant_group=variant_group_id,
        variant_angle=variant_angle["key"] if variant_angle else None,
    )
    if step.get("campaign_step_id"):
        msg.campaign_step_id = step["campaign_step_id"]

    db.session.add(msg)
    db.session.flush()

    return cost


def estimate_regeneration_cost(message_id: str, tenant_id: str) -> dict:
    """Estimate the cost of regenerating a single message.

    Counts tokens from the enrichment context to give a real estimate.
    Returns dict with cost, input_tokens, output_tokens, model.
    """
    msg = db.session.execute(
        db.text("""
            SELECT m.contact_id, ct.company_id, m.channel
            FROM messages m
            JOIN contacts ct ON m.contact_id = ct.id
            WHERE m.id = :id AND m.tenant_id = :t
        """),
        {"id": message_id, "t": tenant_id},
    ).fetchone()

    if not msg:
        return None

    contact_id = str(msg[0])
    company_id = str(msg[1]) if msg[1] else None
    channel = msg[2]

    # Load enrichment to estimate prompt size
    company_data, enrichment_data = _load_enrichment_context(contact_id, company_id)

    # Build a sample prompt to count tokens (approximate)
    sample_prompt = build_generation_prompt(
        channel=channel,
        step_label="Step 1",
        contact_data={"first_name": "X"},
        company_data=company_data,
        enrichment_data=enrichment_data,
        generation_config={},
        step_number=1,
        total_steps=1,
    )

    # Rough token estimate: ~4 chars per token
    est_input = max(len(sample_prompt) // 4, EST_INPUT_TOKENS)
    est_output = EST_OUTPUT_TOKENS

    cost = compute_cost(GENERATION_PROVIDER, GENERATION_MODEL, est_input, est_output)

    return {
        "estimated_cost": float(cost),
        "input_tokens": est_input,
        "output_tokens": est_output,
        "model": GENERATION_MODEL,
    }


def regenerate_message(
    message_id: str,
    tenant_id: str,
    user_id: str = None,
    language: str = None,
    formality: str = None,
    tone: str = None,
    instruction: str = None,
) -> dict:
    """Regenerate a single message with optional overrides.

    Preserves the original body/subject on first regeneration.
    Returns the updated message dict or None if message not found.
    """
    # Load message with context
    row = db.session.execute(
        db.text("""
            SELECT m.id, m.tenant_id, m.contact_id, m.owner_id,
                   m.channel, m.sequence_step, m.variant, m.label,
                   m.subject, m.body, m.status, m.tone, m.language,
                   m.generation_cost_usd, m.campaign_contact_id,
                   m.original_body, m.original_subject,
                   m.regen_count, m.regen_config,
                   ct.first_name, ct.last_name, ct.job_title,
                   ct.email_address, ct.linkedin_url,
                   ct.seniority_level, ct.department, ct.company_id
            FROM messages m
            JOIN contacts ct ON m.contact_id = ct.id
            WHERE m.id = :id AND m.tenant_id = :t
        """),
        {"id": message_id, "t": tenant_id},
    ).fetchone()

    if not row:
        return None

    contact_id = str(row[2])
    channel = row[4]
    sequence_step = row[5]
    label = row[7]
    current_subject = row[8]
    current_body = row[9]
    current_tone = row[11]
    current_language = row[12]
    cc_id = row[14]
    original_body = row[15]
    original_subject = row[16]
    regen_count = row[17] or 0
    company_id = str(row[27]) if row[27] else None

    # Preserve originals on first regen/edit
    if original_body is None:
        original_body = current_body
    if original_subject is None and current_subject:
        original_subject = current_subject

    # Load enrichment context
    contact_data = {
        "first_name": row[19],
        "last_name": row[20],
        "job_title": row[21],
        "email_address": row[22],
        "linkedin_url": row[23],
        "seniority_level": row[24],
        "department": row[25],
    }
    company_data, enrichment_data = _load_enrichment_context(contact_id, company_id)

    # Load campaign generation config
    campaign_config = {}
    strategy_data = None
    if cc_id:
        camp_row = db.session.execute(
            db.text("""
                SELECT c.generation_config, c.template_config, c.tenant_id, c.id
                FROM campaigns c
                JOIN campaign_contacts cc ON cc.campaign_id = c.id
                WHERE cc.id = :cc_id
            """),
            {"cc_id": cc_id},
        ).fetchone()
        if camp_row:
            campaign_config = (
                json.loads(camp_row[0])
                if isinstance(camp_row[0], str)
                else (camp_row[0] or {})
            )
            template_config = (
                json.loads(camp_row[1])
                if isinstance(camp_row[1], str)
                else (camp_row[1] or [])
            )
            camp_id = camp_row[3]
            step_count = CampaignStep.query.filter_by(campaign_id=camp_id).count()
            if step_count > 0:
                total_steps = step_count
            else:
                total_steps = len([s for s in template_config if s.get("enabled")])

            # Use strategy snapshot from generation_config, or load fresh
            strategy_data = campaign_config.get("strategy_snapshot")
            if not strategy_data:
                camp_tenant_id = camp_row[2]
                if camp_tenant_id:
                    strategy_data = _load_strategy_data(str(camp_tenant_id))
        else:
            total_steps = 1
    else:
        total_steps = 1

    # Apply overrides
    effective_language = (
        language or current_language or campaign_config.get("language", "en")
    )
    effective_tone = tone or current_tone or campaign_config.get("tone", "professional")

    gen_config = dict(campaign_config)
    gen_config["language"] = effective_language
    gen_config["tone"] = effective_tone

    prompt = build_generation_prompt(
        channel=channel,
        step_label=label or f"Step {sequence_step}",
        contact_data=contact_data,
        company_data=company_data,
        enrichment_data=enrichment_data,
        generation_config=gen_config,
        step_number=sequence_step or 1,
        total_steps=total_steps,
        strategy_data=strategy_data,
        formality=formality,
        per_message_instruction=instruction,
    )

    start_time = time.time()

    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=GENERATION_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    duration_ms = int((time.time() - start_time) * 1000)

    # Parse response
    raw_text = response.content[0].text
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        import re

        match = re.search(r"\{[^}]+\}", raw_text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
        else:
            parsed = {"body": raw_text}

    new_subject = parsed.get("subject")
    new_body = parsed.get("body", raw_text)

    constraints = CHANNEL_CONSTRAINTS.get(channel, {})
    max_chars = constraints.get("max_chars", 5000)
    if len(new_body) > max_chars:
        new_body = new_body[:max_chars]

    # Log cost
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = compute_cost(
        GENERATION_PROVIDER, GENERATION_MODEL, input_tokens, output_tokens
    )

    log_llm_usage(
        tenant_id=tenant_id,
        operation="message_regeneration",
        model=GENERATION_MODEL,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider=GENERATION_PROVIDER,
        user_id=user_id,
        duration_ms=duration_ms,
        metadata={
            "message_id": message_id,
            "contact_id": contact_id,
            "channel": channel,
            "overrides": {
                "language": language,
                "formality": formality,
                "tone": tone,
                "instruction": instruction,
            },
        },
    )

    # Store regen config
    regen_config = {
        "language": effective_language,
        "formality": formality,
        "tone": effective_tone,
        "instruction": instruction,
    }

    # Update message
    db.session.execute(
        db.text("""
            UPDATE messages
            SET body = :body,
                subject = :subject,
                original_body = :orig_body,
                original_subject = :orig_subject,
                regen_count = :regen_count,
                regen_config = :regen_config,
                generation_cost_usd = COALESCE(generation_cost_usd, 0) + :cost,
                language = :language,
                tone = :tone,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """),
        {
            "body": new_body,
            "subject": new_subject,
            "orig_body": original_body,
            "orig_subject": original_subject,
            "regen_count": regen_count + 1,
            "regen_config": json.dumps(regen_config),
            "cost": float(cost),
            "language": effective_language,
            "tone": effective_tone,
            "id": message_id,
        },
    )
    db.session.commit()

    return {
        "id": message_id,
        "body": new_body,
        "subject": new_subject,
        "original_body": original_body,
        "original_subject": original_subject,
        "regen_count": regen_count + 1,
        "regen_config": regen_config,
        "language": effective_language,
        "tone": effective_tone,
        "generation_cost_usd": float(cost),
    }
