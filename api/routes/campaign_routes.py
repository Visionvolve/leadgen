import csv
import io
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

from flask import (
    Blueprint,
    Response,
    current_app,
    g,
    jsonify,
    request,
    stream_with_context,
)
from sqlalchemy.exc import OperationalError

from ..auth import require_auth, require_role, resolve_tenant
from ..display import display_campaign_status, display_tier, display_status
from ..models import (
    Asset,
    Campaign,
    CampaignContact,
    CampaignStep,
    CampaignTemplate,
    EmailSendLog,
    LinkedInSendQueue,
    Message,
    MessageFeedback,
    StrategyDocument,
    Tenant,
    db,
)
from ..services.asset_service import (
    delete_asset,
    download_asset_bytes,
    get_download_url,
    upload_asset,
    validate_upload,
)
from ..services.message_generator import estimate_generation_cost, start_generation
from ..services.send_service import (
    get_quota_status,
    get_send_status,
    send_campaign_emails,
    send_campaign_emails_gmail,
)

logger = logging.getLogger(__name__)

campaigns_bp = Blueprint("campaigns", __name__)

# Valid status transitions
VALID_TRANSITIONS = {
    "draft": {"ready", "archived"},
    "ready": {"draft", "generating"},
    "generating": {"review"},
    "review": {"approved", "ready"},
    "approved": {"exported", "review"},
    "exported": {"archived"},
}


def _format_ts(v):
    """Format a timestamp value that may be a datetime or a string."""
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


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


def _build_strategy_generation_config(extracted: dict) -> dict:
    """Build generation_config from strategy extracted_data.

    Extracts tone, messaging angles, value proposition, and target persona
    into a generation_config dict that guides message generation.
    """
    config = {}

    # Tone from messaging framework
    messaging = extracted.get("messaging", {})
    if isinstance(messaging, dict):
        if messaging.get("tone"):
            config["tone"] = messaging["tone"]
        # Messaging angles/themes become custom_instructions
        angles = messaging.get("angles") or messaging.get("themes") or []
        if angles and isinstance(angles, list):
            config["messaging_angles"] = angles
        # Proof points
        proof = messaging.get("proof_points") or []
        if proof and isinstance(proof, list):
            config["proof_points"] = proof

    # Value proposition
    vp = extracted.get("value_proposition")
    if vp:
        if isinstance(vp, dict):
            config["value_proposition"] = ", ".join(str(v) for v in vp.values() if v)
        else:
            config["value_proposition"] = str(vp)

    # Competitive positioning
    comp = extracted.get("competitive_positioning")
    if comp:
        if isinstance(comp, list):
            config["competitive_positioning"] = ", ".join(str(c) for c in comp)
        elif isinstance(comp, str):
            config["competitive_positioning"] = comp

    # Buyer personas (first one as target persona)
    personas = extracted.get("personas")
    if personas and isinstance(personas, list) and len(personas) > 0:
        first = personas[0]
        if isinstance(first, dict):
            persona_desc = first.get("title_patterns", [])
            if persona_desc:
                config["target_persona"] = ", ".join(persona_desc)
            pains = first.get("pain_points", [])
            if pains:
                config["target_pain_points"] = pains

    # Build custom_instructions from strategy context
    instructions_parts = []
    if config.get("value_proposition"):
        instructions_parts.append(f"Value proposition: {config['value_proposition']}")
    if config.get("messaging_angles"):
        instructions_parts.append(
            "Messaging angles: " + ", ".join(config["messaging_angles"])
        )
    if config.get("competitive_positioning"):
        instructions_parts.append(
            f"Competitive positioning: {config['competitive_positioning']}"
        )
    if config.get("target_persona"):
        instructions_parts.append(f"Target persona: {config['target_persona']}")
    if instructions_parts:
        config["custom_instructions"] = "Pre-filled from GTM Strategy:\n" + "\n".join(
            instructions_parts
        )

    return config


@campaigns_bp.route("/api/campaigns", methods=["GET"])
@require_auth
def list_campaigns():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    rows = db.session.execute(
        db.text("""
            SELECT
                c.id, c.name, c.status, c.description,
                c.total_contacts, c.generated_count, c.generation_cost,
                c.template_config, c.generation_config,
                c.created_at, c.updated_at,
                o.name AS owner_name
            FROM campaigns c
            LEFT JOIN owners o ON c.owner_id = o.id
            WHERE c.tenant_id = :t AND c.is_active = true
                AND COALESCE(c.status, 'draft') != 'archived'
            ORDER BY c.created_at DESC
        """),
        {"t": tenant_id},
    ).fetchall()

    campaigns = []
    for r in rows:
        campaigns.append(
            {
                "id": str(r[0]),
                "name": r[1],
                "status": display_campaign_status(r[2] or "draft"),
                "description": r[3],
                "total_contacts": r[4] or 0,
                "generated_count": r[5] or 0,
                "generation_cost": float(r[6]) if r[6] else 0,
                "template_config": _parse_jsonb(r[7]) or [],
                "generation_config": _parse_jsonb(r[8]) or {},
                "created_at": _format_ts(r[9]),
                "updated_at": _format_ts(r[10]),
                "owner_name": r[11],
            }
        )

    return jsonify({"campaigns": campaigns})


@campaigns_bp.route("/api/campaigns", methods=["POST"])
@require_role("editor")
def create_campaign():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    description = body.get("description", "")
    owner_id = body.get("owner_id")
    template_id = body.get("template_id")
    strategy_id = body.get("strategy_id")

    # If creating from a template, copy its steps and config
    template_config = []
    generation_config = {}
    if template_id:
        tpl = db.session.execute(
            db.text("""
                SELECT steps, default_config
                FROM campaign_templates
                WHERE id = :id AND (tenant_id = :t OR tenant_id IS NULL)
            """),
            {"id": template_id, "t": tenant_id},
        ).fetchone()
        if tpl:
            template_config = _parse_jsonb(tpl[0]) or []
            generation_config = _parse_jsonb(tpl[1]) or {}

    # Auto-populate from strategy
    target_criteria = body.get("target_criteria", {})
    channel = body.get("channel")
    strategy_prefilled = False

    # Auto-find strategy if not explicitly provided
    if not strategy_id:
        strat_doc = StrategyDocument.query.filter_by(tenant_id=tenant_id).first()
        if strat_doc and strat_doc.extracted_data:
            strategy_id = str(strat_doc.id)

    if strategy_id:
        strat_doc = StrategyDocument.query.filter_by(
            id=strategy_id, tenant_id=tenant_id
        ).first()
        if strat_doc and strat_doc.extracted_data:
            extracted = _parse_jsonb(strat_doc.extracted_data)
            if extracted and isinstance(extracted, dict):
                strategy_prefilled = True

                # Auto-populate target_criteria from ICP (body arg overrides)
                if not target_criteria:
                    icp = extracted.get("icp", {})
                    if icp and isinstance(icp, dict):
                        target_criteria = icp

                # Auto-populate generation_config from strategy
                if not generation_config:
                    generation_config = _build_strategy_generation_config(extracted)

                # Auto-populate channel from channels.primary
                if not channel:
                    channels = extracted.get("channels", {})
                    if isinstance(channels, dict) and channels.get("primary"):
                        channel = channels["primary"]

    # UA campaign features: language + scheduled launch
    language = body.get("language", "cs")
    scheduled_launch_at = body.get("scheduled_launch_at")

    # Use ORM to avoid SQL dialect issues with JSONB casting
    campaign = Campaign(
        tenant_id=tenant_id,
        name=name,
        description=description,
        owner_id=owner_id,
        status="draft",
        strategy_id=strategy_id,
        channel=channel,
        language=language,
        scheduled_launch_at=scheduled_launch_at,
        target_criteria=json.dumps(target_criteria)
        if isinstance(target_criteria, dict)
        else target_criteria,
        template_config=json.dumps(template_config)
        if isinstance(template_config, (dict, list))
        else template_config,
        generation_config=json.dumps(generation_config)
        if isinstance(generation_config, (dict, list))
        else generation_config,
    )
    db.session.add(campaign)
    db.session.commit()

    result = {
        "id": str(campaign.id),
        "name": name,
        "status": "Draft",
        "created_at": _format_ts(campaign.created_at),
    }
    if strategy_prefilled:
        result["strategy_prefilled"] = True
        result["generation_config"] = generation_config

    return jsonify(result), 201


@campaigns_bp.route("/api/campaigns/<campaign_id>", methods=["GET"])
@require_auth
def get_campaign(campaign_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text("""
            SELECT
                c.id, c.name, c.status, c.description,
                c.total_contacts, c.generated_count, c.generation_cost,
                c.template_config, c.generation_config,
                c.generation_started_at, c.generation_completed_at,
                c.created_at, c.updated_at,
                o.name AS owner_name, o.id AS owner_id,
                c.sender_config, c.language
            FROM campaigns c
            LEFT JOIN owners o ON c.owner_id = o.id
            WHERE c.id = :id AND c.tenant_id = :t
        """),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Campaign not found"}), 404

    # Get contact status counts
    contact_stats = db.session.execute(
        db.text("""
            SELECT status, COUNT(*) AS cnt
            FROM campaign_contacts
            WHERE campaign_id = :id AND tenant_id = :t
            GROUP BY status
        """),
        {"id": campaign_id, "t": tenant_id},
    ).fetchall()

    status_counts = {r[0]: r[1] for r in contact_stats}

    return jsonify(
        {
            "id": str(row[0]),
            "name": row[1],
            "status": display_campaign_status(row[2] or "draft"),
            "description": row[3],
            "total_contacts": row[4] or 0,
            "generated_count": row[5] or 0,
            "generation_cost": float(row[6]) if row[6] else 0,
            "template_config": _parse_jsonb(row[7]) or [],
            "generation_config": _parse_jsonb(row[8]) or {},
            "generation_started_at": _format_ts(row[9]),
            "generation_completed_at": _format_ts(row[10]),
            "created_at": _format_ts(row[11]),
            "updated_at": _format_ts(row[12]),
            "owner_name": row[13],
            "owner_id": str(row[14]) if row[14] else None,
            "sender_config": _parse_jsonb(row[15]) or {},
            "language": row[16] or "cs",
            "contact_status_counts": status_counts,
        }
    )


@campaigns_bp.route("/api/campaigns/<campaign_id>", methods=["PATCH"])
@require_role("editor")
def update_campaign(campaign_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}

    # Verify campaign exists and belongs to tenant
    existing = db.session.execute(
        db.text("SELECT status FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not existing:
        return jsonify({"error": "Campaign not found"}), 404

    current_status = existing[0] or "draft"

    # Validate status transition if status is being updated
    new_status = body.get("status")
    if new_status:
        allowed = VALID_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            return jsonify(
                {
                    "error": f"Cannot transition from '{current_status}' to '{new_status}'",
                    "allowed": sorted(allowed),
                }
            ), 400

        # Approval gate: review → approved requires no draft messages
        if current_status == "review" and new_status == "approved":
            draft_count = db.session.execute(
                db.text("""
                    SELECT COUNT(*) FROM messages m
                    JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
                    WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                        AND m.status = 'draft'
                """),
                {"cid": campaign_id, "t": tenant_id},
            ).scalar()
            if draft_count > 0:
                return jsonify(
                    {
                        "error": f"Cannot approve: {draft_count} messages still in draft status",
                        "pending_count": draft_count,
                    }
                ), 400

    allowed_fields = {
        "name",
        "description",
        "status",
        "owner_id",
        "template_config",
        "generation_config",
        "sender_config",
    }
    fields = {k: v for k, v in body.items() if k in allowed_fields}

    if not fields:
        return jsonify({"error": "No valid fields to update"}), 400

    set_parts = []
    params = {"id": campaign_id, "t": tenant_id}
    for k, v in fields.items():
        if k in ("template_config", "generation_config", "sender_config"):
            set_parts.append(f"{k} = :{k}")
            params[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
        else:
            set_parts.append(f"{k} = :{k}")
            params[k] = v

    db.session.execute(
        db.text(
            f"UPDATE campaigns SET {', '.join(set_parts)} WHERE id = :id AND tenant_id = :t"
        ),
        params,
    )
    db.session.commit()

    return jsonify({"ok": True})


@campaigns_bp.route("/api/campaigns/<campaign_id>", methods=["DELETE"])
@require_role("editor")
def delete_campaign(campaign_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    existing = db.session.execute(
        db.text("SELECT status FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not existing:
        return jsonify({"error": "Campaign not found"}), 404

    current_status = existing[0] or "draft"
    if current_status != "draft":
        return jsonify({"error": "Only draft campaigns can be deleted"}), 400

    # Soft delete: set status to archived and is_active to false
    db.session.execute(
        db.text("""
            UPDATE campaigns
            SET status = 'archived', is_active = false
            WHERE id = :id AND tenant_id = :t
        """),
        {"id": campaign_id, "t": tenant_id},
    )
    db.session.commit()

    return jsonify({"ok": True})


# ── Clone Campaign ─────────────────────────────────────────────


@campaigns_bp.route("/api/campaigns/<campaign_id>/clone", methods=["POST"])
@require_role("editor")
def clone_campaign(campaign_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    original = db.session.execute(
        db.text("""
            SELECT id, name, description, owner_id,
                   template_config, generation_config, sender_config
            FROM campaigns
            WHERE id = :id AND tenant_id = :t
        """),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not original:
        return jsonify({"error": "Campaign not found"}), 404

    body = request.get_json(silent=True) or {}
    base_name = body.get("name") or f"{original[1]} (Copy)"

    # Deduplicate name: append " (2)", " (3)" etc. if name exists
    clone_name = base_name
    counter = 1
    while True:
        exists = db.session.execute(
            db.text("""
                SELECT 1 FROM campaigns
                WHERE tenant_id = :t AND name = :n AND is_active = true
            """),
            {"t": tenant_id, "n": clone_name},
        ).fetchone()
        if not exists:
            break
        counter += 1
        clone_name = f"{base_name} ({counter})"

    # Parse JSONB fields
    gen_config = _parse_jsonb(original[5]) or {}
    # Strip runtime keys from generation_config
    for key in ("strategy_snapshot", "cancelled"):
        gen_config.pop(key, None)

    campaign = Campaign(
        tenant_id=tenant_id,
        name=clone_name,
        description=original[2],
        owner_id=original[3],
        status="draft",
        template_config=json.dumps(_parse_jsonb(original[4]) or [])
        if isinstance(_parse_jsonb(original[4]), (dict, list))
        else original[4],
        generation_config=json.dumps(gen_config),
        sender_config=json.dumps(_parse_jsonb(original[6]) or {})
        if isinstance(_parse_jsonb(original[6]), (dict, list))
        else original[6],
        total_contacts=0,
        generated_count=0,
        generation_cost=0,
    )
    db.session.add(campaign)
    db.session.commit()

    return jsonify(
        {
            "id": str(campaign.id),
            "name": clone_name,
            "status": "Draft",
        }
    ), 201


# ── Campaign Templates ────────────────────────────────────────


@campaigns_bp.route("/api/campaign-templates", methods=["GET"])
@require_auth
def list_campaign_templates():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    rows = db.session.execute(
        db.text("""
            SELECT id, name, description, steps, default_config, is_system, created_at
            FROM campaign_templates
            WHERE tenant_id = :t OR tenant_id IS NULL
            ORDER BY is_system DESC, name
        """),
        {"t": tenant_id},
    ).fetchall()

    templates = []
    for r in rows:
        templates.append(
            {
                "id": str(r[0]),
                "name": r[1],
                "description": r[2],
                "steps": _parse_jsonb(r[3]) or [],
                "default_config": _parse_jsonb(r[4]) or {},
                "is_system": bool(r[5]),
                "created_at": _format_ts(r[6]),
            }
        )

    return jsonify({"templates": templates})


@campaigns_bp.route("/api/campaign-templates", methods=["POST"])
@require_auth
def create_campaign_template():
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    steps = body.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        return jsonify({"error": "steps must be a non-empty array"}), 400

    tpl = CampaignTemplate(
        tenant_id=tenant_id,
        name=name,
        description=(body.get("description") or "").strip() or None,
        steps=json.dumps(steps),
        default_config=json.dumps(body.get("default_config") or {}),
        is_system=False,
    )
    db.session.add(tpl)
    db.session.commit()

    return (
        jsonify(
            {
                "id": str(tpl.id),
                "name": tpl.name,
                "description": tpl.description,
                "steps": _parse_jsonb(tpl.steps) or [],
                "default_config": _parse_jsonb(tpl.default_config) or {},
                "is_system": False,
                "created_at": _format_ts(tpl.created_at),
            }
        ),
        201,
    )


@campaigns_bp.route("/api/campaigns/<campaign_id>/save-as-template", methods=["POST"])
@require_auth
def save_campaign_as_template(campaign_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text("""
            SELECT template_config, generation_config, name
            FROM campaigns WHERE id = :id AND tenant_id = :t
        """),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Campaign not found"}), 404

    template_config = _parse_jsonb(row[0]) or []
    generation_config = _parse_jsonb(row[1]) or {}
    campaign_name = row[2]

    if not template_config or len(template_config) == 0:
        return jsonify({"error": "Campaign has no steps to save as template"}), 400

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        name = f"{campaign_name} Template"

    # Strip runtime keys from generation_config
    default_config = {
        k: v
        for k, v in generation_config.items()
        if k not in ("strategy_snapshot", "cancelled")
    }

    tpl = CampaignTemplate(
        tenant_id=tenant_id,
        name=name,
        description=(body.get("description") or "").strip() or None,
        steps=json.dumps(template_config),
        default_config=json.dumps(default_config),
        is_system=False,
    )
    db.session.add(tpl)
    db.session.commit()

    return jsonify({"id": str(tpl.id), "name": tpl.name}), 201


@campaigns_bp.route("/api/campaign-templates/<template_id>", methods=["PATCH"])
@require_auth
def update_campaign_template(template_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text("""
            SELECT id, is_system, tenant_id
            FROM campaign_templates WHERE id = :id
        """),
        {"id": template_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Template not found"}), 404

    if row[1]:
        return jsonify({"error": "Cannot modify system templates"}), 403

    if str(row[2]) != str(tenant_id):
        return jsonify({"error": "Template not found"}), 404

    body = request.get_json(silent=True) or {}
    set_parts = []
    params = {"id": template_id}

    if "name" in body:
        name = (body["name"] or "").strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        set_parts.append("name = :name")
        params["name"] = name
    if "description" in body:
        set_parts.append("description = :description")
        params["description"] = (body["description"] or "").strip() or None

    if not set_parts:
        return jsonify({"error": "No fields to update"}), 400

    set_parts.append("updated_at = CURRENT_TIMESTAMP")
    db.session.execute(
        db.text(f"UPDATE campaign_templates SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )
    db.session.commit()

    return jsonify({"ok": True})


@campaigns_bp.route("/api/campaign-templates/<template_id>", methods=["DELETE"])
@require_auth
def delete_campaign_template(template_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text("""
            SELECT id, is_system, tenant_id
            FROM campaign_templates WHERE id = :id
        """),
        {"id": template_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Template not found"}), 404

    if row[1]:
        return jsonify({"error": "Cannot delete system templates"}), 403

    if str(row[2]) != str(tenant_id):
        return jsonify({"error": "Template not found"}), 404

    db.session.execute(
        db.text("DELETE FROM campaign_templates WHERE id = :id"),
        {"id": template_id},
    )
    db.session.commit()

    return jsonify({"ok": True})


# ── Campaign Contacts ─────────────────────────────────────────


@campaigns_bp.route("/api/campaigns/<campaign_id>/contacts", methods=["GET"])
@require_auth
def list_campaign_contacts(campaign_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify campaign exists
    campaign = db.session.execute(
        db.text("SELECT id FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    rows = db.session.execute(
        db.text("""
            SELECT
                cc.id, cc.status, cc.enrichment_gaps, cc.generation_cost, cc.error,
                cc.added_at, cc.generated_at,
                ct.id AS contact_id, ct.first_name, ct.last_name, ct.job_title,
                ct.email_address, ct.linkedin_url, ct.contact_score, ct.icp_fit,
                co.id AS company_id, co.name AS company_name, co.tier, co.status AS company_status
            FROM campaign_contacts cc
            JOIN contacts ct ON cc.contact_id = ct.id
            LEFT JOIN companies co ON ct.company_id = co.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
            ORDER BY ct.contact_score DESC NULLS LAST, ct.last_name
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    contacts = []
    for r in rows:
        contacts.append(
            {
                "campaign_contact_id": str(r[0]),
                "status": r[1],
                "enrichment_gaps": _parse_jsonb(r[2]) or [],
                "generation_cost": float(r[3]) if r[3] else 0,
                "error": r[4],
                "added_at": _format_ts(r[5]),
                "generated_at": _format_ts(r[6]),
                "contact_id": str(r[7]),
                "first_name": r[8],
                "last_name": r[9],
                "full_name": ((r[8] or "") + " " + (r[9] or "")).strip(),
                "job_title": r[10],
                "email_address": r[11],
                "linkedin_url": r[12],
                "contact_score": r[13],
                "icp_fit": r[14],
                "company_id": str(r[15]) if r[15] else None,
                "company_name": r[16],
                "company_tier": r[17],
                "company_status": r[18],
            }
        )

    return jsonify({"contacts": contacts, "total": len(contacts)})


@campaigns_bp.route("/api/campaigns/<campaign_id>/contact-ids", methods=["GET"])
@require_auth
def campaign_contact_ids(campaign_id):
    """Lightweight endpoint returning just the contact IDs in a campaign."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign = db.session.execute(
        db.text("SELECT id FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    rows = db.session.execute(
        db.text(
            "SELECT contact_id FROM campaign_contacts "
            "WHERE campaign_id = :cid AND tenant_id = :t"
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    return jsonify({"contact_ids": [str(r[0]) for r in rows]})


def _resolve_contacts_by_filters(tenant_id, owner_id, icp_filters, company_ids):
    """Resolve contact IDs from owner_id, ICP filters, and company_ids.

    Builds a dynamic SQL query joining contacts and companies to find
    contacts matching the criteria.  Returns a list of contact ID strings.
    """
    where = [
        "ct.tenant_id = :t",
        "(ct.is_disqualified = false OR ct.is_disqualified IS NULL)",
    ]
    params = {"t": tenant_id}

    if owner_id:
        where.append("ct.owner_id = :owner_id")
        params["owner_id"] = owner_id

    if company_ids:
        ph = ", ".join(f":comp_{i}" for i in range(len(company_ids)))
        for i, v in enumerate(company_ids):
            params[f"comp_{i}"] = v
        where.append(f"ct.company_id IN ({ph})")

    if icp_filters:
        # Tier filter (on company)
        tiers = icp_filters.get("tiers", [])
        if tiers:
            ph = ", ".join(f":tier_{i}" for i in range(len(tiers)))
            for i, v in enumerate(tiers):
                params[f"tier_{i}"] = v
            where.append(f"co.tier IN ({ph})")

        # Industry filter (on company)
        industries = icp_filters.get("industries", [])
        if industries:
            ph = ", ".join(f":ind_{i}" for i in range(len(industries)))
            for i, v in enumerate(industries):
                params[f"ind_{i}"] = v
            where.append(f"co.industry IN ({ph})")

        # ICP fit filter (on contact)
        icp_fit_values = icp_filters.get("icp_fit", [])
        if icp_fit_values:
            ph = ", ".join(f":icp_{i}" for i in range(len(icp_fit_values)))
            for i, v in enumerate(icp_fit_values):
                params[f"icp_{i}"] = v
            where.append(f"ct.icp_fit IN ({ph})")

        # Seniority filter (on contact)
        seniority_levels = icp_filters.get("seniority_levels", [])
        if seniority_levels:
            ph = ", ".join(f":sen_{i}" for i in range(len(seniority_levels)))
            for i, v in enumerate(seniority_levels):
                params[f"sen_{i}"] = v
            where.append(f"ct.seniority_level IN ({ph})")

        # Tag filter (on contact via contact_tag_assignments)
        tag_ids = icp_filters.get("tag_ids", [])
        if tag_ids:
            ph = ", ".join(f":tag_{i}" for i in range(len(tag_ids)))
            for i, v in enumerate(tag_ids):
                params[f"tag_{i}"] = v
            where.append(f"""EXISTS (
                SELECT 1 FROM contact_tag_assignments cta
                WHERE cta.contact_id = ct.id AND cta.tag_id IN ({ph})
            )""")

        # Min contact score
        min_score = icp_filters.get("min_contact_score")
        if min_score is not None:
            where.append("ct.contact_score >= :min_score")
            params["min_score"] = min_score

        # Enrichment readiness filter
        if icp_filters.get("enrichment_ready"):
            where.append("""EXISTS (
                SELECT 1 FROM entity_stage_completions esc_l1
                WHERE esc_l1.entity_id = co.id AND esc_l1.tenant_id = :t
                    AND esc_l1.stage = 'l1_company' AND esc_l1.status = 'completed'
            )""")
            where.append("""EXISTS (
                SELECT 1 FROM entity_stage_completions esc_l2
                WHERE esc_l2.entity_id = co.id AND esc_l2.tenant_id = :t
                    AND esc_l2.stage = 'l2_deep_research' AND esc_l2.status = 'completed'
            )""")
            where.append("""EXISTS (
                SELECT 1 FROM entity_stage_completions esc_p
                WHERE esc_p.entity_id = ct.id AND esc_p.tenant_id = :t
                    AND esc_p.stage = 'person' AND esc_p.status = 'completed'
            )""")

    where_clause = " AND ".join(where)
    rows = db.session.execute(
        db.text(f"""
            SELECT ct.id FROM contacts ct
            LEFT JOIN companies co ON ct.company_id = co.id
            WHERE {where_clause}
        """),
        params,
    ).fetchall()
    return [str(r[0]) for r in rows]


def _check_enrichment_gaps(tenant_id, contact_ids):
    """Check enrichment readiness for a set of contacts.

    Returns a list of dicts with contact_id, contact_name, and missing stages.
    Only contacts with gaps are included.
    """
    if not contact_ids:
        return []

    # Load contact + company info
    ph = ", ".join(f":cid_{i}" for i in range(len(contact_ids)))
    params = {f"cid_{i}": v for i, v in enumerate(contact_ids)}
    params["t"] = tenant_id
    contacts = db.session.execute(
        db.text(f"""
            SELECT ct.id, ct.first_name, ct.last_name, ct.company_id
            FROM contacts ct
            WHERE ct.tenant_id = :t AND ct.id IN ({ph})
        """),
        params,
    ).fetchall()

    if not contacts:
        return []

    # Build entity IDs for stage completion lookup
    company_ids_set = list({str(r[3]) for r in contacts if r[3]})
    all_entity_ids = list(set(contact_ids) | set(company_ids_set))

    completions = {}
    if all_entity_ids:
        eph = ", ".join(f":eid_{i}" for i in range(len(all_entity_ids)))
        eparams = {f"eid_{i}": v for i, v in enumerate(all_entity_ids)}
        eparams["t"] = tenant_id
        rows = db.session.execute(
            db.text(f"""
                SELECT entity_id, stage
                FROM entity_stage_completions
                WHERE tenant_id = :t AND status = 'completed'
                    AND entity_id IN ({eph})
            """),
            eparams,
        ).fetchall()
        for r in rows:
            completions.setdefault(str(r[0]), set()).add(r[1])

    gaps = []
    for row in contacts:
        cid, first_name, last_name, company_id = row
        missing = []
        company_stages = (
            completions.get(str(company_id), set()) if company_id else set()
        )
        contact_stages = completions.get(str(cid), set())

        if "l1_company" not in company_stages:
            missing.append("l1_company")
        if "l2_deep_research" not in company_stages:
            missing.append("l2_deep_research")
        if "person" not in contact_stages:
            missing.append("person")

        if missing:
            full_name = ((first_name or "") + " " + (last_name or "")).strip()
            gaps.append(
                {
                    "contact_id": str(cid),
                    "contact_name": full_name,
                    "missing": missing,
                }
            )

    return gaps


@campaigns_bp.route("/api/campaigns/<campaign_id>/contacts", methods=["POST"])
@require_role("editor")
def add_campaign_contacts(campaign_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify campaign exists and is in draft or ready state
    campaign = db.session.execute(
        db.text("SELECT status FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    if campaign[0] not in ("draft", "ready"):
        return jsonify(
            {"error": "Can only add contacts to draft or ready campaigns"}
        ), 400

    body = request.get_json(silent=True) or {}
    contact_ids = body.get("contact_ids", [])
    company_ids = body.get("company_ids", [])
    owner_id = body.get("owner_id")
    icp_filters = body.get("icp_filters")

    has_explicit = bool(contact_ids or company_ids)
    has_filters = bool(owner_id or icp_filters)

    if not has_explicit and not has_filters:
        return jsonify(
            {"error": "contact_ids, company_ids, owner_id, or icp_filters required"}
        ), 400

    # Resolve contacts from ICP filters and/or owner_id
    if has_filters:
        filter_company_ids = company_ids if company_ids else []
        resolved_ids = _resolve_contacts_by_filters(
            tenant_id, owner_id, icp_filters, filter_company_ids
        )
        # Merge with explicit contact_ids (deduplicate)
        contact_ids = list(set(contact_ids + resolved_ids))
    elif company_ids:
        # Legacy path: resolve contacts from company_ids only
        cid_placeholders = ", ".join(f":cid_{i}" for i in range(len(company_ids)))
        cid_params = {f"cid_{i}": v for i, v in enumerate(company_ids)}
        cid_params["t"] = tenant_id
        company_contacts = db.session.execute(
            db.text(f"""
                SELECT id FROM contacts
                WHERE tenant_id = :t AND company_id IN ({cid_placeholders})
                    AND (is_disqualified = false OR is_disqualified IS NULL)
            """),
            cid_params,
        ).fetchall()
        contact_ids = list(set(contact_ids + [str(r[0]) for r in company_contacts]))

    if not contact_ids:
        return jsonify({"error": "No contacts found for given criteria"}), 400

    # Verify contacts belong to tenant
    id_placeholders = ", ".join(f":id_{i}" for i in range(len(contact_ids)))
    id_params = {f"id_{i}": v for i, v in enumerate(contact_ids)}
    id_params["t"] = tenant_id
    valid = db.session.execute(
        db.text(f"""
            SELECT id FROM contacts
            WHERE tenant_id = :t AND id IN ({id_placeholders})
                AND (is_disqualified = false OR is_disqualified IS NULL)
        """),
        id_params,
    ).fetchall()
    valid_ids = {str(r[0]) for r in valid}

    # Get existing assignments to skip duplicates
    existing = db.session.execute(
        db.text("""
            SELECT contact_id FROM campaign_contacts
            WHERE campaign_id = :cid AND tenant_id = :t
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()
    existing_ids = {str(r[0]) for r in existing}

    added = 0
    skipped = 0
    added_ids = []
    for cid in contact_ids:
        if cid not in valid_ids:
            continue
        if cid in existing_ids:
            skipped += 1
            continue
        cc = CampaignContact(
            campaign_id=campaign_id,
            contact_id=cid,
            tenant_id=tenant_id,
            status="pending",
        )
        db.session.add(cc)
        added += 1
        added_ids.append(cid)

    # Flush ORM inserts so the count subquery can see them
    if added > 0:
        db.session.flush()
        db.session.execute(
            db.text("""
                UPDATE campaigns
                SET total_contacts = (
                    SELECT COUNT(*) FROM campaign_contacts
                    WHERE campaign_id = :cid AND tenant_id = :t
                )
                WHERE id = :cid AND tenant_id = :t
            """),
            {"cid": campaign_id, "t": tenant_id},
        )

    db.session.commit()

    # Check enrichment readiness for newly added contacts
    enrichment_gaps = _check_enrichment_gaps(tenant_id, added_ids) if added_ids else []

    return jsonify(
        {
            "added": added,
            "skipped": skipped,
            "total": added + len(existing_ids),
            "gaps": enrichment_gaps,
        }
    )


@campaigns_bp.route("/api/campaigns/<campaign_id>/contacts/bulk", methods=["POST"])
@require_role("editor")
def bulk_add_contacts_by_segment(campaign_id):
    """Bulk-add contacts to a campaign by company segment filter.

    Body: {segment: "obec", filters: {language: "cs", ...}}
    Returns: {added: N, skipped: N, total: N}
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify campaign exists and is in draft or ready state
    campaign = db.session.execute(
        db.text("SELECT status FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    if campaign[0] not in ("draft", "ready"):
        return jsonify(
            {"error": "Can only add contacts to draft or ready campaigns"}
        ), 400

    body = request.get_json(silent=True) or {}
    segment = body.get("segment")
    filters = body.get("filters", {})

    if not segment:
        return jsonify({"error": "segment is required"}), 400

    # Build query to find contacts via company segment
    where = [
        "ct.tenant_id = :t",
        "co.tenant_id = :t",
        "(ct.is_disqualified = false OR ct.is_disqualified IS NULL)",
        "co.segment = :segment",
    ]
    params = {"t": tenant_id, "segment": segment}

    # Optional language filter
    language = filters.get("language")
    if language:
        where.append("ct.language = :lang")
        params["lang"] = language

    # Optional business_type filter
    business_type = filters.get("business_type")
    if business_type:
        where.append("co.business_type = :btype")
        params["btype"] = business_type

    # Optional last_collaboration_at filter (active vs sleeping)
    collab_since = filters.get("collaboration_since")
    collab_before = filters.get("collaboration_before")
    if collab_since:
        try:
            datetime.fromisoformat(collab_since)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid collaboration_since datetime"}), 400
        where.append("ct.last_collaboration_at >= :collab_since")
        params["collab_since"] = collab_since
    if collab_before:
        try:
            datetime.fromisoformat(collab_before)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid collaboration_before datetime"}), 400
        where.append(
            "(ct.last_collaboration_at < :collab_before"
            " OR ct.last_collaboration_at IS NULL)"
        )
        params["collab_before"] = collab_before

    # Must have email
    if filters.get("require_email", False):
        where.append("ct.email_address IS NOT NULL")
        where.append("ct.email_address != ''")

    where_clause = " AND ".join(where)
    query = f"""
        SELECT ct.id FROM contacts ct
        JOIN companies co ON ct.company_id = co.id
        WHERE {where_clause}
    """
    rows = db.session.execute(db.text(query), params).fetchall()
    contact_ids = [str(r[0]) for r in rows]

    if not contact_ids:
        return jsonify({"added": 0, "skipped": 0, "total": 0}), 200

    # Get existing assignments to skip duplicates
    existing = db.session.execute(
        db.text("""
            SELECT contact_id FROM campaign_contacts
            WHERE campaign_id = :cid AND tenant_id = :t
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()
    existing_ids = {str(r[0]) for r in existing}

    added = 0
    for cid in contact_ids:
        if cid in existing_ids:
            continue
        cc = CampaignContact(
            campaign_id=campaign_id,
            contact_id=cid,
            tenant_id=tenant_id,
            status="pending",
        )
        db.session.add(cc)
        added += 1

    if added > 0:
        db.session.flush()
        db.session.execute(
            db.text("""
                UPDATE campaigns
                SET total_contacts = (
                    SELECT COUNT(*) FROM campaign_contacts
                    WHERE campaign_id = :cid AND tenant_id = :t
                )
                WHERE id = :cid AND tenant_id = :t
            """),
            {"cid": campaign_id, "t": tenant_id},
        )

    db.session.commit()

    return jsonify(
        {
            "added": added,
            "skipped": len(contact_ids) - added,
            "total": added + len(existing_ids),
        }
    )


@campaigns_bp.route("/api/campaigns/<campaign_id>/contacts", methods=["DELETE"])
@require_role("editor")
def remove_campaign_contacts(campaign_id):
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign = db.session.execute(
        db.text("SELECT status FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    if campaign[0] not in ("draft", "ready"):
        return jsonify(
            {"error": "Can only remove contacts from draft or ready campaigns"}
        ), 400

    body = request.get_json(silent=True) or {}
    contact_ids = body.get("contact_ids", [])
    if not contact_ids:
        return jsonify({"error": "contact_ids required"}), 400

    id_placeholders = ", ".join(f":id_{i}" for i in range(len(contact_ids)))
    del_params = {f"id_{i}": v for i, v in enumerate(contact_ids)}
    del_params["cid"] = campaign_id
    del_params["t"] = tenant_id
    result = db.session.execute(
        db.text(
            f"DELETE FROM campaign_contacts WHERE campaign_id = :cid AND tenant_id = :t AND contact_id IN ({id_placeholders})"
        ),
        del_params,
    )
    removed = result.rowcount

    # Update total_contacts count
    db.session.execute(
        db.text("""
            UPDATE campaigns
            SET total_contacts = (
                SELECT COUNT(*) FROM campaign_contacts
                WHERE campaign_id = :cid AND tenant_id = :t
            )
            WHERE id = :cid AND tenant_id = :t
        """),
        {"cid": campaign_id, "t": tenant_id},
    )
    db.session.commit()

    return jsonify({"removed": removed})


# ── Enrichment Readiness Check ───────────────────────────


@campaigns_bp.route("/api/campaigns/<campaign_id>/enrichment-check", methods=["POST"])
@require_role("editor")
def enrichment_check(campaign_id):
    """Check enrichment readiness for all contacts in a campaign.

    For each contact, checks whether their company has completed L1 and L2
    enrichment stages, and whether the contact has completed person enrichment.
    Returns per-contact readiness and a summary.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign = db.session.execute(
        db.text("SELECT id FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    # Get all campaign contacts with their company info
    contacts = db.session.execute(
        db.text("""
            SELECT
                cc.id AS cc_id, cc.contact_id, cc.status AS cc_status,
                ct.company_id, ct.first_name, ct.last_name,
                co.name AS company_name
            FROM campaign_contacts cc
            JOIN contacts ct ON cc.contact_id = ct.id
            LEFT JOIN companies co ON ct.company_id = co.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    if not contacts:
        return jsonify(
            {
                "contacts": [],
                "summary": {"total": 0, "ready": 0, "needs_enrichment": 0},
            }
        )

    # Get all completed stages for relevant entities
    company_ids = list({str(r[3]) for r in contacts if r[3]})
    contact_ids = list({str(r[1]) for r in contacts})

    # Build completions lookup: entity_id -> set of completed stages
    completions = {}
    if company_ids or contact_ids:
        all_entity_ids = company_ids + contact_ids
        ph = ", ".join(f":eid_{i}" for i in range(len(all_entity_ids)))
        params = {f"eid_{i}": v for i, v in enumerate(all_entity_ids)}
        params["t"] = tenant_id
        rows = db.session.execute(
            db.text(f"""
                SELECT entity_id, stage
                FROM entity_stage_completions
                WHERE tenant_id = :t AND status = 'completed' AND entity_id IN ({ph})
            """),
            params,
        ).fetchall()
        for r in rows:
            eid = str(r[0])
            completions.setdefault(eid, set()).add(r[1])

    # Check each contact's readiness
    result_contacts = []
    ready_count = 0
    needs_enrichment_count = 0

    for row in contacts:
        (
            cc_id,
            contact_id,
            cc_status,
            company_id,
            first_name,
            last_name,
            company_name,
        ) = row
        gaps = []
        company_stages = (
            completions.get(str(company_id), set()) if company_id else set()
        )
        contact_stages = completions.get(str(contact_id), set())

        if "l1_company" not in company_stages:
            gaps.append("l1_company")
        if "l2_deep_research" not in company_stages:
            gaps.append("l2_deep_research")
        if "person" not in contact_stages:
            gaps.append("person")

        is_ready = len(gaps) == 0
        if is_ready:
            ready_count += 1
        else:
            needs_enrichment_count += 1

        # Update campaign_contact status
        new_status = "enrichment_ok" if is_ready else "enrichment_needed"
        if cc_status in ("pending", "enrichment_ok", "enrichment_needed"):
            db.session.execute(
                db.text("""
                    UPDATE campaign_contacts
                    SET status = :s, enrichment_gaps = :g
                    WHERE id = :id
                """),
                {"s": new_status, "g": json.dumps(gaps), "id": cc_id},
            )

        result_contacts.append(
            {
                "campaign_contact_id": str(cc_id),
                "contact_id": str(contact_id),
                "full_name": ((first_name or "") + " " + (last_name or "")).strip(),
                "company_name": company_name,
                "ready": is_ready,
                "gaps": gaps,
            }
        )

    db.session.commit()

    return jsonify(
        {
            "contacts": result_contacts,
            "summary": {
                "total": len(contacts),
                "ready": ready_count,
                "needs_enrichment": needs_enrichment_count,
            },
        }
    )


# ── Generation Pipeline ──────────────────────────────────


@campaigns_bp.route("/api/campaigns/<campaign_id>/cost-estimate", methods=["POST"])
@require_role("editor")
def generation_cost_estimate(campaign_id):
    """Estimate the cost of generating messages for this campaign."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text("""
            SELECT template_config, total_contacts
            FROM campaigns WHERE id = :id AND tenant_id = :t
        """),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Campaign not found"}), 404

    template_config = _parse_jsonb(row[0]) or []
    total_contacts = row[1] or 0

    if total_contacts == 0:
        return jsonify({"error": "No contacts in campaign"}), 400

    step_count = CampaignStep.query.filter_by(campaign_id=campaign_id).count()
    enabled = [s for s in template_config if s.get("enabled")]
    if step_count == 0 and not enabled:
        return jsonify({"error": "No enabled message steps"}), 400

    estimate = estimate_generation_cost(
        template_config, total_contacts, campaign_id=campaign_id, tenant_id=tenant_id
    )

    # Enrichment gap analysis — find contacts missing key stages
    gap_rows = db.session.execute(
        db.text("""
            SELECT
                cc.contact_id,
                ct.first_name, ct.last_name, ct.company_id,
                (SELECT COUNT(*) FROM entity_stage_completions esc
                 WHERE esc.entity_id = ct.company_id
                   AND esc.entity_type = 'company'
                   AND esc.stage = 'l2_deep_research'
                   AND esc.status = 'completed'
                   AND esc.tenant_id = :t
                ) AS l2_done,
                (SELECT COUNT(*) FROM entity_stage_completions esc
                 WHERE esc.entity_id = cc.contact_id
                   AND esc.entity_type = 'contact'
                   AND esc.stage = 'person_enrichment'
                   AND esc.status = 'completed'
                   AND esc.tenant_id = :t
                ) AS person_done
            FROM campaign_contacts cc
            JOIN contacts ct ON cc.contact_id = ct.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
              AND cc.status NOT IN ('excluded')
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    unenriched = []
    for r in gap_rows:
        missing = []
        if r[4] == 0:
            missing.append("l2_deep_research")
        if r[5] == 0:
            missing.append("person_enrichment")
        if missing:
            name = f"{r[1] or ''} {r[2] or ''}".strip() or "Unknown"
            unenriched.append(
                {
                    "contact_id": str(r[0]),
                    "name": name,
                    "missing_stages": missing,
                }
            )

    enriched_count = len(gap_rows) - len(unenriched)
    estimate["enrichment_gaps"] = {
        "total_contacts": len(gap_rows),
        "enriched_contacts": enriched_count,
        "unenriched_contacts": len(unenriched),
        "gap_details": unenriched,
    }

    return jsonify(estimate)


@campaigns_bp.route("/api/campaigns/<campaign_id>/generate", methods=["POST"])
@require_role("editor")
def start_campaign_generation(campaign_id):
    """Start message generation for a campaign (background)."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text(
            "SELECT status, total_contacts, template_config FROM campaigns WHERE id = :id AND tenant_id = :t"
        ),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Campaign not found"}), 404

    current_status = row[0] or "draft"
    total_contacts = row[1] or 0
    template_config = _parse_jsonb(row[2]) or []

    # Auto-migrate template_config to campaign_steps if no steps exist
    existing_steps = CampaignStep.query.filter_by(campaign_id=campaign_id).count()
    if existing_steps == 0 and template_config:
        tpl_steps = (
            template_config
            if isinstance(template_config, list)
            else json.loads(template_config or "[]")
        )
        for i, ts in enumerate([s for s in tpl_steps if s.get("enabled")], 1):
            step = CampaignStep(
                campaign_id=campaign_id,
                tenant_id=str(tenant_id),
                position=i,
                channel=ts.get("channel", "linkedin_message"),
                day_offset=ts.get("day_offset", 0),
                label=ts.get("label", f"Step {i}"),
                config={
                    k: v
                    for k, v in ts.items()
                    if k not in ("channel", "day_offset", "label", "step", "enabled")
                },
            )
            db.session.add(step)
        db.session.commit()

    # Must be in ready status to start generation
    if current_status != "ready":
        return jsonify(
            {
                "error": f"Campaign must be in 'ready' status to generate (current: {current_status})"
            }
        ), 400

    if total_contacts == 0:
        return jsonify({"error": "No contacts in campaign"}), 400

    step_count = CampaignStep.query.filter_by(campaign_id=campaign_id).count()
    enabled = [s for s in template_config if s.get("enabled")]
    if step_count == 0 and not enabled:
        return jsonify({"error": "No enabled message steps"}), 400

    # Handle skip_unenriched flag
    body = request.get_json(silent=True) or {}
    skip_unenriched = body.get("skip_unenriched", False)

    if skip_unenriched:
        # Exclude contacts without completed enrichment stages
        enriched_ids = db.session.execute(
            db.text("""
                SELECT cc.contact_id
                FROM campaign_contacts cc
                JOIN contacts ct ON cc.contact_id = ct.id
                WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                  AND cc.status NOT IN ('excluded')
                  AND EXISTS (
                      SELECT 1 FROM entity_stage_completions esc
                      WHERE esc.entity_id = cc.contact_id
                        AND esc.entity_type = 'contact'
                        AND esc.stage = 'person_enrichment'
                        AND esc.status = 'completed'
                        AND esc.tenant_id = :t
                  )
            """),
            {"cid": campaign_id, "t": tenant_id},
        ).fetchall()

        enriched_contact_ids = [str(r[0]) for r in enriched_ids]

        if not enriched_contact_ids:
            return jsonify({"error": "No enriched contacts to generate for"}), 400

        # Exclude unenriched contacts
        db.session.execute(
            db.text("""
                UPDATE campaign_contacts
                SET status = 'excluded'
                WHERE campaign_id = :cid AND tenant_id = :t
                  AND contact_id NOT IN (SELECT unnest(string_to_array(:ids, ',')))
                  AND status NOT IN ('excluded')
            """),
            {"cid": campaign_id, "t": tenant_id, "ids": ",".join(enriched_contact_ids)},
        )

        # Update total_contacts
        total_contacts = len(enriched_contact_ids)
        db.session.execute(
            db.text(
                "UPDATE campaigns SET total_contacts = :tc WHERE id = :id AND tenant_id = :t"
            ),
            {"tc": total_contacts, "id": campaign_id, "t": tenant_id},
        )

    # Transition to generating
    db.session.execute(
        db.text("""
            UPDATE campaigns
            SET status = 'generating', generation_started_at = CURRENT_TIMESTAMP,
                generated_count = 0, generation_cost = 0
            WHERE id = :id
        """),
        {"id": campaign_id},
    )
    db.session.commit()

    # Get user_id from auth context
    user_id = getattr(g, "user_id", None)

    # Start background generation
    start_generation(current_app._get_current_object(), campaign_id, tenant_id, user_id)

    return jsonify({"ok": True, "status": "generating"})


@campaigns_bp.route("/api/campaigns/<campaign_id>/generation-status", methods=["GET"])
@require_auth
def generation_status(campaign_id):
    """Poll generation progress for a campaign."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text("""
            SELECT status, total_contacts, generated_count, generation_cost,
                   generation_started_at, generation_completed_at,
                   template_config
            FROM campaigns WHERE id = :id AND tenant_id = :t
        """),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Campaign not found"}), 404

    total = row[1] or 0
    generated = row[2] or 0
    template_config = _parse_jsonb(row[6]) or []

    # Count per-contact statuses
    contact_stats = db.session.execute(
        db.text("""
            SELECT status, COUNT(*) FROM campaign_contacts
            WHERE campaign_id = :id AND tenant_id = :t
            GROUP BY status
        """),
        {"id": campaign_id, "t": tenant_id},
    ).fetchall()
    status_counts = {r[0]: r[1] for r in contact_stats}

    # Channel breakdown: count generated messages per channel vs target
    enabled_steps = [s for s in template_config if s.get("enabled")]
    channels = {}
    if enabled_steps and total > 0:
        # Target per channel = contacts * steps with that channel
        channel_step_counts = {}
        for step in enabled_steps:
            ch = step.get("channel", "unknown")
            channel_step_counts[ch] = channel_step_counts.get(ch, 0) + 1

        for ch, step_count in channel_step_counts.items():
            channels[ch] = {"generated": 0, "target": total * step_count}

        # Count actual generated messages per channel
        msg_channel_stats = db.session.execute(
            db.text("""
                SELECT m.channel, COUNT(*)
                FROM messages m
                JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
                WHERE cc.campaign_id = :id AND cc.tenant_id = :t
                    AND m.status != 'failed'
                GROUP BY m.channel
            """),
            {"id": campaign_id, "t": tenant_id},
        ).fetchall()
        for ch, cnt in msg_channel_stats:
            if ch in channels:
                channels[ch]["generated"] = cnt
            else:
                channels[ch] = {"generated": cnt, "target": cnt}

    # Failed contacts with error details
    failed_rows = db.session.execute(
        db.text("""
            SELECT cc.contact_id, ct.first_name, ct.last_name, cc.error
            FROM campaign_contacts cc
            JOIN contacts ct ON cc.contact_id = ct.id
            WHERE cc.campaign_id = :id AND cc.tenant_id = :t
                AND cc.status = 'failed'
        """),
        {"id": campaign_id, "t": tenant_id},
    ).fetchall()
    failed_contacts = [
        {
            "contact_id": str(r[0]),
            "name": ((r[1] or "") + " " + (r[2] or "")).strip(),
            "error": r[3] or "Generation error",
        }
        for r in failed_rows
    ]

    return jsonify(
        {
            "status": display_campaign_status(row[0] or "draft"),
            "total_contacts": total,
            "generated_count": generated,
            "generation_cost": float(row[3]) if row[3] else 0,
            "progress_pct": round(generated / total * 100) if total > 0 else 0,
            "generation_started_at": _format_ts(row[4]),
            "generation_completed_at": _format_ts(row[5]),
            "contact_statuses": status_counts,
            "channels": channels,
            "failed_contacts": failed_contacts,
        }
    )


@campaigns_bp.route("/api/campaigns/<campaign_id>/generate", methods=["DELETE"])
@require_role("editor")
def cancel_campaign_generation(campaign_id):
    """Cancel an active generation by setting the cancelled flag.

    The background generator checks this flag between messages and stops
    gracefully. Campaign status reverts to 'ready' so generation can be
    restarted later.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    row = db.session.execute(
        db.text(
            "SELECT status, generation_config FROM campaigns WHERE id = :id AND tenant_id = :t"
        ),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not row:
        return jsonify({"error": "Campaign not found"}), 404

    current_status = row[0] or "draft"
    if current_status != "generating":
        return jsonify(
            {"error": f"Campaign is not generating (current: {current_status})"}
        ), 400

    # Set cancelled flag in generation_config so the background thread stops
    gen_config = _parse_jsonb(row[1]) or {}
    gen_config["cancelled"] = True

    db.session.execute(
        db.text("""
            UPDATE campaigns
            SET generation_config = :gc, status = 'ready'
            WHERE id = :id AND tenant_id = :t
        """),
        {
            "gc": json.dumps(gen_config),
            "id": campaign_id,
            "t": tenant_id,
        },
    )
    db.session.commit()

    return jsonify({"ok": True, "status": "cancelled"})


# --- T6: Disqualify contact ---


@campaigns_bp.route("/api/campaigns/<campaign_id>/disqualify-contact", methods=["POST"])
@require_role("editor")
def disqualify_contact(campaign_id):
    """Disqualify a contact from a campaign (campaign-only or global)."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    contact_id = body.get("contact_id")
    scope = body.get("scope", "campaign")
    reason = body.get("reason")

    if not contact_id:
        return jsonify({"error": "contact_id required"}), 400
    if scope not in ("campaign", "global"):
        return jsonify({"error": "scope must be 'campaign' or 'global'"}), 400

    # Verify campaign_contact exists
    cc = db.session.execute(
        db.text("""
            SELECT id FROM campaign_contacts
            WHERE campaign_id = :cid AND contact_id = :ctid AND tenant_id = :t
        """),
        {"cid": campaign_id, "ctid": contact_id, "t": tenant_id},
    ).fetchone()
    if not cc:
        return jsonify({"error": "Contact not in this campaign"}), 404

    cc_id = cc[0]

    # Campaign exclusion: set campaign_contact to excluded, reject all messages
    db.session.execute(
        db.text(
            "UPDATE campaign_contacts SET status = 'excluded' WHERE id = :id AND tenant_id = :t"
        ),
        {"id": cc_id, "t": tenant_id},
    )
    result = db.session.execute(
        db.text("""
            UPDATE messages
            SET status = 'rejected',
                review_notes = 'Contact excluded from campaign',
                updated_at = CURRENT_TIMESTAMP
            WHERE campaign_contact_id = :cc_id AND status = 'draft'
        """),
        {"cc_id": cc_id},
    )
    messages_rejected = result.rowcount

    # Global disqualification
    if scope == "global":
        db.session.execute(
            db.text("""
                UPDATE contacts
                SET is_disqualified = true,
                    disqualified_at = CURRENT_TIMESTAMP,
                    disqualified_reason = :reason
                WHERE id = :id AND tenant_id = :t
            """),
            {"id": contact_id, "t": tenant_id, "reason": reason},
        )

    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "contact_id": contact_id,
            "scope": scope,
            "messages_rejected": messages_rejected,
        }
    )


# --- T7: Review summary + approval gate ---


@campaigns_bp.route("/api/campaigns/<campaign_id>/review-summary", methods=["GET"])
@require_auth
def review_summary(campaign_id):
    """Get review progress and approval readiness for a campaign."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Message status counts
    msg_stats = db.session.execute(
        db.text("""
            SELECT m.status, COUNT(*)
            FROM messages m
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
            GROUP BY m.status
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()
    counts = {r[0]: r[1] for r in msg_stats}

    total = sum(counts.values())
    approved = counts.get("approved", 0)
    rejected = counts.get("rejected", 0)
    draft = counts.get("draft", 0)

    # Excluded contacts
    excluded = db.session.execute(
        db.text("""
            SELECT COUNT(*) FROM campaign_contacts
            WHERE campaign_id = :cid AND tenant_id = :t AND status = 'excluded'
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).scalar()

    active_contacts = db.session.execute(
        db.text("""
            SELECT COUNT(DISTINCT cc.contact_id)
            FROM campaign_contacts cc
            JOIN messages m ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                AND cc.status != 'excluded' AND m.status = 'approved'
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).scalar()

    # Breakdown by channel
    channel_stats = db.session.execute(
        db.text("""
            SELECT m.channel, m.status, COUNT(*)
            FROM messages m
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
            GROUP BY m.channel, m.status
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    by_channel = {}
    for ch, st, cnt in channel_stats:
        if ch not in by_channel:
            by_channel[ch] = {"approved": 0, "rejected": 0, "draft": 0}
        by_channel[ch][st] = by_channel[ch].get(st, 0) + cnt

    can_approve = draft == 0 and total > 0
    pending_reason = None
    if draft > 0:
        pending_reason = f"{draft} messages pending review"
    elif total == 0:
        pending_reason = "No messages generated"

    return jsonify(
        {
            "total": total,
            "approved": approved,
            "rejected": rejected,
            "draft": draft,
            "excluded_contacts": excluded,
            "active_contacts": active_contacts,
            "by_channel": by_channel,
            "can_approve_outreach": can_approve,
            "pending_reason": pending_reason,
        }
    )


# --- T8: Review queue ---


@campaigns_bp.route("/api/campaigns/<campaign_id>/review-queue", methods=["GET"])
@require_auth
def review_queue(campaign_id):
    """Get ordered list of messages with full context for focused review."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Query params
    status_filter = request.args.get("status", "draft")
    channel_filter = request.args.get("channel")
    step_filter = request.args.get("step")

    where = ["cc.campaign_id = :cid", "cc.tenant_id = :t", "cc.status != 'excluded'"]
    params = {"cid": campaign_id, "t": tenant_id}

    if status_filter:
        where.append("m.status = :status")
        params["status"] = status_filter
    if channel_filter:
        where.append("m.channel = :channel")
        params["channel"] = channel_filter
    if step_filter:
        try:
            params["step"] = int(step_filter)
        except (ValueError, TypeError):
            return jsonify({"error": "step must be an integer"}), 400
        where.append("m.sequence_step = :step")

    where_clause = " AND ".join(where)

    rows = db.session.execute(
        db.text(f"""
            SELECT
                m.id, m.channel, m.sequence_step, m.variant,
                m.subject, m.body, m.status, m.tone, m.language,
                m.generation_cost_usd, m.review_notes, m.approved_at,
                m.original_body, m.original_subject, m.edit_reason,
                m.edit_reason_text, m.regen_count, m.regen_config,
                ct.id AS contact_id, ct.first_name, ct.last_name,
                ct.job_title, ct.email_address, ct.linkedin_url,
                ct.contact_score, ct.icp_fit, ct.seniority_level,
                ct.department, ct.location_country,
                co.id AS company_id, co.name AS company_name,
                co.domain, co.tier, co.industry, co.hq_country,
                co.summary AS company_summary, co.status AS company_status,
                m.label, m.campaign_contact_id
            FROM messages m
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            JOIN contacts ct ON m.contact_id = ct.id
            LEFT JOIN companies co ON ct.company_id = co.id
            WHERE {where_clause}
            ORDER BY ct.contact_score DESC NULLS LAST,
                     ct.id,
                     m.sequence_step ASC
        """),
        params,
    ).fetchall()

    # Queue stats (all messages in campaign, not filtered)
    stats = db.session.execute(
        db.text("""
            SELECT m.status, COUNT(*)
            FROM messages m
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                AND cc.status != 'excluded'
            GROUP BY m.status
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()
    stat_counts = {r[0]: r[1] for r in stats}

    total_count = len(rows)
    messages = []
    for idx, r in enumerate(rows):
        regen_config = r[17]
        if isinstance(regen_config, str):
            try:
                regen_config = json.loads(regen_config)
            except (json.JSONDecodeError, TypeError):
                regen_config = None

        messages.append(
            {
                "position": idx + 1,
                "total": total_count,
                "message": {
                    "id": str(r[0]),
                    "channel": r[1],
                    "sequence_step": r[2],
                    "variant": (r[3] or "a").upper(),
                    "subject": r[4],
                    "body": r[5],
                    "status": r[6],
                    "tone": r[7],
                    "language": r[8],
                    "generation_cost": float(r[9]) if r[9] else None,
                    "review_notes": r[10],
                    "approved_at": _format_ts(r[11]),
                    "original_body": r[12],
                    "original_subject": r[13],
                    "edit_reason": r[14],
                    "edit_reason_text": r[15],
                    "regen_count": r[16] or 0,
                    "regen_config": regen_config,
                    "label": r[37],
                    "campaign_contact_id": str(r[38]),
                },
                "contact": {
                    "id": str(r[18]),
                    "first_name": r[19],
                    "last_name": r[20],
                    "full_name": ((r[19] or "") + " " + (r[20] or "")).strip(),
                    "job_title": r[21],
                    "email_address": r[22],
                    "linkedin_url": r[23],
                    "contact_score": r[24],
                    "icp_fit": r[25],
                    "seniority_level": r[26],
                    "department": r[27],
                    "location_country": r[28],
                },
                "company": {
                    "id": str(r[29]) if r[29] else None,
                    "name": r[30],
                    "domain": r[31],
                    "tier": display_tier(r[32]),
                    "industry": r[33],
                    "hq_country": r[34],
                    "summary": r[35],
                    "status": display_status(r[36]),
                }
                if r[29]
                else None,
            }
        )

    return jsonify(
        {
            "queue": messages,
            "stats": {
                "total": sum(stat_counts.values()),
                "approved": stat_counts.get("approved", 0),
                "rejected": stat_counts.get("rejected", 0),
                "draft": stat_counts.get("draft", 0),
            },
        }
    )


# --- Batch message actions (approve/reject) ---


@campaigns_bp.route(
    "/api/campaigns/<campaign_id>/messages/batch-action", methods=["POST"]
)
@require_role("editor")
def batch_message_action(campaign_id):
    """Batch approve or reject messages belonging to a campaign.

    Body: { message_ids: string[], action: "approve"|"reject", reason?: string }
    Response: { updated: N, action: "approve"|"reject", errors: [] }
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    message_ids = body.get("message_ids", [])
    action = body.get("action")
    reason = body.get("reason")

    # Validate inputs
    if not message_ids:
        return jsonify({"error": "message_ids is required and cannot be empty"}), 400
    if action not in ("approve", "reject"):
        return jsonify({"error": "action must be 'approve' or 'reject'"}), 400

    # Verify campaign exists and belongs to tenant
    campaign = db.session.execute(
        db.text("SELECT id FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    # Verify all message_ids belong to this campaign and tenant
    id_placeholders = ", ".join(f":mid_{i}" for i in range(len(message_ids)))
    id_params = {f"mid_{i}": v for i, v in enumerate(message_ids)}
    id_params["cid"] = campaign_id
    id_params["t"] = tenant_id

    valid_rows = db.session.execute(
        db.text(f"""
            SELECT m.id FROM messages m
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                AND m.id IN ({id_placeholders})
        """),
        id_params,
    ).fetchall()
    valid_ids = {str(r[0]) for r in valid_rows}

    # Collect errors for invalid IDs
    errors = []
    for mid in message_ids:
        if mid not in valid_ids:
            errors.append(
                {"message_id": mid, "error": "Message not found in this campaign"}
            )

    if not valid_ids:
        return (
            jsonify(
                {
                    "updated": 0,
                    "action": action,
                    "errors": errors,
                }
            ),
            400,
        )

    # Build the update using individual placeholders (SQLite + PG compatible)
    valid_list = list(valid_ids)
    upd_placeholders = ", ".join(f":uid_{i}" for i in range(len(valid_list)))
    update_params = {f"uid_{i}": v for i, v in enumerate(valid_list)}
    update_params["t"] = tenant_id

    if action == "approve":
        db.session.execute(
            db.text(f"""
                UPDATE messages
                SET status = 'approved',
                    approved_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = :t AND id IN ({upd_placeholders})
            """),
            update_params,
        )
    else:  # reject
        update_params["reason"] = reason or ""
        db.session.execute(
            db.text(f"""
                UPDATE messages
                SET status = 'rejected',
                    review_notes = :reason,
                    updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = :t AND id IN ({upd_placeholders})
            """),
            update_params,
        )

    db.session.commit()

    return jsonify(
        {
            "updated": len(valid_ids),
            "action": action,
            "errors": errors,
        }
    )


# --- Email send + status ---


@campaigns_bp.route("/api/campaigns/<campaign_id>/send-emails", methods=["POST"])
@require_role("editor")
def send_emails(campaign_id):
    """Send approved email messages for a campaign via Resend or Gmail.

    Checks sender_config.send_via to determine the backend:
    - "gmail": sends via user's Gmail account (requires OAuth connection with send scope)
    - "resend" (default): sends via Resend API

    Body: { confirm?: boolean }
    Response: { queued_count: N, sender: { from_email, from_name }, send_via: str }
    """
    import threading

    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign or str(campaign.tenant_id) != str(tenant_id):
        return jsonify({"error": "Campaign not found"}), 404

    # Validate sender_config
    sender_config = campaign.sender_config
    if isinstance(sender_config, str):
        sender_config = json.loads(sender_config)
    sender_config = sender_config or {}

    send_via = sender_config.get("send_via", "resend")

    if send_via == "gmail":
        # Gmail path: validate OAuth connection
        from ..models import OAuthConnection

        oauth_connection_id = sender_config.get("oauth_connection_id")
        if not oauth_connection_id:
            return jsonify(
                {
                    "error": "Gmail sending requires an OAuth connection. Connect your Gmail account first."
                }
            ), 400

        oauth_conn = db.session.get(OAuthConnection, oauth_connection_id)
        if not oauth_conn or str(oauth_conn.tenant_id) != str(tenant_id):
            return jsonify({"error": "OAuth connection not found"}), 404
        if oauth_conn.status != "active":
            return jsonify(
                {
                    "error": f"Gmail connection is {oauth_conn.status}. Please reconnect your Gmail account."
                }
            ), 400

        from ..services.google_oauth import has_send_scope

        if not has_send_scope(oauth_conn):
            return jsonify(
                {
                    "error": "Gmail connection does not have send permission. Please reconnect with send access."
                }
            ), 403

        from_email = oauth_conn.provider_email
        from_name = sender_config.get("from_name")
    else:
        # Resend path: validate from_email and API key
        from_email = sender_config.get("from_email")
        from_name = sender_config.get("from_name")
        if not from_email:
            return jsonify(
                {
                    "error": "Campaign sender_config is missing from_email. Configure sender identity first."
                }
            ), 400

        from ..models import Tenant as TenantModel

        tenant = db.session.get(TenantModel, tenant_id)
        tenant_settings = tenant.settings if tenant else {}
        if isinstance(tenant_settings, str):
            tenant_settings = json.loads(tenant_settings)
        tenant_settings = tenant_settings or {}

        if not tenant_settings.get("resend_api_key"):
            return jsonify(
                {"error": "Tenant settings missing resend_api_key. Contact your admin."}
            ), 400

    # Count approved email messages not yet sent
    approved_count = db.session.execute(
        db.text("""
            SELECT COUNT(*) FROM messages m
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                AND m.status = 'approved' AND m.channel = 'email'
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).scalar()

    if approved_count == 0:
        return jsonify({"error": "No approved email messages to send"}), 400

    # Pre-flight quota check (Resend only — Gmail checks internally)
    if send_via != "gmail":
        tenant = db.session.get(Tenant, tenant_id)
        t_settings = tenant.settings if tenant else {}
        if isinstance(t_settings, str):
            t_settings = json.loads(t_settings)
        t_settings = t_settings or {}
        quota = get_quota_status(str(tenant_id), t_settings)
        if quota["daily_remaining"] == 0:
            return jsonify(
                {
                    "error": (
                        f"Daily send limit reached ({quota['daily_limit']} emails). "
                        f"Try again tomorrow or increase tenant send_limits."
                    ),
                    "quota": quota,
                }
            ), 429
        if quota["hourly_remaining"] == 0:
            return jsonify(
                {
                    "error": (
                        f"Hourly send limit reached ({quota['hourly_limit']} emails). "
                        f"Try again next hour."
                    ),
                    "quota": quota,
                }
            ), 429

    # Start background send
    app = current_app._get_current_object()
    send_fn = (
        send_campaign_emails_gmail if send_via == "gmail" else send_campaign_emails
    )

    def _run_send():
        with app.app_context():
            try:
                result = send_fn(campaign_id, str(tenant_id))
                logger.info(
                    "Send completed for campaign %s (via %s): %s",
                    campaign_id,
                    send_via,
                    result,
                )
            except Exception:
                logger.exception("Send failed for campaign %s", campaign_id)

    thread = threading.Thread(target=_run_send, daemon=True)
    thread.start()

    response = {
        "queued_count": approved_count,
        "send_via": send_via,
        "sender": {
            "from_email": from_email,
            "from_name": from_name,
        },
    }
    if send_via != "gmail":
        response["quota"] = quota  # noqa: F821 — quota defined in resend branch above

    return jsonify(response)


@campaigns_bp.route("/api/campaigns/<campaign_id>/send-status", methods=["GET"])
@require_auth
def send_status(campaign_id):
    """Get email send status for a campaign.

    Response: { total, queued, sent, delivered, failed, bounced }
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify campaign exists
    campaign = db.session.execute(
        db.text("SELECT id FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    status = get_send_status(campaign_id, str(tenant_id))
    return jsonify(status)


# --- Queue LinkedIn messages for Chrome extension ---


@campaigns_bp.route("/api/campaigns/<campaign_id>/queue-linkedin", methods=["POST"])
@require_role("editor")
def queue_linkedin(campaign_id):
    """Queue approved LinkedIn messages for the Chrome extension to send.

    Finds all approved LinkedIn messages (linkedin_connect, linkedin_message)
    in this campaign and creates LinkedInSendQueue entries for each.
    Idempotent: re-queuing skips messages already in the queue.

    Returns: { queued_count: N, by_owner: { "Alice": 5, "Bob": 3 } }
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify campaign exists and belongs to tenant
    campaign = db.session.execute(
        db.text("SELECT id, status FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    # Load approved LinkedIn messages for this campaign
    rows = db.session.execute(
        db.text("""
            SELECT m.id, m.body, m.channel, m.contact_id, m.owner_id,
                   ct.linkedin_url, ct.first_name, ct.last_name
            FROM messages m
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            JOIN contacts ct ON m.contact_id = ct.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                AND m.status = 'approved'
                AND m.channel IN ('linkedin_connect', 'linkedin_message')
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    if not rows:
        return jsonify({"queued_count": 0, "by_owner": {}})

    # Get already-queued message IDs (idempotency)
    message_ids = [str(r[0]) for r in rows]
    mid_placeholders = ", ".join(f":mid_{i}" for i in range(len(message_ids)))
    mid_params = {f"mid_{i}": v for i, v in enumerate(message_ids)}
    mid_params["t"] = tenant_id
    existing = db.session.execute(
        db.text(f"""
            SELECT message_id FROM linkedin_send_queue
            WHERE tenant_id = :t AND message_id IN ({mid_placeholders})
        """),
        mid_params,
    ).fetchall()
    existing_message_ids = {str(r[0]) for r in existing}

    # Map action_type from channel name
    channel_to_action = {
        "linkedin_connect": "connection_request",
        "linkedin_message": "message",
    }

    # Load owner names for the response
    owner_ids = list({str(r[4]) for r in rows if r[4]})
    owner_names = {}
    if owner_ids:
        oid_placeholders = ", ".join(f":oid_{i}" for i in range(len(owner_ids)))
        oid_params = {f"oid_{i}": v for i, v in enumerate(owner_ids)}
        owner_rows = db.session.execute(
            db.text(f"SELECT id, name FROM owners WHERE id IN ({oid_placeholders})"),
            oid_params,
        ).fetchall()
        owner_names = {str(r[0]): r[1] for r in owner_rows}

    queued_count = 0
    by_owner = {}

    for r in rows:
        msg_id = r[0]
        body = r[1]
        channel = r[2]
        contact_id = r[3]
        owner_id = r[4]
        linkedin_url = r[5]

        if str(msg_id) in existing_message_ids:
            continue

        if not owner_id:
            continue

        action_type = channel_to_action.get(channel, "message")

        entry = LinkedInSendQueue(
            tenant_id=str(tenant_id),
            message_id=str(msg_id),
            contact_id=str(contact_id),
            owner_id=str(owner_id),
            action_type=action_type,
            linkedin_url=linkedin_url,
            body=body,
            status="queued",
        )
        db.session.add(entry)
        queued_count += 1

        owner_name = owner_names.get(str(owner_id), str(owner_id))
        by_owner[owner_name] = by_owner.get(owner_name, 0) + 1

    db.session.commit()

    return jsonify({"queued_count": queued_count, "by_owner": by_owner})


# --- T8: Campaign analytics aggregation ---


@campaigns_bp.route("/api/campaigns/<campaign_id>/analytics", methods=["GET"])
@require_role("viewer")
def campaign_analytics(campaign_id):
    """Return aggregated campaign metrics for the OutreachTab / CampaignAnalytics component.

    Aggregates message counts, sending stats, contact stats, cost, and timeline.

    Delegates the aggregation work to :func:`_compute_campaign_analytics`
    so the REST endpoint and the SSE stream endpoint (BL-1039) return
    identical shapes and stay on the same SQL path. Both call-sites
    apply the BL-1026/BL-1029 preview+superseded filtering through the
    shared helper.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    result = _compute_campaign_analytics(campaign_id, tenant_id)
    if result is None:
        return jsonify({"error": "Campaign not found"}), 404

    return jsonify(result)


# ─── Time-series analytics (BL-1037) ────────────────────────────────────
# Valid query parameter values for the timeseries endpoint. Kept at
# module scope so tests / other modules can inspect the contract.
_TIMESERIES_RANGES = {"24h", "7d", "30d", "all"}
_TIMESERIES_BUCKETS = {"hour", "day"}
# How far back to look when range=all and the campaign has no events yet.
# Anything older than this is treated as "the beginning of time" for
# bucket skeleton generation, so we don't materialise years of zero rows.
_TIMESERIES_ALL_FALLBACK_DAYS = 30


def _timeseries_since(range_val, oldest_event_at, now):
    """Compute the window start timestamp for the requested range."""
    if range_val == "24h":
        return now - timedelta(hours=24)
    if range_val == "7d":
        return now - timedelta(days=7)
    if range_val == "30d":
        return now - timedelta(days=30)
    # range == "all": span the campaign's whole lifetime (or a sensible
    # fallback when no events exist yet).
    if oldest_event_at is None:
        return now - timedelta(days=_TIMESERIES_ALL_FALLBACK_DAYS)
    return _coerce_aware(oldest_event_at)


def _coerce_aware(ts):
    """Coerce a SQL timestamp (datetime or ISO string) to a UTC-aware datetime.

    SQLite stores ``DateTime(timezone=True)`` columns as strings; PostgreSQL
    returns ``datetime`` objects. This helper normalises both paths so
    bucketing logic can assume tz-aware UTC datetimes.
    """
    if ts is None:
        return None
    if isinstance(ts, str):
        # SQLite typically emits 'YYYY-MM-DD HH:MM:SS[.ffffff]' or ISO-8601.
        text = ts.strip()
        # Be tolerant of trailing 'Z' and '+00:00' suffixes.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            # Fallback: drop sub-second / tz decoration and retry.
            dt = datetime.fromisoformat(text.split(".")[0])
    else:
        dt = ts
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _truncate_bucket(dt, bucket):
    """Floor a UTC datetime to the start of its bucket."""
    dt = _coerce_aware(dt)
    if bucket == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    # day
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _iter_buckets(since, until, bucket):
    """Yield bucket start timestamps from ``since`` through ``until`` inclusive."""
    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    current = _truncate_bucket(since, bucket)
    end = _truncate_bucket(until, bucket)
    # Safety cap: avoid pathological outputs (>5 years daily, >45 days hourly).
    max_buckets = 45 * 24 if bucket == "hour" else 365 * 5
    count = 0
    while current <= end and count < max_buckets:
        yield current
        current = current + step
        count += 1


def _iso_z(dt):
    """Render a UTC datetime as ISO-8601 with trailing Z (not +00:00)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # isoformat() yields +00:00; normalise to Z for contract.
    return dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


@campaigns_bp.route(
    "/api/campaigns/<campaign_id>/analytics/timeseries", methods=["GET"]
)
@require_role("viewer")
def campaign_analytics_timeseries(campaign_id):
    """Time-bucketed mail-event counts for a campaign (BL-1037).

    Buckets counts of sent / delivered / opened / clicked / bounced /
    unsubscribed events across the requested range. Empty buckets are
    zero-filled so the front-end can render a continuous series without
    special-casing gaps.

    Query params:
      range: 24h | 7d (default) | 30d | all
      bucket: hour | day (auto-selected when omitted: 24h→hour, else→day)

    Tenant isolation: the campaign's tenant is verified first; cross-tenant
    IDs return 404 (not 403) to avoid existence disclosure.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # ── Validate query parameters ───────────────────────────────────
    range_val = (request.args.get("range") or "7d").strip().lower()
    if range_val not in _TIMESERIES_RANGES:
        return jsonify(
            {
                "error": (
                    f"Invalid range '{range_val}'. "
                    f"Must be one of: {sorted(_TIMESERIES_RANGES)}"
                )
            }
        ), 400

    bucket_param = request.args.get("bucket")
    if bucket_param is None or bucket_param.strip() == "":
        bucket_val = "hour" if range_val == "24h" else "day"
    else:
        bucket_val = bucket_param.strip().lower()
        if bucket_val not in _TIMESERIES_BUCKETS:
            return jsonify(
                {
                    "error": (
                        f"Invalid bucket '{bucket_val}'. "
                        f"Must be one of: {sorted(_TIMESERIES_BUCKETS)}"
                    )
                }
            ), 400

    # ── Verify campaign belongs to tenant (404 on miss, not 403) ────
    campaign_exists = db.session.execute(
        db.text("SELECT 1 FROM campaigns WHERE id = :id AND tenant_id = :t LIMIT 1"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign_exists:
        return jsonify({"error": "Campaign not found"}), 404

    now = datetime.now(timezone.utc)

    # ── Fetch event timestamps ──────────────────────────────────────
    # We fetch just the six timestamp columns for rows in this campaign
    # (joined through messages → campaign_contacts) and bucket in Python.
    # This is portable across PG + SQLite (tests use SQLite), and fast
    # enough at current scale. A future optimisation is PG-side
    # `date_trunc` aggregation; at that point it would live behind a
    # dialect check.
    # Exclude superseded retry rows (BL-1029) so a message that bounced and
    # was later re-sent successfully only counts once per event type.
    # Exclude preview/test sends (BL-1026) so they never inflate analytics.
    rows = db.session.execute(
        db.text(
            """
            SELECT
                esl.sent_at,
                esl.delivered_at,
                esl.opened_at,
                esl.clicked_at,
                esl.bounced_at,
                esl.unsubscribed_at
            FROM email_send_log esl
            JOIN messages m ON esl.message_id = m.id
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid
              AND cc.tenant_id = :t
              AND esl.tenant_id = :t
              AND esl.kind != 'preview'
              AND esl.superseded_at IS NULL
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    # ── Determine window (range=all uses oldest event) ──────────────
    oldest = None
    for r in rows:
        for ts in r:
            ts_aware = _coerce_aware(ts)
            if ts_aware is None:
                continue
            if oldest is None or ts_aware < oldest:
                oldest = ts_aware
    since = _timeseries_since(range_val, oldest, now)

    # ── Build zero-filled bucket skeleton ───────────────────────────
    skeleton = {}
    for bucket_start in _iter_buckets(since, now, bucket_val):
        skeleton[bucket_start] = {
            "sent": 0,
            "delivered": 0,
            "opened": 0,
            "clicked": 0,
            "bounced": 0,
            "unsubscribed": 0,
        }

    # ── Fold events into buckets ────────────────────────────────────
    # Each send-log row contributes up to 6 event increments (one per
    # non-NULL timestamp column). Each increment is attributed to the
    # bucket containing its own timestamp.
    metric_fields = (
        ("sent_at", "sent"),
        ("delivered_at", "delivered"),
        ("opened_at", "opened"),
        ("clicked_at", "clicked"),
        ("bounced_at", "bounced"),
        ("unsubscribed_at", "unsubscribed"),
    )
    for r in rows:
        for idx, (_col, metric) in enumerate(metric_fields):
            ts_aware = _coerce_aware(r[idx])
            if ts_aware is None:
                continue
            if ts_aware < since or ts_aware > now:
                continue
            bucket_start = _truncate_bucket(ts_aware, bucket_val)
            if bucket_start not in skeleton:
                # Event falls outside the iter_buckets range (shouldn't
                # happen given the since/now clamp above, but guard).
                continue
            skeleton[bucket_start][metric] += 1

    # ── Emit in chronological order ─────────────────────────────────
    buckets = [
        {"bucket_start": _iso_z(ts), **counts}
        for ts, counts in sorted(skeleton.items(), key=lambda kv: kv[0])
    ]

    return jsonify(
        {
            "campaign_id": str(campaign_id),
            "range": range_val,
            "bucket": bucket_val,
            "buckets": buckets,
        }
    )


@campaigns_bp.route("/api/campaigns/<campaign_id>/recipients", methods=["GET"])
@require_role("viewer")
def campaign_recipients(campaign_id):
    """Per-recipient timeline for the OutreachTab drill-down (Phase 2).

    Returns one entry per CampaignContact, including any microsite partner
    token and a chronologically-sorted timeline of:

    - mail-event timestamps from EmailSendLog (sent / delivered / opened /
      clicked / bounced / unsubscribed)
    - microsite Activity events linked to the same contact (source =
      'microsite')

    Tenant-scoped via the existing JWT auth + tenant_id filter on the
    underlying queries (LEADGEN-04: data sourced from Leadgen DB only,
    no PostHog).
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify campaign exists and belongs to tenant.
    campaign_exists = db.session.execute(
        db.text("SELECT 1 FROM campaigns WHERE id = :id AND tenant_id = :t LIMIT 1"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign_exists:
        return jsonify({"error": "Campaign not found"}), 404

    # Per-recipient roster.
    rows = db.session.execute(
        db.text(
            """
            SELECT
                cc.id AS campaign_contact_id,
                cc.contact_id AS contact_id,
                cc.microsite_partner_token AS partner_token,
                ct.email_address AS email,
                COALESCE(NULLIF(TRIM(COALESCE(ct.first_name,'') || ' ' || COALESCE(ct.last_name,'')), ''), ct.email_address) AS name
            FROM campaign_contacts cc
            JOIN contacts ct ON ct.id = cc.contact_id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
            ORDER BY ct.email_address
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    recipients: list[dict] = []
    for r in rows:
        cc_id = r[0]
        contact_id = r[1]

        # Mail-event timeline from EmailSendLog (one row → up to 6 events).
        # BL-1026: exclude preview rows so a stakeholder preview does not
        # appear in the per-recipient drill-down as if it were a real
        # partner engagement event.
        mail_rows = db.session.execute(
            db.text(
                """
                SELECT
                    esl.sent_at, esl.delivered_at, esl.opened_at,
                    esl.clicked_at, esl.bounced_at, esl.unsubscribed_at
                FROM email_send_log esl
                JOIN messages m ON m.id = esl.message_id
                WHERE m.campaign_contact_id = :cc_id
                  AND esl.tenant_id = :t
                  AND esl.superseded_at IS NULL
                  AND esl.kind != 'preview'
                """
            ),
            {"cc_id": cc_id, "t": tenant_id},
        ).fetchall()

        events: list[dict] = []
        for er in mail_rows:
            for label, ts in zip(
                ("sent", "delivered", "opened", "clicked", "bounced", "unsubscribed"),
                er,
            ):
                if ts is not None:
                    events.append({"type": label, "ts": _format_ts(ts)})

        # Microsite Activity events for this contact.
        if contact_id is not None:
            act_rows = db.session.execute(
                db.text(
                    """
                    SELECT activity_name, occurred_at
                    FROM activities
                    WHERE contact_id = :cid AND tenant_id = :t
                      AND source = 'microsite'
                    ORDER BY occurred_at ASC
                    """
                ),
                {"cid": contact_id, "t": tenant_id},
            ).fetchall()
            for ar in act_rows:
                events.append(
                    {
                        "type": "microsite_activity",
                        "event": ar[0] or "",
                        "ts": _format_ts(ar[1]),
                    }
                )

        # Chronological sort (None timestamps drop to the end).
        events.sort(key=lambda e: e.get("ts") or "")

        recipients.append(
            {
                "campaign_contact_id": str(cc_id),
                "contact_id": str(contact_id) if contact_id else None,
                "email": r[3],
                "name": r[4],
                "microsite_partner_token": r[2],
                "timeline": events,
            }
        )

    return jsonify({"recipients": recipients})


# ── Bounces export (BL-1102) ───────────────────────────────────────────
# Returns the list of undeliverable recipients for a campaign, so an
# operator (or LCC client) can scrub them from future sends.
#
# CSV columns (locked — documented here so downstream consumers stay
# stable):
#   contact_id, email, first_name, last_name, company,
#   bounce_type, bounced_at, status, error_message
#
# Status filter: any send-log row where `bounced_at IS NOT NULL` OR
# `status IN ('bounced', 'failed')`, scoped to:
#   - the campaign (campaign_contacts.campaign_id)
#   - the tenant (email_send_log.tenant_id)
#   - non-superseded rows (BL-1029 — earlier failed attempts that later
#     succeeded are filtered out)
#   - non-preview rows (BL-1026 — stakeholder previews never appear)
#
# Tenant-scoped via the standard JWT auth path; viewer role is enough.


def _fetch_campaign_bounces(campaign_id, tenant_id):
    """Return (campaign_name, bounce_rows) or (None, None) if campaign missing.

    Shared by the JSON and CSV endpoints so both stay on the same SQL
    contract. Each row is a dict ready for JSON serialisation; the CSV
    formatter pulls the same fields in column order.
    """
    campaign_row = db.session.execute(
        db.text("SELECT name FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign_row:
        return None, None

    rows = db.session.execute(
        db.text(
            """
            SELECT
                ct.id AS contact_id,
                COALESCE(NULLIF(esl.to_email, ''), ct.email_address) AS email,
                ct.first_name,
                ct.last_name,
                co.name AS company_name,
                esl.bounce_type,
                esl.bounced_at,
                esl.status,
                esl.error AS error_message,
                esl.id AS send_log_id
            FROM email_send_log esl
            JOIN messages m ON m.id = esl.message_id
            JOIN campaign_contacts cc ON cc.id = m.campaign_contact_id
            JOIN contacts ct ON ct.id = cc.contact_id
            LEFT JOIN companies co ON co.id = ct.company_id
            WHERE cc.campaign_id = :cid
              AND esl.tenant_id = :t
              AND esl.superseded_at IS NULL
              AND esl.kind != 'preview'
              AND (
                  esl.bounced_at IS NOT NULL
                  OR esl.status IN ('bounced', 'failed')
              )
            ORDER BY COALESCE(esl.bounced_at, esl.created_at) DESC NULLS LAST,
                     esl.id
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    bounce_rows = []
    for r in rows:
        bounce_rows.append(
            {
                "contact_id": str(r[0]) if r[0] else None,
                "email": r[1] or "",
                "first_name": r[2] or "",
                "last_name": r[3] or "",
                "company": r[4] or "",
                "bounce_type": r[5] or "",
                "bounced_at": _format_ts(r[6]),
                "status": r[7] or "",
                "error_message": r[8] or "",
            }
        )

    return (campaign_row[0] or "campaign"), bounce_rows


@campaigns_bp.route("/api/campaigns/<campaign_id>/bounces", methods=["GET"])
@require_role("viewer")
def list_campaign_bounces(campaign_id):
    """JSON list of undeliverable recipients for the campaign.

    Used by the CampaignAnalytics surface so the UI can show a preview
    table + total count before the operator triggers the CSV download.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign_name, bounce_rows = _fetch_campaign_bounces(campaign_id, tenant_id)
    if campaign_name is None:
        return jsonify({"error": "Campaign not found"}), 404

    return jsonify(
        {
            "campaign_id": str(campaign_id),
            "campaign_name": campaign_name,
            "total": len(bounce_rows),
            "bounces": bounce_rows,
        }
    )


@campaigns_bp.route("/api/campaigns/<campaign_id>/bounces.csv", methods=["GET"])
@require_role("viewer")
def export_campaign_bounces_csv(campaign_id):
    """Download the campaign's undeliverable recipients as a CSV file.

    Sanitises every cell against spreadsheet formula injection. The
    filename is `bounces-{campaign-slug}-{YYYYMMDD}.csv`.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign_name, bounce_rows = _fetch_campaign_bounces(campaign_id, tenant_id)
    if campaign_name is None:
        return jsonify({"error": "Campaign not found"}), 404

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Contact ID",
            "Email",
            "First Name",
            "Last Name",
            "Company",
            "Bounce Type",
            "Bounced At",
            "Status",
            "Error Message",
        ]
    )
    for row in bounce_rows:
        writer.writerow(
            [
                _sanitize_csv_cell(row["contact_id"]),
                _sanitize_csv_cell(row["email"]),
                _sanitize_csv_cell(row["first_name"]),
                _sanitize_csv_cell(row["last_name"]),
                _sanitize_csv_cell(row["company"]),
                _sanitize_csv_cell(row["bounce_type"]),
                _sanitize_csv_cell(row["bounced_at"]),
                _sanitize_csv_cell(row["status"]),
                _sanitize_csv_cell(row["error_message"]),
            ]
        )

    csv_content = output.getvalue()
    output.close()

    safe_name = "".join(c for c in campaign_name if c.isalnum() or c in " -_").strip()
    slug = (safe_name or "campaign").lower().replace(" ", "-")
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"bounces-{slug}-{date_str}.csv"

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _sanitize_csv_cell(value):
    """Sanitize a cell value to prevent CSV formula injection.

    Dangerous prefixes (=, +, -, @, \\t, \\r) at the start of a cell
    can trigger formula execution in spreadsheet applications.
    """
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


@campaigns_bp.route("/api/campaigns/<campaign_id>/messages/export-csv", methods=["GET"])
@require_auth
def export_messages_csv(campaign_id):
    """Export approved campaign messages as CSV with formula injection sanitization."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify campaign belongs to tenant
    campaign_row = db.session.execute(
        db.text("SELECT name FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign_row:
        return jsonify({"error": "Campaign not found"}), 404

    campaign_name = campaign_row[0] or "campaign"

    # Optional status filter (default: approved only)
    status_filter = request.args.get("status", "approved")

    where = ["cc.campaign_id = :cid", "cc.tenant_id = :t", "cc.status != 'excluded'"]
    params = {"cid": campaign_id, "t": tenant_id}
    if status_filter != "all":
        where.append("m.status = :status")
        params["status"] = status_filter

    where_clause = " AND ".join(where)

    rows = db.session.execute(
        db.text(f"""
            SELECT
                ct.first_name, ct.last_name, ct.email_address,
                ct.linkedin_url, ct.job_title,
                co.name AS company_name, co.domain,
                m.channel, m.sequence_step, m.label,
                m.subject, m.body, m.status, m.tone,
                m.generation_cost_usd, m.approved_at
            FROM messages m
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            JOIN contacts ct ON m.contact_id = ct.id
            LEFT JOIN companies co ON ct.company_id = co.id
            WHERE {where_clause}
            ORDER BY ct.last_name, ct.first_name, m.sequence_step
        """),
        params,
    ).fetchall()

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        "First Name",
        "Last Name",
        "Email",
        "LinkedIn URL",
        "Job Title",
        "Company",
        "Domain",
        "Channel",
        "Step",
        "Label",
        "Subject",
        "Body",
        "Status",
        "Tone",
        "Cost (USD)",
        "Approved At",
    ]
    writer.writerow(headers)

    for r in rows:
        writer.writerow(
            [
                _sanitize_csv_cell(r[0]),  # first_name
                _sanitize_csv_cell(r[1]),  # last_name
                _sanitize_csv_cell(r[2]),  # email_address
                _sanitize_csv_cell(r[3]),  # linkedin_url
                _sanitize_csv_cell(r[4]),  # job_title
                _sanitize_csv_cell(r[5]),  # company_name
                _sanitize_csv_cell(r[6]),  # domain
                _sanitize_csv_cell(r[7]),  # channel
                r[8],  # sequence_step
                _sanitize_csv_cell(r[9]),  # label
                _sanitize_csv_cell(r[10]),  # subject
                _sanitize_csv_cell(r[11]),  # body
                _sanitize_csv_cell(r[12]),  # status
                _sanitize_csv_cell(r[13]),  # tone
                f"{r[14]:.4f}" if r[14] else "",  # cost
                _format_ts(r[15]),  # approved_at
            ]
        )

    csv_content = output.getvalue()
    output.close()

    safe_name = "".join(c for c in campaign_name if c.isalnum() or c in " -_").strip()
    filename = f"{safe_name}-messages.csv" if safe_name else "messages.csv"

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Conflict Check ──────────────────────────────────


@campaigns_bp.route("/api/campaigns/<campaign_id>/conflict-check", methods=["POST"])
@require_role("editor")
def conflict_check(campaign_id):
    """Check a campaign's contacts for ICP mismatches and overlaps."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign = db.session.execute(
        db.text("""
            SELECT id, name, strategy_id, target_criteria,
                   contact_cooldown_days, status, template_config,
                   created_at
            FROM campaigns
            WHERE id = :id AND tenant_id = :t
        """),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    strategy_id = campaign[2]
    cooldown_days = campaign[4] or 30

    icp = {}
    if strategy_id:
        strat_row = db.session.execute(
            db.text("""
                SELECT extracted_data FROM strategy_documents
                WHERE id = :sid AND tenant_id = :t
            """),
            {"sid": strategy_id, "t": tenant_id},
        ).fetchone()
        if strat_row:
            extracted = _parse_jsonb(strat_row[0]) or {}
            icp = extracted.get("icp", {})

    # Get campaign contacts with company details
    contacts = db.session.execute(
        db.text("""
            SELECT ct.id, ct.first_name, ct.last_name,
                   ct.email_address, ct.linkedin_url,
                   ct.seniority_level, ct.department,
                   co.industry, co.geo_region, co.company_size, co.name
            FROM campaign_contacts cc
            JOIN contacts ct ON ct.id = cc.contact_id
            LEFT JOIN companies co ON co.id = ct.company_id
            WHERE cc.campaign_id = :cid AND ct.tenant_id = :t
        """),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()

    issues = []

    icp_industries = [ind.lower() for ind in icp.get("industries", [])]
    icp_geos = [g.lower() for g in icp.get("geographies", [])]
    icp_sizes = [s.lower() for s in icp.get("company_sizes", [])]

    for c in contacts:
        contact_id = str(c[0])
        contact_name = f"{c[1] or ''} {c[2] or ''}".strip()

        # ICP industry mismatch
        if icp_industries and c[7]:
            if c[7].lower() not in icp_industries:
                issues.append(
                    {
                        "type": "icp_mismatch",
                        "field": "industry",
                        "contact_id": contact_id,
                        "contact_name": contact_name,
                        "value": c[7],
                        "expected": icp_industries,
                    }
                )

        # ICP geography mismatch
        if icp_geos and c[8]:
            if c[8].lower() not in icp_geos:
                issues.append(
                    {
                        "type": "icp_mismatch",
                        "field": "geo_region",
                        "contact_id": contact_id,
                        "contact_name": contact_name,
                        "value": c[8],
                        "expected": icp_geos,
                    }
                )

        # ICP company size mismatch
        if icp_sizes and c[9]:
            if c[9].lower() not in icp_sizes:
                issues.append(
                    {
                        "type": "icp_mismatch",
                        "field": "company_size",
                        "contact_id": contact_id,
                        "contact_name": contact_name,
                        "value": c[9],
                        "expected": icp_sizes,
                    }
                )

        # Channel gaps
        if not c[3] and not c[4]:
            issues.append(
                {
                    "type": "channel_gap",
                    "contact_id": contact_id,
                    "contact_name": contact_name,
                    "detail": "No email or LinkedIn URL",
                }
            )

    # Cooldown violations
    cooldown_rows = db.session.execute(
        db.text("""
            SELECT cc2.contact_id, ct.first_name, ct.last_name,
                   cmp2.id, cmp2.name, cmp2.status
            FROM campaign_contacts cc2
            JOIN contacts ct ON ct.id = cc2.contact_id
            JOIN campaigns cmp2 ON cmp2.id = cc2.campaign_id
            WHERE cc2.contact_id IN (
                SELECT contact_id FROM campaign_contacts
                WHERE campaign_id = :cid
            )
            AND cc2.campaign_id != :cid
            AND cmp2.status NOT IN ('archived', 'draft')
            AND cmp2.tenant_id = :t
            AND cmp2.created_at >= CURRENT_TIMESTAMP - INTERVAL '1 day' * :cooldown
        """),
        {"cid": campaign_id, "t": tenant_id, "cooldown": cooldown_days},
    ).fetchall()

    for cr in cooldown_rows:
        issues.append(
            {
                "type": "cooldown_violation",
                "contact_id": str(cr[0]),
                "contact_name": f"{cr[1] or ''} {cr[2] or ''}".strip(),
                "overlapping_campaign": {
                    "id": str(cr[3]),
                    "name": cr[4],
                    "status": cr[5],
                },
                "cooldown_days": cooldown_days,
            }
        )

    return jsonify(
        {
            "campaign_id": campaign_id,
            "total_contacts": len(contacts),
            "total_issues": len(issues),
            "issues": issues,
        }
    )


# ---------------------------------------------------------------------------
# BL-147: Campaign Auto-Setup from Qualified Contacts
# ---------------------------------------------------------------------------


@campaigns_bp.route("/api/campaigns/auto-setup", methods=["POST"])
@require_role("editor")
def auto_setup_campaign():
    """Create a draft campaign pre-populated with qualified contacts.

    Finds all triage-passed contacts (via their companies), auto-names the
    campaign from strategy context, assigns per-contact channels based on
    available contact info (email -> email, LinkedIn URL -> linkedin_message),
    and pre-fills generation_config from the strategy.

    Returns the created campaign with contact count and strategy_prefilled flag.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}

    # Optional overrides
    name_override = (body.get("name") or "").strip()
    description = body.get("description", "")
    owner_id = body.get("owner_id")
    min_status = body.get("min_status", "triage_passed")

    # Determine which company statuses qualify
    QUALIFIED_STATUSES = ("triage_passed", "enriched_l2", "enriched", "synced")
    status_idx = (
        QUALIFIED_STATUSES.index(min_status) if min_status in QUALIFIED_STATUSES else 0
    )
    qualified_statuses = QUALIFIED_STATUSES[status_idx:]

    # Find qualified contacts with company and contact info
    placeholders = ", ".join(f":s{i}" for i in range(len(qualified_statuses)))
    params = {"t": tenant_id}
    for i, s in enumerate(qualified_statuses):
        params[f"s{i}"] = s

    rows = db.session.execute(
        db.text(f"""
            SELECT
                ct.id AS contact_id,
                ct.first_name, ct.last_name,
                ct.email_address, ct.linkedin_url,
                co.name AS company_name,
                co.id AS company_id
            FROM contacts ct
            JOIN companies co ON ct.company_id = co.id
            WHERE ct.tenant_id = :t
                AND co.status IN ({placeholders})
            ORDER BY ct.contact_score DESC NULLS LAST, co.name ASC
        """),
        params,
    ).fetchall()

    if not rows:
        return jsonify({"error": "No qualified contacts found. Run triage first."}), 422

    # Load strategy for auto-config
    strat_doc = StrategyDocument.query.filter_by(tenant_id=tenant_id).first()
    strategy_id = str(strat_doc.id) if strat_doc else None
    extracted = (
        _parse_jsonb(strat_doc.extracted_data)
        if strat_doc and strat_doc.extracted_data
        else {}
    )
    generation_config = (
        _build_strategy_generation_config(extracted)
        if extracted and isinstance(extracted, dict)
        else {}
    )

    # Auto-generate campaign name
    if name_override:
        campaign_name = name_override
    else:
        campaign_name = _generate_campaign_name(extracted, len(rows))

    # Build template_config with default email + LinkedIn connect steps
    template_config = [
        {
            "step": 1,
            "label": "Connection Request",
            "channel": "linkedin_connect",
            "enabled": True,
        },
        {
            "step": 2,
            "label": "Follow-up Email",
            "channel": "email",
            "enabled": True,
        },
        {
            "step": 3,
            "label": "LinkedIn Message",
            "channel": "linkedin_message",
            "enabled": True,
        },
    ]

    # Create campaign
    campaign = Campaign(
        tenant_id=tenant_id,
        name=campaign_name,
        description=description,
        owner_id=owner_id,
        status="draft",
        strategy_id=strategy_id,
        template_config=json.dumps(template_config),
        generation_config=json.dumps(generation_config),
        total_contacts=len(rows),
    )
    db.session.add(campaign)
    db.session.flush()

    # Add qualified contacts to campaign
    for row in rows:
        contact_id = row[0]
        cc = CampaignContact(
            campaign_id=campaign.id,
            contact_id=contact_id,
            tenant_id=tenant_id,
            status="pending",
        )
        db.session.add(cc)

    db.session.commit()

    # Count by channel capability
    with_email = sum(1 for r in rows if r[3])
    with_linkedin = sum(1 for r in rows if r[4])

    return jsonify(
        {
            "id": str(campaign.id),
            "name": campaign_name,
            "status": "Draft",
            "total_contacts": len(rows),
            "with_email": with_email,
            "with_linkedin": with_linkedin,
            "strategy_prefilled": bool(extracted),
            "generation_config": generation_config,
            "template_config": template_config,
            "created_at": _format_ts(campaign.created_at),
        }
    ), 201


def _generate_campaign_name(extracted: dict, contact_count: int) -> str:
    """Generate a campaign name from strategy context.

    Format: "{ICP focus} — {Quarter} {Year}" or fallback to generic name.
    """
    from datetime import datetime

    now = datetime.now()
    quarter = f"Q{(now.month - 1) // 3 + 1}"
    year = now.year

    # Try to extract focus from ICP
    icp = extracted.get("icp", {}) if extracted else {}
    focus = ""
    if isinstance(icp, dict):
        industries = icp.get("industries", [])
        if industries and isinstance(industries, list):
            focus = (
                industries[0]
                if len(industries) == 1
                else f"{len(industries)} industries"
            )
        geos = icp.get("geographies", [])
        if geos and isinstance(geos, list) and not focus:
            focus = geos[0] if len(geos) == 1 else f"{len(geos)} markets"

    if focus:
        return f"{focus} — {quarter} {year}"

    return f"Outreach Campaign — {quarter} {year} ({contact_count} contacts)"


# ── Feedback Summary ─────────────────────────────────────────


@campaigns_bp.route("/api/campaigns/<campaign_id>/feedback-summary", methods=["GET"])
@require_auth
def feedback_summary(campaign_id):
    """Aggregated feedback stats for a campaign."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify campaign belongs to tenant
    campaign = db.session.execute(
        db.text("SELECT id FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": str(tenant_id)},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    feedbacks = MessageFeedback.query.filter_by(campaign_id=campaign_id).all()

    by_action = {}
    edit_reasons = {}
    for f in feedbacks:
        by_action[f.action] = by_action.get(f.action, 0) + 1
        if f.edit_reason:
            edit_reasons[f.edit_reason] = edit_reasons.get(f.edit_reason, 0) + 1

    # Per-step approval rate
    step_stats = {}
    for f in feedbacks:
        msg = db.session.get(Message, f.message_id)
        if msg and msg.campaign_step_id:
            sid = str(msg.campaign_step_id)
            if sid not in step_stats:
                step_stats[sid] = {"total": 0, "approved": 0}
            step_stats[sid]["total"] += 1
            if f.action == "approved":
                step_stats[sid]["approved"] += 1

    for sid in step_stats:
        s = step_stats[sid]
        s["approval_rate"] = (
            round(s["approved"] / s["total"] * 100) if s["total"] > 0 else 0
        )

    return jsonify(
        {
            "total": len(feedbacks),
            "by_action": by_action,
            "top_edit_reasons": sorted(edit_reasons.items(), key=lambda x: -x[1]),
            "per_step": step_stats,
        }
    )


# ── Feedback Insights ────────────────────────────────────────


@campaigns_bp.route("/api/campaigns/<campaign_id>/feedback-insights", methods=["GET"])
@require_auth
def feedback_insights(campaign_id):
    """Actionable insights derived from feedback patterns for a campaign.

    Applies heuristic rules to feedback data and suggests configuration
    changes (formality, length, personalization, tone) when patterns exceed
    defined thresholds.  Returns empty insights when fewer than 5 feedback
    actions exist.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify campaign belongs to tenant
    campaign = db.session.execute(
        db.text("SELECT id FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": str(tenant_id)},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    feedbacks = MessageFeedback.query.filter_by(campaign_id=campaign_id).all()

    total_actions = len(feedbacks)

    # Not enough data for meaningful insights
    if total_actions < 5:
        return jsonify({"insights": [], "stats": {"total_actions": total_actions}})

    # Aggregate stats
    by_action: dict[str, int] = {}
    edit_reasons: dict[str, int] = {}
    step_stats: dict[str, dict] = {}

    for f in feedbacks:
        by_action[f.action] = by_action.get(f.action, 0) + 1
        if f.edit_reason:
            edit_reasons[f.edit_reason] = edit_reasons.get(f.edit_reason, 0) + 1

        msg = db.session.get(Message, f.message_id)
        if msg and msg.campaign_step_id:
            sid = str(msg.campaign_step_id)
            if sid not in step_stats:
                step_stats[sid] = {"total": 0, "approved": 0}
            step_stats[sid]["total"] += 1
            if f.action == "approved":
                step_stats[sid]["approved"] += 1

    approved_count = by_action.get("approved", 0)
    approval_rate = round(approved_count / total_actions, 2) if total_actions else 0

    total_edits = sum(edit_reasons.values()) or 1  # avoid division by zero

    # Build insights from heuristic rules
    insights: list[dict] = []

    # Too formal
    too_formal_pct = edit_reasons.get("too_formal", 0) / total_edits
    if too_formal_pct > 0.25:
        insights.append(
            {
                "type": "tone_mismatch",
                "severity": "warning",
                "message": (
                    f"{round(too_formal_pct * 100)}% of edits cite 'too formal'. "
                    "Consider switching to informal address."
                ),
                "suggestion": {"field": "formality", "value": "informal"},
            }
        )

    # Too casual
    too_casual_pct = edit_reasons.get("too_casual", 0) / total_edits
    if too_casual_pct > 0.25:
        insights.append(
            {
                "type": "tone_mismatch",
                "severity": "warning",
                "message": (
                    f"{round(too_casual_pct * 100)}% of edits cite 'too casual'. "
                    "Consider switching to formal address."
                ),
                "suggestion": {"field": "formality", "value": "formal"},
            }
        )

    # Too long
    too_long_pct = edit_reasons.get("too_long", 0) / total_edits
    if too_long_pct > 0.20:
        insights.append(
            {
                "type": "length_issue",
                "severity": "warning",
                "message": (
                    f"{round(too_long_pct * 100)}% of edits cite 'too long'. "
                    "Consider reducing max message length."
                ),
                "suggestion": {"field": "max_length", "value": "shorter"},
            }
        )

    # Generic
    generic_pct = edit_reasons.get("generic", 0) / total_edits
    if generic_pct > 0.20:
        insights.append(
            {
                "type": "personalization_gap",
                "severity": "warning",
                "message": (
                    f"{round(generic_pct * 100)}% of edits cite 'generic'. "
                    "Consider increasing personalization level."
                ),
                "suggestion": {"field": "personalization_level", "value": 4},
            }
        )

    # Wrong tone (absolute count)
    wrong_tone_count = edit_reasons.get("wrong_tone", 0)
    if wrong_tone_count > 3:
        insights.append(
            {
                "type": "tone_review",
                "severity": "info",
                "message": (
                    f"'Wrong tone' was cited {wrong_tone_count} times. "
                    "Review the tone setting for this campaign."
                ),
                "suggestion": {"field": "tone", "value": "review"},
            }
        )

    # Low-performing steps (approval rate < 50%)
    for sid, stats in step_stats.items():
        if stats["total"] >= 3:
            step_approval = stats["approved"] / stats["total"]
            if step_approval < 0.50:
                insights.append(
                    {
                        "type": "low_performing_step",
                        "severity": "warning",
                        "message": (
                            f"Step {sid} has a {round(step_approval * 100)}% approval rate "
                            f"({stats['approved']}/{stats['total']}). "
                            "Consider revising this step's configuration."
                        ),
                        "suggestion": {"field": "step", "value": sid},
                    }
                )

    return jsonify(
        {
            "insights": insights,
            "stats": {
                "total_actions": total_actions,
                "approval_rate": approval_rate,
                "edit_reasons": edit_reasons,
            },
        }
    )


# ── Auto-segmentation endpoints ──────────────────────────────────────


@campaigns_bp.route("/api/companies/auto-segment", methods=["POST"])
@require_role("editor")
def auto_segment_companies():
    """Run auto-segmentation on all unsegmented companies in the tenant."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    force = body.get("force", False)

    from ..services.segmentation import auto_segment_tenant

    result = auto_segment_tenant(tenant_id, force=force)
    return jsonify(result)


# ── Eligible contacts endpoint ───────────────────────────────────────


@campaigns_bp.route("/api/campaigns/<campaign_id>/eligible-contacts", methods=["GET"])
@require_auth
def eligible_contacts(campaign_id):
    """Return contacts eligible for a campaign based on segment matching.

    Filters:
    - Company segment matches campaign target_criteria.segment (if set)
    - Contact not already in campaign
    - Contact has valid email
    - Company passed triage (status in triage_passed, enriched_l2, or above)
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Load campaign to get target segment
    campaign = db.session.execute(
        db.text("""
            SELECT target_criteria FROM campaigns
            WHERE id = :id AND tenant_id = :t
        """),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    target_criteria = campaign[0]
    if isinstance(target_criteria, str):
        try:
            target_criteria = json.loads(target_criteria)
        except (json.JSONDecodeError, TypeError):
            target_criteria = {}
    target_criteria = target_criteria or {}

    target_segment = target_criteria.get("segment")

    # Build query
    where = [
        "ct.tenant_id = :t",
        "ct.email_address IS NOT NULL",
        "ct.email_address != ''",
        "co.status IN ('triage_passed', 'enriched_l2', 'enrichment_l2_complete')",
    ]
    params = {"t": tenant_id, "cid": campaign_id}

    if target_segment:
        where.append("co.segment = :segment")
        params["segment"] = target_segment

    # Exclude contacts already in this campaign
    where.append("""
        ct.id NOT IN (
            SELECT contact_id FROM campaign_contacts WHERE campaign_id = :cid
        )
    """)

    where_clause = " AND ".join(where)

    rows = db.session.execute(
        db.text(f"""
            SELECT ct.id, ct.first_name, ct.last_name, ct.job_title,
                   ct.email_address, ct.contact_score, ct.icp_fit,
                   co.id AS company_id, co.name AS company_name,
                   co.segment, co.tier
            FROM contacts ct
            JOIN companies co ON ct.company_id = co.id
            WHERE {where_clause}
            ORDER BY ct.contact_score DESC NULLS LAST
        """),
        params,
    ).fetchall()

    contacts = [
        {
            "id": str(r[0]),
            "first_name": r[1],
            "last_name": r[2],
            "job_title": r[3],
            "email_address": r[4],
            "contact_score": r[5],
            "icp_fit": r[6],
            "company_id": str(r[7]) if r[7] else None,
            "company_name": r[8],
            "segment": r[9],
            "tier": r[10],
        }
        for r in rows
    ]

    return jsonify({"contacts": contacts, "total": len(contacts)})


# ── Message preview + batch generation endpoints ─────────────────────


@campaigns_bp.route("/api/campaigns/<campaign_id>/generate-preview", methods=["POST"])
@require_role("editor")
def generate_message_preview(campaign_id):
    """Generate a preview message for one contact without saving.

    Body: {contact_id, step_position}
    Returns: {subject, body, recommended_products, segment}
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    contact_id = body.get("contact_id")
    step_position = body.get("step_position")

    if not contact_id or step_position is None:
        return jsonify({"error": "contact_id and step_position required"}), 400

    from ..services.message_generator import generate_preview

    try:
        result = generate_preview(
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            contact_id=contact_id,
            step_position=int(step_position),
        )
    except Exception:
        logger.exception("Preview generation failed")
        return jsonify({"error": "Preview generation failed"}), 500

    if not result:
        return jsonify({"error": "Contact or campaign step not found"}), 404

    return jsonify(result)


@campaigns_bp.route("/api/campaigns/<campaign_id>/generate-batch", methods=["POST"])
@require_role("editor")
def generate_batch_messages(campaign_id):
    """Generate messages for eligible contacts in a campaign step.

    Body: {step_position, limit: 10}
    Returns: {generated: N, total_eligible: M}
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    body = request.get_json(silent=True) or {}
    step_position = body.get("step_position")
    limit = min(int(body.get("limit", 10)), 50)

    if step_position is None:
        return jsonify({"error": "step_position required"}), 400

    # Verify campaign exists
    campaign = db.session.execute(
        db.text("SELECT id FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    # Get campaign contacts that haven't been generated yet for this step
    contacts = db.session.execute(
        db.text("""
            SELECT cc.id AS cc_id, cc.contact_id
            FROM campaign_contacts cc
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                AND cc.status NOT IN ('excluded', 'generated', 'failed', 'generating')
            ORDER BY cc.added_at
            LIMIT :lim
        """),
        {"cid": campaign_id, "t": tenant_id, "lim": limit},
    ).fetchall()

    if not contacts:
        return jsonify({"generated": 0, "message": "No eligible contacts"}), 200

    # Use the existing start_generation which handles the full flow
    # For batch, we start the background generation thread
    from flask import g

    user_id = str(g.current_user.id) if hasattr(g, "current_user") else None

    start_generation(
        current_app._get_current_object(),
        campaign_id=campaign_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    return jsonify(
        {
            "status": "generating",
            "total_contacts": len(contacts),
            "message": f"Generation started for {len(contacts)} contacts",
        }
    ), 202


# ── Campaign Attachments ──────────────────────────────────


@campaigns_bp.route("/api/campaigns/<campaign_id>/attachments", methods=["POST"])
@require_role("editor")
def upload_attachment(campaign_id):
    """Upload a PDF attachment for a campaign (multipart form data).

    Form field: file (required)
    Response: Asset dict with id, filename, content_type, size_bytes, etc.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify campaign exists and belongs to tenant
    campaign = db.session.execute(
        db.text("SELECT id FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": str(tenant_id)},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No filename"}), 400

    file_data = file.read()
    size_bytes = len(file_data)
    content_type = file.content_type or "application/octet-stream"

    error = validate_upload(content_type, size_bytes)
    if error:
        return jsonify({"error": error}), 400

    asset_id = str(uuid.uuid4())
    file_obj = BytesIO(file_data)

    try:
        storage_path = upload_asset(
            file_obj=file_obj,
            filename=file.filename,
            content_type=content_type,
            tenant_id=str(tenant_id),
            campaign_id=campaign_id,
            asset_id=asset_id,
        )
    except Exception as e:
        logger.error("S3 upload failed for campaign %s: %s", campaign_id, e)
        return jsonify({"error": "File upload failed"}), 500

    asset = Asset(
        id=asset_id,
        tenant_id=str(tenant_id),
        campaign_id=campaign_id,
        filename=file.filename,
        content_type=content_type,
        storage_path=storage_path,
        size_bytes=size_bytes,
        metadata_={},
    )
    db.session.add(asset)
    db.session.commit()

    return jsonify(asset.to_dict()), 201


@campaigns_bp.route("/api/campaigns/<campaign_id>/attachments", methods=["GET"])
@require_auth
def list_attachments(campaign_id):
    """List all attachments for a campaign.

    Response: { attachments: [Asset, ...] }
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign = db.session.execute(
        db.text("SELECT id FROM campaigns WHERE id = :id AND tenant_id = :t"),
        {"id": campaign_id, "t": str(tenant_id)},
    ).fetchone()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    assets = (
        Asset.query.filter_by(tenant_id=str(tenant_id), campaign_id=campaign_id)
        .order_by(Asset.created_at.desc())
        .all()
    )

    result = []
    for a in assets:
        d = a.to_dict()
        try:
            d["download_url"] = get_download_url(a.storage_path)
        except Exception:
            d["download_url"] = None
        result.append(d)

    return jsonify({"attachments": result}), 200


@campaigns_bp.route(
    "/api/campaigns/<campaign_id>/attachments/<attachment_id>", methods=["DELETE"]
)
@require_role("editor")
def delete_attachment(campaign_id, attachment_id):
    """Delete a campaign attachment from S3 and database."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    asset = Asset.query.filter_by(
        id=attachment_id, campaign_id=campaign_id, tenant_id=str(tenant_id)
    ).first()
    if not asset:
        return jsonify({"error": "Attachment not found"}), 404

    try:
        delete_asset(asset.storage_path)
    except Exception as e:
        logger.warning("S3 delete failed for attachment %s: %s", attachment_id, e)

    db.session.delete(asset)
    db.session.commit()

    return jsonify({"ok": True}), 200


# ── Test Email ──────────────────────────────────


@campaigns_bp.route("/api/campaigns/<campaign_id>/send-test", methods=["POST"])
@require_role("editor")
def send_test_email(campaign_id):
    """Send a test email to the current authenticated user.

    Body: { message_id } — ID of an existing message to use as content
    Response: { ok: true, sent_to: email, message_id: ... }

    The test email:
    - Has [TEST] prefix on the subject
    - Includes a header note with original recipient info
    - Attaches all campaign PDF attachments
    - Is sent to the authenticated user's email
    """
    import resend

    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign or str(campaign.tenant_id) != str(tenant_id):
        return jsonify({"error": "Campaign not found"}), 404

    body = request.get_json(silent=True) or {}
    message_id = body.get("message_id")
    if not message_id:
        return jsonify({"error": "message_id is required"}), 400

    # Load the message
    from ..models import Contact

    message = db.session.get(Message, message_id)
    if not message or str(message.tenant_id) != str(tenant_id):
        return jsonify({"error": "Message not found"}), 404

    contact = (
        db.session.get(Contact, message.contact_id) if message.contact_id else None
    )
    contact_name = ""
    contact_email = ""
    if contact:
        contact_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
        contact_email = contact.email_address or ""

    # Get sender config
    sender_config = campaign.sender_config
    if isinstance(sender_config, str):
        sender_config = json.loads(sender_config)
    sender_config = sender_config or {}

    from_email = sender_config.get("from_email")
    from_name = sender_config.get("from_name")
    reply_to = sender_config.get("reply_to")

    if not from_email:
        return jsonify({"error": "Campaign sender_config missing from_email"}), 400

    # Get Resend API key from tenant
    tenant = db.session.get(Tenant, tenant_id)
    tenant_settings = tenant.settings if tenant else {}
    if isinstance(tenant_settings, str):
        tenant_settings = json.loads(tenant_settings)
    tenant_settings = tenant_settings or {}

    api_key = tenant_settings.get("resend_api_key")
    if not api_key:
        return jsonify({"error": "Tenant settings missing resend_api_key"}), 400

    resend.api_key = api_key

    # Build the test email
    user = g.current_user
    to_email = user.email

    subject = f"[TEST] {message.subject or '(no subject)'}"

    # Build HTML body with header note
    from ..services.send_service import _render_body_html

    original_body_html = _render_body_html(message.body)
    header_note = (
        '<div style="background:#f0f0f0;padding:12px;margin-bottom:16px;'
        'border-left:4px solid #2196F3;font-size:13px;color:#555;">'
        "<strong>This is a test email.</strong><br>"
        f"Original recipient: {contact_name} &lt;{contact_email}&gt;"
        "</div>"
    )
    body_html = header_note + original_body_html

    sender = f"{from_name} <{from_email}>" if from_name else from_email

    # Collect campaign PDF attachments
    attachments = []
    campaign_assets = Asset.query.filter_by(
        campaign_id=campaign_id, tenant_id=str(tenant_id)
    ).all()

    for asset in campaign_assets:
        if asset.content_type == "application/pdf":
            try:
                import base64

                file_content = download_asset_bytes(asset.storage_path)
                attachments.append(
                    {
                        "filename": asset.filename,
                        "content": base64.b64encode(file_content).decode("utf-8"),
                        "type": "application/pdf",
                    }
                )
            except Exception as e:
                logger.warning(
                    "Failed to fetch attachment %s for test email: %s",
                    asset.id,
                    e,
                )

    # Send via Resend
    params = {
        "from_": sender,
        "to": [to_email],
        "subject": subject,
        "html": body_html,
    }
    if reply_to:
        params["reply_to"] = [reply_to]
    if attachments:
        params["attachments"] = attachments

    try:
        result = resend.Emails.send(params)
        resend_id = (
            result.id
            if hasattr(result, "id")
            else (result.get("id") if isinstance(result, dict) else str(result))
        )
    except Exception as e:
        logger.error("Test email send failed for campaign %s: %s", campaign_id, e)
        return jsonify({"error": f"Failed to send test email: {str(e)}"}), 500

    # BL-1026: log the preview send with kind='preview' so Resend webhooks
    # for the test email land on a known row (instead of being dropped as
    # "no EmailSendLog") while analytics queries still filter it out.
    from datetime import datetime, timezone

    try:
        preview_log = EmailSendLog(
            tenant_id=tenant_id,
            message_id=message.id,
            status="sent",
            kind="preview",
            from_email=from_email,
            to_email=to_email,
            resend_message_id=resend_id,
            sent_at=datetime.now(timezone.utc),
        )
        db.session.add(preview_log)
        db.session.commit()
    except Exception as e:  # pragma: no cover — defensive; the email was sent
        logger.warning(
            "Test email sent for campaign %s but preview log insert failed: %s",
            campaign_id,
            e,
        )
        db.session.rollback()

    return jsonify(
        {
            "ok": True,
            "sent_to": to_email,
            "message_id": message_id,
            "resend_id": resend_id,
            "attachments_included": len(attachments),
        }
    ), 200


# ═══════════════════════════════════════════════════════════════════════
# BL-1039: SSE analytics stream
# ═══════════════════════════════════════════════════════════════════════
#
# Shares query logic with ``campaign_analytics`` (at line ~2635) but is
# invoked from a streaming generator context where we can't return a
# Flask ``jsonify`` response. The helper below runs the same SQL and
# returns the dict that ``campaign_analytics`` would serialize.
#
# Design choices:
#   * Polling over webhook-push: the Resend webhook handler writes to PG;
#     polling PG every 5–10s is simpler than threading a pub/sub bus
#     through Gunicorn worker processes, and latency is well within the
#     2s AC-4 budget.
#   * Metric diffing: engagement counters drive the ``update`` event. We
#     emit only changed keys to minimize bandwidth.
#   * Tenant isolation: the helper returns ``None`` when the campaign
#     does not belong to ``tenant_id``. Route handler surfaces that as
#     **404** (not 403) per NFR-3 to avoid existence disclosure.
#   * Generator cleanup: ``GeneratorExit`` is swallowed so client
#     disconnects don't log an exception; the SQLAlchemy session is
#     released via ``db.session.remove()``.


def _compute_campaign_analytics(campaign_id, tenant_id):
    """Return the analytics dict for a campaign, or ``None`` if not found.

    Mirrors the aggregation performed in :func:`campaign_analytics`
    (the HTTP handler at /api/campaigns/<id>/analytics). Kept as a
    standalone helper so the SSE stream generator can reuse it without
    touching Flask request/response objects.

    Tenant isolation: returns ``None`` if the campaign either does not
    exist or does not belong to ``tenant_id``. The route-level handler
    translates that to a 404 (NFR-3: avoid existence disclosure).
    """
    # Verify campaign exists and belongs to tenant (BL-1039 tenant gate).
    campaign_row = db.session.execute(
        db.text(
            """
            SELECT id, generation_config, created_at,
                   generation_started_at, generation_completed_at
            FROM campaigns
            WHERE id = :id AND tenant_id = :t
            """
        ),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()

    if not campaign_row:
        return None

    gen_config = _parse_jsonb(campaign_row[1]) or {}
    campaign_created_at = campaign_row[2]
    generation_started_at = campaign_row[3]
    generation_completed_at = campaign_row[4]

    # Messages — by status / channel / step
    msg_by_status_rows = db.session.execute(
        db.text(
            """
            SELECT m.status, COUNT(*)
            FROM messages m
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
            GROUP BY m.status
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()
    msg_by_status = {r[0]: r[1] for r in msg_by_status_rows}
    msg_total = sum(msg_by_status.values())

    msg_by_channel_rows = db.session.execute(
        db.text(
            """
            SELECT m.channel, COUNT(*)
            FROM messages m
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
            GROUP BY m.channel
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()
    msg_by_channel = {r[0]: r[1] for r in msg_by_channel_rows}

    msg_by_step_rows = db.session.execute(
        db.text(
            """
            SELECT m.sequence_step, COUNT(*)
            FROM messages m
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
            GROUP BY m.sequence_step
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()
    msg_by_step = {str(r[0]): r[1] for r in msg_by_step_rows}

    # Email send log aggregation
    # BL-1029: exclude superseded rows (abort-then-retry attempts) so
    # audit counts don't double-count.
    # BL-1026: `esl.kind != 'preview'` excludes operator self-send
    # previews from polluting the rollup.
    email_send_rows = db.session.execute(
        db.text(
            """
            SELECT esl.status, COUNT(*)
            FROM email_send_log esl
            JOIN messages m ON esl.message_id = m.id
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
              AND esl.superseded_at IS NULL
              AND esl.kind != 'preview'
            GROUP BY esl.status
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()
    email_counts = {r[0]: r[1] for r in email_send_rows}
    email_total = sum(email_counts.values())

    # LinkedIn send queue aggregation
    li_send_rows = db.session.execute(
        db.text(
            """
            SELECT lsq.status, COUNT(*)
            FROM linkedin_send_queue lsq
            JOIN messages m ON lsq.message_id = m.id
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
            GROUP BY lsq.status
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchall()
    li_counts = {r[0]: r[1] for r in li_send_rows}
    li_total = sum(li_counts.values())

    # Contact stats
    contact_stats_row = db.session.execute(
        db.text(
            """
            SELECT
                COUNT(DISTINCT cc.contact_id) AS total,
                COUNT(DISTINCT CASE WHEN ct.email_address IS NOT NULL AND ct.email_address != '' THEN cc.contact_id END) AS with_email,
                COUNT(DISTINCT CASE WHEN ct.linkedin_url IS NOT NULL AND ct.linkedin_url != '' THEN cc.contact_id END) AS with_linkedin,
                COUNT(DISTINCT CASE WHEN
                    (ct.email_address IS NOT NULL AND ct.email_address != '')
                    AND (ct.linkedin_url IS NOT NULL AND ct.linkedin_url != '')
                THEN cc.contact_id END) AS both_channels
            FROM campaign_contacts cc
            JOIN contacts ct ON cc.contact_id = ct.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchone()

    contacts_total = contact_stats_row[0] if contact_stats_row else 0
    contacts_with_email = contact_stats_row[1] if contact_stats_row else 0
    contacts_with_linkedin = contact_stats_row[2] if contact_stats_row else 0
    contacts_both = contact_stats_row[3] if contact_stats_row else 0

    # Cost — prefer generation_config.cost, fall back to summed messages
    cost_data = gen_config.get("cost", {})
    generation_cost_usd = (
        float(cost_data.get("generation_usd", 0)) if isinstance(cost_data, dict) else 0
    )
    if generation_cost_usd == 0:
        cost_row = db.session.execute(
            db.text(
                """
                SELECT COALESCE(SUM(m.generation_cost_usd), 0)
                FROM messages m
                JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
                WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                """
            ),
            {"cid": campaign_id, "t": tenant_id},
        ).fetchone()
        generation_cost_usd = float(cost_row[0]) if cost_row else 0

    # Timeline — first/last send from email + LinkedIn.
    # BL-1026: preview rows excluded so stakeholder previews don't shift
    # the timeline.
    send_times = db.session.execute(
        db.text(
            """
            SELECT MIN(esl.sent_at), MAX(esl.sent_at)
            FROM email_send_log esl
            JOIN messages m ON esl.message_id = m.id
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                AND esl.sent_at IS NOT NULL
                AND esl.superseded_at IS NULL
                AND esl.kind != 'preview'
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchone()
    first_send_at = send_times[0] if send_times else None
    last_send_at = send_times[1] if send_times else None

    li_send_times = db.session.execute(
        db.text(
            """
            SELECT MIN(lsq.sent_at), MAX(lsq.sent_at)
            FROM linkedin_send_queue lsq
            JOIN messages m ON lsq.message_id = m.id
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                AND lsq.sent_at IS NOT NULL
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchone()
    if li_send_times and li_send_times[0]:
        if first_send_at is None or li_send_times[0] < first_send_at:
            first_send_at = li_send_times[0]
        if last_send_at is None or li_send_times[1] > last_send_at:
            last_send_at = li_send_times[1]

    # Engagement (the metrics that drive live updates).
    # BL-1026/BL-1029: exclude preview and superseded rows so stakeholder
    # previews and abort-then-retry attempts can't inflate engagement.
    engagement_row = db.session.execute(
        db.text(
            """
            SELECT
                COUNT(CASE WHEN esl.opened_at IS NOT NULL THEN 1 END) AS opened,
                COUNT(CASE WHEN esl.replied_at IS NOT NULL THEN 1 END) AS replied,
                COUNT(CASE WHEN esl.bounced_at IS NOT NULL THEN 1 END) AS bounced,
                COUNT(CASE WHEN esl.clicked_at IS NOT NULL THEN 1 END) AS clicked,
                COALESCE(SUM(esl.open_count), 0) AS total_opens,
                COALESCE(SUM(esl.click_count), 0) AS total_clicks,
                COUNT(CASE WHEN esl.bounce_type = 'hard' THEN 1 END) AS hard_bounces,
                COUNT(CASE WHEN esl.bounce_type = 'soft' THEN 1 END) AS soft_bounces,
                COUNT(CASE WHEN esl.unsubscribed_at IS NOT NULL THEN 1 END) AS unsubscribed,
                COUNT(CASE WHEN esl.delivered_at IS NOT NULL THEN 1 END) AS delivered
            FROM email_send_log esl
            JOIN messages m ON esl.message_id = m.id
            JOIN campaign_contacts cc ON m.campaign_contact_id = cc.id
            WHERE cc.campaign_id = :cid AND cc.tenant_id = :t
                AND esl.superseded_at IS NULL
                AND esl.kind != 'preview'
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchone()

    opened_count = int(engagement_row[0]) if engagement_row else 0
    replied_count = int(engagement_row[1]) if engagement_row else 0
    bounced_count = int(engagement_row[2]) if engagement_row else 0
    clicked_count = int(engagement_row[3]) if engagement_row else 0
    total_opens = int(engagement_row[4]) if engagement_row else 0
    total_clicks = int(engagement_row[5]) if engagement_row else 0
    hard_bounces = int(engagement_row[6]) if engagement_row else 0
    soft_bounces = int(engagement_row[7]) if engagement_row else 0
    unsubscribed_count = int(engagement_row[8]) if engagement_row else 0
    delivered_count = int(engagement_row[9]) if engagement_row else 0

    emails_delivered = (
        delivered_count
        if delivered_count > 0
        else email_counts.get("delivered", 0) + email_counts.get("sent", 0)
    )

    # Microsite — activities-table counts are the legacy fallback path.
    # Preserved during BL-1047 migration so pre-PostHog campaigns continue
    # to render metrics, and so a PostHog outage degrades gracefully to
    # locally-owned data rather than zeroes. `product_views` is the
    # legacy-only field (activities event_type) — still emitted for
    # backward compatibility until ua-microsite stops emitting it.
    microsite_row = db.session.execute(
        db.text(
            """
            SELECT
                COUNT(*) AS visits,
                COUNT(DISTINCT a.contact_id) AS unique_visitors,
                COUNT(CASE WHEN a.event_type = 'product_viewed' THEN 1 END) AS product_views
            FROM activities a
            JOIN campaign_contacts cc
                ON a.contact_id = cc.contact_id AND cc.tenant_id = :t
            WHERE cc.campaign_id = :cid
                AND a.source = 'microsite'
            """
        ),
        {"cid": campaign_id, "t": tenant_id},
    ).fetchone()
    legacy_ms_visits = int(microsite_row[0]) if microsite_row else 0
    legacy_ms_unique = int(microsite_row[1]) if microsite_row else 0
    ms_product_views = int(microsite_row[2]) if microsite_row else 0

    # BL-1047: merge PostHog-sourced microsite metrics. PostHog is the
    # canonical source for visits/unique/CTA/form metrics — activities-
    # table rows stay as a fallback while ua-microsite finishes moving
    # off the partner-token ingest path. `microsite_source` tells the UI
    # which data it is looking at (for banner copy, not for filtering).
    ms_visits = legacy_ms_visits
    ms_unique = legacy_ms_unique
    ms_cta_clicks: int | None = None
    ms_form_submits: int | None = None
    ms_avg_time_sec: float | None = None
    posthog_available = False
    microsite_source = "activities"
    try:
        # Import locally — keeps the integrations module off the cold-start
        # path for routes that don't touch analytics (mirrors the pattern
        # in `campaign_analytics_microsite`).
        from ..integrations.posthog import PostHogClient, PostHogUnavailableError

        since, until = _range_to_window("7d")
        client = PostHogClient()
        ph_metrics = client.get_campaign_microsite_metrics(
            str(campaign_id), since, until
        )
        # PostHog is authoritative when it answers. Legacy counts remain
        # available via `microsite_source="merged"` semantics — i.e. the
        # Activity-table counts are exposed only when PostHog is offline.
        ms_visits = ph_metrics.visits
        ms_unique = ph_metrics.unique_visitors
        ms_cta_clicks = ph_metrics.cta_clicks
        ms_form_submits = ph_metrics.form_submits
        ms_avg_time_sec = ph_metrics.avg_time_on_page_sec
        posthog_available = True
        microsite_source = "posthog"
    except (PostHogUnavailableError, RuntimeError) as exc:
        # RuntimeError covers PostHogClient.__init__ when env is unset.
        # PostHogUnavailableError covers transient failures.
        # Both degrade to legacy activities counts + `posthog_available=False`
        # so the frontend can render a banner without hiding the rest of
        # the analytics surface.
        logger.debug(
            "Microsite PostHog degraded for campaign %s (%s) — falling back "
            "to activities table",
            campaign_id,
            type(exc).__name__,
        )
        posthog_available = False
        microsite_source = "activities"
    except Exception:  # pragma: no cover — defensive; never break analytics
        logger.exception(
            "Unexpected PostHog error for campaign %s — falling back", campaign_id
        )
        posthog_available = False
        microsite_source = "activities"

    def _rate(num, den):
        if den == 0:
            return 0
        return round((num / den) * 100, 1)

    return {
        "messages": {
            "total": msg_total,
            "by_status": msg_by_status,
            "by_channel": msg_by_channel,
            "by_step": msg_by_step,
        },
        "sending": {
            "email": {
                "total": email_total,
                "queued": email_counts.get("queued", 0),
                "sent": email_counts.get("sent", 0),
                "delivered": delivered_count
                if delivered_count > 0
                else email_counts.get("delivered", 0),
                "bounced": email_counts.get("bounced", 0),
                "failed": email_counts.get("failed", 0),
                "unsubscribed": unsubscribed_count,
            },
            "linkedin": {
                "total": li_total,
                "queued": li_counts.get("queued", 0),
                "sent": li_counts.get("sent", 0),
                "delivered": li_counts.get("delivered", 0),
                "failed": li_counts.get("failed", 0),
            },
        },
        "contacts": {
            "total": contacts_total,
            "with_email": contacts_with_email,
            "with_linkedin": contacts_with_linkedin,
            "both_channels": contacts_both,
        },
        "cost": {
            "generation_usd": generation_cost_usd,
            "email_sends": email_total,
        },
        "engagement": {
            "opened": opened_count,
            "replied": replied_count,
            "bounced": bounced_count,
            "clicked": clicked_count,
            "unsubscribed": unsubscribed_count,
            "delivered": delivered_count,
            "total_opens": total_opens,
            "total_clicks": total_clicks,
            "hard_bounces": hard_bounces,
            "soft_bounces": soft_bounces,
            "open_rate": _rate(opened_count, emails_delivered),
            "reply_rate": _rate(replied_count, emails_delivered),
            "bounce_rate": _rate(bounced_count, email_total),
            "click_rate": _rate(clicked_count, emails_delivered),
            "unsubscribe_rate": _rate(unsubscribed_count, emails_delivered),
        },
        "timeline": {
            "created_at": _format_ts(campaign_created_at),
            "generation_started_at": _format_ts(generation_started_at),
            "generation_completed_at": _format_ts(generation_completed_at),
            "first_send_at": _format_ts(first_send_at),
            "last_send_at": _format_ts(last_send_at),
        },
        "microsite": {
            "visits": ms_visits,
            "unique_visitors": ms_unique,
            # BL-1047: PostHog-sourced engagement metrics. `None` when
            # PostHog is unreachable so the frontend can distinguish
            # "we have no data" from "the data is zero".
            "cta_clicks": ms_cta_clicks,
            "form_submits": ms_form_submits,
            "avg_time_on_page_sec": ms_avg_time_sec,
            # Legacy activities-table count — kept for backward compat
            # until ua-microsite drops the `product_viewed` event. See
            # ADR-010 §8 for Phase-2 removal plan.
            "product_views": ms_product_views,
            "visit_rate": _rate(ms_unique, contacts_total),
            # Diagnostic field: tells the UI which data source it is
            # looking at so it can show the correct banner copy.
            "source": microsite_source,
        },
        # Top-level flag so the frontend can render a single "PostHog
        # offline" banner without inspecting the microsite block. Set to
        # `False` both when the env is unset and when PostHog returns a
        # transient error — from the UI's perspective these are the same
        # state (fall back to activities-table counts + show banner).
        "posthog_available": posthog_available,
    }


# Metrics that drive the ``update`` SSE event. Tracked as scalar keys
# under the indicated parent. Rate fields are derived and emitted as
# part of engagement whenever any absolute count changes.
#
# NOTE on dot-notation: parent keys containing "." (e.g. "sending.email")
# are *paths*, not flat dict keys. :func:`_get_nested` splits on "." and
# traverses the snapshot dict (``snapshot["sending"]["email"]``) so
# sending-channel counters are compared correctly. This is verified by
# ``test_delta_resolves_dotted_parent_path``.
_STREAM_DELTA_KEYS = {
    "engagement": [
        "opened",
        "replied",
        "bounced",
        "clicked",
        "unsubscribed",
        "delivered",
        "total_opens",
        "total_clicks",
    ],
    "sending.email": ["sent", "delivered", "bounced", "failed", "unsubscribed"],
    "messages": ["total"],
    # BL-1047: cta_clicks + form_submits added for PostHog-sourced
    # engagement. product_views remains for legacy activities-table data.
    "microsite": [
        "visits",
        "unique_visitors",
        "cta_clicks",
        "form_submits",
        "product_views",
    ],
}


def _get_nested(d, path):
    """Return ``d[a][b]...`` for ``path='a.b'``; ``None`` on any miss."""
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _compute_analytics_delta(prev, curr):
    """Return the subset of metrics that changed between two snapshots.

    Output shape::

        {
          "engagement": {
            "opened": {"value": 5, "change": +1},
            ...
          },
          "messages": {"total": {"value": 10, "change": +2}},
        }

    Empty dict means "no change". Fields whose absolute values match
    between ``prev`` and ``curr`` are omitted.
    """
    delta = {}
    for parent_path, keys in _STREAM_DELTA_KEYS.items():
        prev_parent = _get_nested(prev, parent_path) or {}
        curr_parent = _get_nested(curr, parent_path) or {}
        changed = {}
        for k in keys:
            p = prev_parent.get(k, 0) or 0
            c = curr_parent.get(k, 0) or 0
            if p != c:
                changed[k] = {"value": c, "change": c - p}
        if changed:
            # Flatten sending.email → nested dict under "sending"
            if "." in parent_path:
                head, tail = parent_path.split(".", 1)
                delta.setdefault(head, {})[tail] = changed
            else:
                delta[parent_path] = changed
    return delta


def _sse_format_event(event_name, payload):
    """Encode a single SSE message."""
    return f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n"


def _analytics_stream_gen(
    campaign_id,
    tenant_id,
    poll_interval=7,
    heartbeat_interval=30,
    posthog_refresh_interval=30,
):
    """Yield SSE frames for a live-updating campaign analytics stream.

    Behaviour:
      1. Emit initial ``event: snapshot`` frame with full metrics.
      2. Every ``poll_interval`` seconds, re-query PG. If any tracked
         counter changed, emit ``event: update`` with a delta payload.
      3. After ``heartbeat_interval`` seconds with no delivered event,
         emit a ``:heartbeat`` SSE comment so proxies don't close the
         idle connection (Caddy + any sidecar buffering).
      4. On ``GeneratorExit`` (client disconnected or app shutdown),
         release the DB session and return cleanly — never raise.

    ``poll_interval``, ``heartbeat_interval`` and
    ``posthog_refresh_interval`` are parameters (not module-level
    constants) so unit tests can shrink them to zero.

    Tenant isolation is the caller's responsibility — the route
    handler must invoke :func:`_compute_campaign_analytics` once first
    and return 404 if it yields ``None``. This generator then assumes
    ownership has already been verified, but re-validates on every
    poll to defend against tenant-role revocation mid-stream.
    """
    try:
        snapshot = _compute_campaign_analytics(campaign_id, tenant_id)
        if snapshot is None:
            # Shouldn't happen (route validated) — emit an error and stop.
            yield _sse_format_event(
                "error",
                {"campaign_id": campaign_id, "message": "campaign_not_found"},
            )
            return

        yield _sse_format_event(
            "snapshot",
            {"campaign_id": campaign_id, "metrics": snapshot},
        )

        last_metrics = snapshot
        last_heartbeat = time.time()
        last_posthog_refresh = time.time()

        while True:
            try:
                time.sleep(poll_interval)
            except GeneratorExit:
                raise
            except Exception:  # pragma: no cover — interrupted sleep
                logger.warning(
                    "SSE analytics stream terminated unexpectedly in sleep "
                    "handler (campaign=%s tenant=%s)",
                    campaign_id,
                    tenant_id,
                )
                break

            # Re-check tenant ownership each poll (handles role revocation).
            # Transient DB errors (connection drops, RDS failovers) must NOT
            # kill the stream — skip this tick and try again next iteration.
            # Non-transient exceptions bubble up to the outer handler.
            try:
                current = _compute_campaign_analytics(campaign_id, tenant_id)
            except OperationalError as e:
                logger.warning(
                    "Transient DB error during analytics poll "
                    "(campaign=%s tenant=%s): %s",
                    campaign_id,
                    tenant_id,
                    e,
                )
                # Advance heartbeat clock so we don't spam heartbeats
                # immediately after recovery; real exceptions still bubble.
                continue

            if current is None:
                yield _sse_format_event(
                    "error",
                    {"campaign_id": campaign_id, "message": "campaign_not_found"},
                )
                return

            delta = _compute_analytics_delta(last_metrics, current)
            now = time.time()

            if delta:
                yield _sse_format_event(
                    "update",
                    {
                        "campaign_id": campaign_id,
                        "delta": delta,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    },
                )
                last_metrics = current
                last_heartbeat = now
            elif now - last_heartbeat >= heartbeat_interval:
                # SSE comment — keeps proxy buffers flushed.
                yield ":heartbeat\n\n"
                last_heartbeat = now

            # TODO(BL-1038): Wire BL-1035's PostHogClient.get_campaign_microsite_metrics
            # here. Until then, microsite metrics in snapshot/update events
            # come only from the DB (which has zero microsite data until
            # PostHog is wired). Spec FR-6 says 15s cadence; the default
            # here is 30s and deferred — reconcile to 15s when actually
            # wiring PostHog in BL-1038.
            if now - last_posthog_refresh >= posthog_refresh_interval:
                last_posthog_refresh = now
                # (no-op for now — see TODO above)

    except GeneratorExit:
        # Client disconnected — release SQLAlchemy session and exit cleanly.
        logger.debug(
            "analytics stream closed by client (campaign=%s tenant=%s)",
            campaign_id,
            tenant_id,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception(
            "analytics stream error (campaign=%s tenant=%s): %s",
            campaign_id,
            tenant_id,
            exc,
        )
        try:
            yield _sse_format_event("error", {"message": "stream_error"})
        except Exception:
            pass
    finally:
        try:
            db.session.remove()
        except Exception:
            pass


@campaigns_bp.route("/api/campaigns/<campaign_id>/analytics/stream", methods=["GET"])
@require_role("viewer")
def campaign_analytics_stream(campaign_id):
    """SSE endpoint pushing live campaign analytics updates (BL-1039).

    Powers live-updating KPI tiles / funnel / time-series on OutreachTab
    (BL-1041) and the Echo analytics page (BL-1040). Clients should
    use ``EventSource`` with exponential backoff on disconnect.

    Response headers include ``X-Accel-Buffering: no`` so Caddy and any
    reverse-proxy sidecar forward each frame immediately rather than
    buffering it into a chunk.
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Eagerly validate ownership before opening the stream. 404 (not 403)
    # per spec NFR-3 — never disclose whether a campaign exists cross-tenant.
    initial = _compute_campaign_analytics(campaign_id, tenant_id)
    if initial is None:
        return jsonify({"error": "Campaign not found"}), 404

    return Response(
        stream_with_context(_analytics_stream_gen(campaign_id, tenant_id)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# BL-1038 — Microsite analytics endpoint (PostHog-sourced)
# ---------------------------------------------------------------------------
#
# GET /api/campaigns/<id>/analytics/microsite?range=7d
#
# Returns microsite engagement metrics (visits, unique visitors, CTA clicks,
# form submits, avg time on page) for a campaign over a time window. Data
# comes from the PostHog Query API via the BL-1035 ``PostHogClient`` helper,
# which carries a 30s in-process cache.
#
# Graceful degradation (spec NFR-4): if PostHog is unavailable or not
# configured, we return HTTP 200 with zero metrics and ``posthog_available:
# false`` so the rest of the analytics dashboard keeps rendering. The
# frontend shows a "temporarily unavailable" banner on this block only.
#
# Tenant isolation (spec NFR-3): the campaign lookup is scoped to the
# resolved tenant BEFORE any PostHog call. Cross-tenant IDs return 404 (not
# 403) to avoid existence disclosure.


# Valid values for the ``range`` query param. Mirrors the analytics timeseries
# endpoint (BL-1037) when it lands; kept local here so this route can be
# factored/shared later without blocking BL-1037.
_VALID_RANGES = ("24h", "7d", "30d", "all")


def _range_to_window(range_param):
    """Map a ``range`` query-string value to a (since, until) UTC window.

    ``all`` returns a far-past ``since`` to effectively drop the lower bound.

    Raises:
        ValueError: when ``range_param`` is not one of ``_VALID_RANGES``.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    if range_param == "24h":
        return now - timedelta(hours=24), now
    if range_param == "7d":
        return now - timedelta(days=7), now
    if range_param == "30d":
        return now - timedelta(days=30), now
    if range_param == "all":
        # Fallback: far-past epoch. Sufficient until we have campaigns older
        # than 2020 (we don't — this project did not exist yet).
        return datetime(2020, 1, 1, tzinfo=timezone.utc), now
    raise ValueError(f"Invalid range: {range_param!r}")


def _zero_microsite_metrics():
    """The metrics block emitted when PostHog is unavailable / not configured."""
    return {
        "visits": 0,
        "unique_visitors": 0,
        "cta_clicks": 0,
        "form_submits": 0,
        "avg_time_on_page_sec": None,
    }


@campaigns_bp.route("/api/campaigns/<campaign_id>/analytics/microsite", methods=["GET"])
@require_role("viewer")
def campaign_analytics_microsite(campaign_id):
    """Return microsite metrics for a campaign from PostHog.

    Query params:
        range: one of ``24h``, ``7d`` (default), ``30d``, ``all``.

    Responses:
        200: ``{campaign_id, range, since, until, metrics, source,
              posthog_available[, degraded_reason]}``.
        400: invalid ``range`` value.
        401: no auth.
        404: campaign not found in current tenant (cross-tenant access also
             returns 404 per spec NFR-3 — no existence disclosure).
    """
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Range first — cheap validation before a DB round-trip.
    range_param = (request.args.get("range") or "7d").strip()
    if range_param not in _VALID_RANGES:
        return jsonify(
            {
                "error": (
                    f"Invalid range: {range_param!r}. "
                    f"Expected one of: {', '.join(_VALID_RANGES)}"
                )
            }
        ), 400

    # Tenant-scoped campaign lookup. A missing row OR a row owned by another
    # tenant both produce 404 (spec NFR-3).
    exists = db.session.execute(
        db.text("SELECT 1 FROM campaigns WHERE id = :id AND tenant_id = :t LIMIT 1"),
        {"id": campaign_id, "t": tenant_id},
    ).fetchone()
    if not exists:
        return jsonify({"error": "Campaign not found"}), 404

    # All invalid ranges were caught above, so this is guaranteed to succeed.
    since, until = _range_to_window(range_param)

    # Deferred import keeps the integrations module off the cold-start path
    # for unrelated routes.
    from ..integrations.posthog import PostHogClient, PostHogUnavailableError

    payload = {
        "campaign_id": str(campaign_id),
        "range": range_param,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "source": "posthog",
    }

    try:
        client = PostHogClient()
        metrics = client.get_campaign_microsite_metrics(str(campaign_id), since, until)
        payload["metrics"] = {
            "visits": metrics.visits,
            "unique_visitors": metrics.unique_visitors,
            "cta_clicks": metrics.cta_clicks,
            "form_submits": metrics.form_submits,
            "avg_time_on_page_sec": metrics.avg_time_on_page_sec,
        }
        payload["posthog_available"] = True
    except (PostHogUnavailableError, RuntimeError) as exc:
        # RuntimeError covers missing env (PostHogClient.__init__).
        # PostHogUnavailableError covers transient failures / malformed
        # responses. Both degrade cleanly to zero metrics so the frontend
        # can render a "temporarily unavailable" banner on this block while
        # the rest of the dashboard keeps working.
        logger.warning(
            "Microsite analytics degraded for campaign %s: %s",
            campaign_id,
            type(exc).__name__,
        )
        payload["metrics"] = _zero_microsite_metrics()
        payload["posthog_available"] = False
        # ``str(exc)`` on ``PostHogClient`` init or ``PostHogUnavailableError``
        # carries no secret material by design (see
        # ``api/integrations/posthog.py`` — the client never formats the key
        # into error messages). Still, we only expose the message, never
        # ``repr(exc)`` or the traceback.
        payload["degraded_reason"] = str(exc) or type(exc).__name__

    return jsonify(payload), 200
