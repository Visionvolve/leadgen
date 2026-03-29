"""CRUD routes for campaign steps (outreach sequence builder)."""

import json
import logging
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request

from ..auth import require_auth, resolve_tenant
from ..models import (
    Campaign,
    CampaignContact,
    CampaignStep,
    CampaignTemplate,
    Contact,
    Company,
    db,
)
from ..services.step_designer import design_steps

logger = logging.getLogger(__name__)

campaign_steps_bp = Blueprint("campaign_steps", __name__)


def _parse_jsonb(v):
    """Parse a JSONB column value — may be dict/list (PG) or str (SQLite)."""
    if v is None:
        return None
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return v
    return v


def _step_to_dict(step):
    """Convert a CampaignStep to dict, handling SQLite JSON strings."""
    d = step.to_dict()
    d["config"] = _parse_jsonb(d["config"]) or {}
    return d


def _get_campaign_or_404(campaign_id, tenant_id):
    """Look up campaign by id and tenant, return (campaign, None) or (None, error_response)."""
    campaign = Campaign.query.filter_by(id=campaign_id, tenant_id=tenant_id).first()
    if not campaign:
        return None, (jsonify({"error": "Campaign not found"}), 404)
    return campaign, None


@campaign_steps_bp.route("/api/campaigns/<campaign_id>/steps", methods=["GET"])
@require_auth
def list_steps(campaign_id):
    """List all steps for a campaign, ordered by position."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign, err = _get_campaign_or_404(campaign_id, tenant_id)
    if err:
        return err

    steps = (
        CampaignStep.query.filter_by(campaign_id=campaign_id, tenant_id=tenant_id)
        .order_by(CampaignStep.position)
        .all()
    )
    return jsonify({"steps": [_step_to_dict(s) for s in steps]}), 200


@campaign_steps_bp.route("/api/campaigns/<campaign_id>/steps", methods=["POST"])
@require_auth
def add_step(campaign_id):
    """Add a new step to a campaign. Position auto-increments if not provided."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign, err = _get_campaign_or_404(campaign_id, tenant_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}

    # Auto-increment position if not provided
    if "position" not in data:
        max_pos = (
            db.session.query(db.func.max(CampaignStep.position))
            .filter_by(campaign_id=campaign_id)
            .scalar()
        )
        data["position"] = (max_pos or 0) + 1

    step = CampaignStep(
        id=str(uuid.uuid4()),
        campaign_id=campaign_id,
        tenant_id=tenant_id,
        position=data["position"],
        channel=data.get("channel", "linkedin_message"),
        day_offset=data.get("day_offset", 0),
        label=data.get("label", ""),
        config=json.dumps(data.get("config", {})),
    )
    db.session.add(step)
    db.session.commit()

    return jsonify(_step_to_dict(step)), 201


@campaign_steps_bp.route(
    "/api/campaigns/<campaign_id>/steps/<step_id>", methods=["PATCH"]
)
@require_auth
def update_step(campaign_id, step_id):
    """Update an existing campaign step."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign, err = _get_campaign_or_404(campaign_id, tenant_id)
    if err:
        return err

    step = CampaignStep.query.filter_by(
        id=step_id, campaign_id=campaign_id, tenant_id=tenant_id
    ).first()
    if not step:
        return jsonify({"error": "Step not found"}), 404

    data = request.get_json(silent=True) or {}

    allowed = ("channel", "day_offset", "label", "config")
    updated = False
    for field in allowed:
        if field in data:
            if field == "config":
                setattr(step, field, json.dumps(data[field]))
            else:
                setattr(step, field, data[field])
            updated = True

    if not updated:
        return jsonify({"error": "No valid fields to update"}), 400

    db.session.commit()
    return jsonify(_step_to_dict(step)), 200


@campaign_steps_bp.route(
    "/api/campaigns/<campaign_id>/steps/<step_id>", methods=["DELETE"]
)
@require_auth
def delete_step(campaign_id, step_id):
    """Delete a step and reorder remaining steps to close the gap."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign, err = _get_campaign_or_404(campaign_id, tenant_id)
    if err:
        return err

    step = CampaignStep.query.filter_by(
        id=step_id, campaign_id=campaign_id, tenant_id=tenant_id
    ).first()
    if not step:
        return jsonify({"error": "Step not found"}), 404

    deleted_position = step.position
    db.session.delete(step)
    db.session.flush()

    # Reorder remaining steps to close the gap
    remaining = (
        CampaignStep.query.filter(
            CampaignStep.campaign_id == campaign_id,
            CampaignStep.position > deleted_position,
        )
        .order_by(CampaignStep.position)
        .all()
    )
    for s in remaining:
        s.position -= 1

    db.session.commit()
    return jsonify({"ok": True}), 200


@campaign_steps_bp.route("/api/campaigns/<campaign_id>/steps/reorder", methods=["PUT"])
@require_auth
def reorder_steps(campaign_id):
    """Reorder steps. Expects {"order": ["step-id-1", "step-id-2", ...]}."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign, err = _get_campaign_or_404(campaign_id, tenant_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    order = data.get("order")
    if not order or not isinstance(order, list):
        return jsonify({"error": "order must be a non-empty list of step IDs"}), 400

    steps = CampaignStep.query.filter_by(
        campaign_id=campaign_id, tenant_id=tenant_id
    ).all()
    step_map = {s.id: s for s in steps}

    # Validate order contains exactly all existing step IDs
    if len(order) != len(step_map):
        return jsonify({"error": "order must contain all step IDs"}), 400

    # Validate all IDs exist
    for sid in order:
        if sid not in step_map:
            return jsonify({"error": f"Step {sid} not found"}), 404

    # Use temporary negative positions to avoid unique constraint violations
    for i, sid in enumerate(order):
        step_map[sid].position = -(i + 1)
    db.session.flush()

    # Now set the real positions
    for i, sid in enumerate(order):
        step_map[sid].position = i + 1
    db.session.commit()

    # Return updated list
    ordered = (
        CampaignStep.query.filter_by(campaign_id=campaign_id, tenant_id=tenant_id)
        .order_by(CampaignStep.position)
        .all()
    )
    return jsonify({"steps": [_step_to_dict(s) for s in ordered]}), 200


@campaign_steps_bp.route(
    "/api/campaigns/<campaign_id>/steps/from-template", methods=["POST"]
)
@require_auth
def populate_from_template(campaign_id):
    """Populate campaign steps from a campaign template."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign, err = _get_campaign_or_404(campaign_id, tenant_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    template_id = data.get("template_id")
    if not template_id:
        return jsonify({"error": "template_id is required"}), 400

    template = CampaignTemplate.query.filter_by(
        id=template_id, tenant_id=str(tenant_id)
    ).first()
    if not template:
        return jsonify({"error": "Template not found"}), 404

    # Parse template steps (may be JSON string in SQLite)
    template_steps = _parse_jsonb(template.steps)
    if not template_steps or not isinstance(template_steps, list):
        return jsonify({"error": "Template has no steps"}), 400

    # Delete existing steps for this campaign
    CampaignStep.query.filter_by(campaign_id=campaign_id, tenant_id=tenant_id).delete()
    db.session.flush()

    # Create new steps from template
    created = []
    for ts in template_steps:
        step = CampaignStep(
            id=str(uuid.uuid4()),
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            position=ts.get("step", len(created) + 1),
            channel=ts.get("channel", "linkedin_message"),
            day_offset=ts.get("day_offset", 0),
            label=ts.get("label", ""),
            config=json.dumps(ts.get("config", {})),
            condition=ts.get("condition", "always"),
            execution_status="pending",
        )
        db.session.add(step)
        created.append(step)

    db.session.commit()
    return jsonify({"steps": [_step_to_dict(s) for s in created]}), 201


@campaign_steps_bp.route(
    "/api/campaigns/<campaign_id>/steps/ai-design", methods=["POST"]
)
@require_auth
def ai_design_steps(campaign_id):
    """Propose campaign steps using AI. Does not save — returns a proposal."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign, err = _get_campaign_or_404(campaign_id, tenant_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    goal = data.get("goal")
    if not goal:
        return jsonify({"error": "goal is required"}), 400

    # Build campaign context from contacts
    campaign_context: dict = {}
    contact_count = CampaignContact.query.filter_by(campaign_id=campaign_id).count()
    if contact_count:
        campaign_context["contact_count"] = contact_count

        # Get top industries from campaign contacts
        industry_rows = (
            db.session.query(Company.industry)
            .join(Contact, Contact.company_id == Company.id)
            .join(CampaignContact, CampaignContact.contact_id == Contact.id)
            .filter(
                CampaignContact.campaign_id == campaign_id,
                Company.industry.isnot(None),
            )
            .group_by(Company.industry)
            .order_by(db.func.count().desc())
            .limit(5)
            .all()
        )
        if industry_rows:
            campaign_context["industries"] = [r[0] for r in industry_rows]

        # Get top seniority levels
        seniority_rows = (
            db.session.query(Contact.seniority_level)
            .join(CampaignContact, CampaignContact.contact_id == Contact.id)
            .filter(
                CampaignContact.campaign_id == campaign_id,
                Contact.seniority_level.isnot(None),
            )
            .group_by(Contact.seniority_level)
            .order_by(db.func.count().desc())
            .limit(5)
            .all()
        )
        if seniority_rows:
            campaign_context["seniority_levels"] = [r[0] for r in seniority_rows]

    try:
        result = design_steps(
            goal=goal,
            channel_preference=data.get("channel_preference"),
            num_steps=data.get("num_steps"),
            campaign_context=campaign_context or None,
            feedback_context=data.get("feedback_context"),
        )
        return jsonify(result), 200
    except Exception as e:
        logger.exception("AI step design failed")
        return jsonify({"error": f"AI design failed: {e}"}), 500


@campaign_steps_bp.route(
    "/api/campaigns/<campaign_id>/steps/ai-design/confirm", methods=["POST"]
)
@require_auth
def ai_design_confirm(campaign_id):
    """Confirm and save AI-proposed steps. Replaces existing steps."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign, err = _get_campaign_or_404(campaign_id, tenant_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    steps_data = data.get("steps")
    if not steps_data or not isinstance(steps_data, list):
        return jsonify({"error": "steps must be a non-empty list"}), 400

    # Clear existing steps
    CampaignStep.query.filter_by(campaign_id=campaign_id, tenant_id=tenant_id).delete()
    db.session.flush()

    # Create new steps from confirmed proposal
    created = []
    for i, s in enumerate(steps_data):
        step = CampaignStep(
            id=str(uuid.uuid4()),
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            position=i + 1,
            channel=s.get("channel", "linkedin_message"),
            day_offset=s.get("day_offset", 0),
            label=s.get("label", ""),
            config=json.dumps(s.get("config", {})),
        )
        db.session.add(step)
        created.append(step)

    db.session.commit()
    return jsonify({"steps": [_step_to_dict(s) for s in created]}), 201


# ── Sequence (execution-focused) endpoints ───────────────────


@campaign_steps_bp.route("/api/campaigns/<campaign_id>/sequence", methods=["GET"])
@require_auth
def get_sequence(campaign_id):
    """Return steps with execution info, ordered by position."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign, err = _get_campaign_or_404(campaign_id, tenant_id)
    if err:
        return err

    steps = (
        CampaignStep.query.filter_by(campaign_id=campaign_id, tenant_id=tenant_id)
        .order_by(CampaignStep.position)
        .all()
    )
    return jsonify({"sequence": [_step_to_dict(s) for s in steps]}), 200


@campaign_steps_bp.route("/api/campaigns/<campaign_id>/sequence", methods=["PUT"])
@require_auth
def replace_sequence(campaign_id):
    """Bulk replace sequence config. Accepts array of step definitions."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign, err = _get_campaign_or_404(campaign_id, tenant_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    steps_data = data.get("steps")
    if not steps_data or not isinstance(steps_data, list):
        return jsonify({"error": "steps must be a non-empty list"}), 400

    # Delete existing steps
    CampaignStep.query.filter_by(campaign_id=campaign_id, tenant_id=tenant_id).delete()
    db.session.flush()

    # Create new steps
    created = []
    for i, s in enumerate(steps_data):
        step = CampaignStep(
            id=str(uuid.uuid4()),
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            position=s.get("position", i + 1),
            channel=s.get("channel", "linkedin_message"),
            day_offset=s.get("day_offset", 0),
            label=s.get("label", ""),
            config=json.dumps(s.get("config", {})),
            condition=s.get("condition", "always"),
            execution_status="pending",
        )
        db.session.add(step)
        created.append(step)

    db.session.commit()
    return jsonify({"sequence": [_step_to_dict(s) for s in created]}), 200


@campaign_steps_bp.route(
    "/api/campaigns/<campaign_id>/sequence/<int:step_number>", methods=["PATCH"]
)
@require_auth
def patch_sequence_step(campaign_id, step_number):
    """Update a single step's execution-related fields by position number."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign, err = _get_campaign_or_404(campaign_id, tenant_id)
    if err:
        return err

    step = CampaignStep.query.filter_by(
        campaign_id=campaign_id, tenant_id=tenant_id, position=step_number
    ).first()
    if not step:
        return jsonify({"error": "Step not found"}), 404

    data = request.get_json(silent=True) or {}

    allowed = (
        "condition",
        "execution_status",
        "day_offset",
        "started_at",
        "completed_at",
    )
    updated = False
    for field in allowed:
        if field in data:
            value = data[field]
            # Parse ISO timestamps
            if field in ("started_at", "completed_at") and isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value)
                except (ValueError, TypeError):
                    return jsonify({"error": f"Invalid timestamp for {field}"}), 400
            setattr(step, field, value)
            updated = True

    if not updated:
        return jsonify({"error": "No valid fields to update"}), 400

    db.session.commit()
    return jsonify(_step_to_dict(step)), 200
