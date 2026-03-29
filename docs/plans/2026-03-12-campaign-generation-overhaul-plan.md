# Campaign Message Generation Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace template-locked campaign steps with a flexible step builder supporting blank-slate creation, per-step example messages, length limits, file assets, AI-designed sequences, and a learning loop from user feedback.

**Architecture:** Hybrid relational + JSONB. New `CampaignStep` model with relational columns for queryable structure (position, channel, day_offset) and JSONB `config` for extensible generation params. `Asset` table for S3 file storage. `MessageFeedback` for learning signals. Generation reads from `campaign_step` rows instead of `template_config` JSONB.

**Tech Stack:** Flask + SQLAlchemy (backend), React + TypeScript (frontend), PostgreSQL, S3 (boto3), Anthropic Claude API (AI designer).

**Design doc:** `docs/plans/2026-03-12-campaign-generation-overhaul-design.md`

---

## Phase 1: Step Builder + Examples + Length Limits

### Task 1: Migration — campaign_step table + alter messages

**Files:**
- Create: `migrations/049_campaign_steps.sql`

**Step 1: Write migration**

```sql
-- Campaign steps: relational structure + JSONB config
CREATE TABLE IF NOT EXISTS campaign_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    position INTEGER NOT NULL DEFAULT 1,
    channel VARCHAR(50) NOT NULL DEFAULT 'linkedin_message',
    day_offset INTEGER NOT NULL DEFAULT 0,
    label VARCHAR(255) NOT NULL DEFAULT '',
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(campaign_id, position)
);

CREATE INDEX IF NOT EXISTS idx_campaign_steps_campaign ON campaign_steps(campaign_id);

-- Link messages to steps
ALTER TABLE messages ADD COLUMN IF NOT EXISTS campaign_step_id UUID REFERENCES campaign_steps(id);
CREATE INDEX IF NOT EXISTS idx_messages_campaign_step ON messages(campaign_step_id);

-- Link campaigns to LinkedIn accounts
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS linkedin_account_id UUID REFERENCES linkedin_accounts(id);
```

**Step 2: Run migration locally**

Run: `psql -h localhost -p 5433 -U leadgen -d leadgen_dev -f migrations/049_campaign_steps.sql`

**Step 3: Commit**

```bash
git add migrations/049_campaign_steps.sql
git commit -m "feat: add campaign_steps table and message step FK (migration 049)"
```

---

### Task 2: CampaignStep model

**Files:**
- Modify: `api/models.py` (after CampaignTemplate at line ~1188)
- Test: `tests/unit/test_campaign_steps.py`

**Step 1: Write failing test**

```python
# tests/unit/test_campaign_steps.py
"""Tests for CampaignStep CRUD API."""
import json
import pytest


def _create_campaign(client, headers):
    """Create a draft campaign for testing."""
    resp = client.post("/api/campaigns", headers=headers, json={
        "name": "Test Steps Campaign",
        "channel": "linkedin_message",
    })
    assert resp.status_code == 201
    return resp.get_json()["id"]


class TestCampaignStepsCRUD:
    """Campaign steps CRUD endpoints."""

    def test_list_steps_empty(self, client, auth_headers):
        cid = _create_campaign(client, auth_headers)
        resp = client.get(f"/api/campaigns/{cid}/steps", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_add_step(self, client, auth_headers):
        cid = _create_campaign(client, auth_headers)
        resp = client.post(f"/api/campaigns/{cid}/steps", headers=auth_headers, json={
            "channel": "linkedin_connect",
            "day_offset": 0,
            "label": "Connection request",
            "config": {
                "max_length": 300,
                "tone": "informal",
                "example_messages": [
                    {"body": "Hey {{first_name}}, saw your talk at...", "note": "casual opener"}
                ]
            }
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["channel"] == "linkedin_connect"
        assert data["position"] == 1
        assert data["config"]["max_length"] == 300
        assert len(data["config"]["example_messages"]) == 1

    def test_add_multiple_steps_auto_position(self, client, auth_headers):
        cid = _create_campaign(client, auth_headers)
        client.post(f"/api/campaigns/{cid}/steps", headers=auth_headers, json={
            "channel": "linkedin_connect", "day_offset": 0, "label": "Step 1",
        })
        resp = client.post(f"/api/campaigns/{cid}/steps", headers=auth_headers, json={
            "channel": "linkedin_message", "day_offset": 3, "label": "Step 2",
        })
        assert resp.status_code == 201
        assert resp.get_json()["position"] == 2

    def test_update_step(self, client, auth_headers):
        cid = _create_campaign(client, auth_headers)
        step = client.post(f"/api/campaigns/{cid}/steps", headers=auth_headers, json={
            "channel": "email", "day_offset": 7, "label": "Follow-up email",
        }).get_json()
        resp = client.patch(
            f"/api/campaigns/{cid}/steps/{step['id']}", headers=auth_headers,
            json={"label": "Updated label", "config": {"max_length": 500}}
        )
        assert resp.status_code == 200
        assert resp.get_json()["label"] == "Updated label"
        assert resp.get_json()["config"]["max_length"] == 500

    def test_delete_step_reorders(self, client, auth_headers):
        cid = _create_campaign(client, auth_headers)
        s1 = client.post(f"/api/campaigns/{cid}/steps", headers=auth_headers, json={
            "channel": "linkedin_connect", "day_offset": 0, "label": "S1",
        }).get_json()
        s2 = client.post(f"/api/campaigns/{cid}/steps", headers=auth_headers, json={
            "channel": "linkedin_message", "day_offset": 3, "label": "S2",
        }).get_json()
        s3 = client.post(f"/api/campaigns/{cid}/steps", headers=auth_headers, json={
            "channel": "email", "day_offset": 7, "label": "S3",
        }).get_json()
        # Delete middle step
        resp = client.delete(f"/api/campaigns/{cid}/steps/{s2['id']}", headers=auth_headers)
        assert resp.status_code == 200
        # Remaining steps should be reordered
        steps = client.get(f"/api/campaigns/{cid}/steps", headers=auth_headers).get_json()
        assert len(steps) == 2
        assert steps[0]["position"] == 1
        assert steps[0]["label"] == "S1"
        assert steps[1]["position"] == 2
        assert steps[1]["label"] == "S3"

    def test_reorder_steps(self, client, auth_headers):
        cid = _create_campaign(client, auth_headers)
        s1 = client.post(f"/api/campaigns/{cid}/steps", headers=auth_headers, json={
            "channel": "linkedin_connect", "day_offset": 0, "label": "S1",
        }).get_json()
        s2 = client.post(f"/api/campaigns/{cid}/steps", headers=auth_headers, json={
            "channel": "email", "day_offset": 3, "label": "S2",
        }).get_json()
        # Swap order
        resp = client.put(f"/api/campaigns/{cid}/steps/reorder", headers=auth_headers, json=[
            {"id": s2["id"], "position": 1},
            {"id": s1["id"], "position": 2},
        ])
        assert resp.status_code == 200
        steps = client.get(f"/api/campaigns/{cid}/steps", headers=auth_headers).get_json()
        assert steps[0]["label"] == "S2"
        assert steps[1]["label"] == "S1"

    def test_populate_from_template(self, client, auth_headers):
        cid = _create_campaign(client, auth_headers)
        # Create a template first
        tpl = client.post("/api/campaign-templates", headers=auth_headers, json={
            "name": "3-step LinkedIn",
            "steps": [
                {"channel": "linkedin_connect", "day_offset": 0, "label": "Connect", "enabled": True},
                {"channel": "linkedin_message", "day_offset": 3, "label": "Follow-up", "enabled": True},
            ]
        }).get_json()
        resp = client.post(
            f"/api/campaigns/{cid}/steps/from-template", headers=auth_headers,
            json={"template_id": tpl["id"]}
        )
        assert resp.status_code == 201
        steps = client.get(f"/api/campaigns/{cid}/steps", headers=auth_headers).get_json()
        assert len(steps) == 2
        assert steps[0]["channel"] == "linkedin_connect"
        assert steps[1]["channel"] == "linkedin_message"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_campaign_steps.py -v --tb=short`
Expected: FAIL (no model, no routes)

**Step 3: Add CampaignStep model to `api/models.py`**

Add after CampaignTemplate (line ~1188):

```python
class CampaignStep(db.Model):
    """A single step in a campaign outreach sequence."""
    __tablename__ = "campaign_steps"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id = db.Column(db.String(36), db.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    tenant_id = db.Column(db.String(36), db.ForeignKey("tenants.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=1)
    channel = db.Column(db.String(50), nullable=False, default="linkedin_message")
    day_offset = db.Column(db.Integer, nullable=False, default=0)
    label = db.Column(db.String(255), nullable=False, default="")
    config = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    updated_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now())

    campaign = db.relationship("Campaign", backref=db.backref("steps", lazy="dynamic", order_by="CampaignStep.position"))

    __table_args__ = (
        db.UniqueConstraint("campaign_id", "position", name="uq_campaign_step_position"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "campaign_id": self.campaign_id,
            "position": self.position,
            "channel": self.channel,
            "day_offset": self.day_offset,
            "label": self.label,
            "config": self.config or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
```

Also add `campaign_step_id` column to Message model (after line ~1073):

```python
campaign_step_id = db.Column(db.String(36), db.ForeignKey("campaign_steps.id"), nullable=True)
```

And add `linkedin_account_id` to Campaign model (after line ~1139):

```python
linkedin_account_id = db.Column(db.String(36), db.ForeignKey("linkedin_accounts.id"), nullable=True)
```

**Step 4: Commit model**

```bash
git add api/models.py
git commit -m "feat: add CampaignStep model + message/campaign FK columns"
```

---

### Task 3: Campaign steps API routes

**Files:**
- Create: `api/routes/campaign_step_routes.py`
- Modify: `api/__init__.py` (register blueprint)

**Step 1: Create routes file**

```python
# api/routes/campaign_step_routes.py
"""Campaign steps CRUD endpoints."""
import json
from flask import Blueprint, request, jsonify
from api.models import db, Campaign, CampaignStep, CampaignTemplate
from api.auth import require_auth

bp = Blueprint("campaign_steps", __name__)


def _get_campaign_or_404(campaign_id, tenant_id):
    campaign = Campaign.query.filter_by(id=campaign_id, tenant_id=str(tenant_id)).first()
    if not campaign:
        return None
    return campaign


@bp.route("/api/campaigns/<campaign_id>/steps", methods=["GET"])
@require_auth
def list_steps(campaign_id):
    tenant_id = request.tenant_id
    campaign = _get_campaign_or_404(campaign_id, tenant_id)
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    steps = (CampaignStep.query
             .filter_by(campaign_id=campaign_id, tenant_id=str(tenant_id))
             .order_by(CampaignStep.position)
             .all())
    return jsonify([s.to_dict() for s in steps])


@bp.route("/api/campaigns/<campaign_id>/steps", methods=["POST"])
@require_auth
def add_step(campaign_id):
    tenant_id = request.tenant_id
    campaign = _get_campaign_or_404(campaign_id, tenant_id)
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    data = request.get_json() or {}

    # Auto-increment position
    max_pos = db.session.query(db.func.max(CampaignStep.position)).filter_by(
        campaign_id=campaign_id
    ).scalar() or 0

    step = CampaignStep(
        campaign_id=campaign_id,
        tenant_id=str(tenant_id),
        position=data.get("position", max_pos + 1),
        channel=data.get("channel", "linkedin_message"),
        day_offset=data.get("day_offset", 0),
        label=data.get("label", ""),
        config=data.get("config", {}),
    )
    db.session.add(step)
    db.session.commit()
    return jsonify(step.to_dict()), 201


@bp.route("/api/campaigns/<campaign_id>/steps/<step_id>", methods=["PATCH"])
@require_auth
def update_step(campaign_id, step_id):
    tenant_id = request.tenant_id
    step = CampaignStep.query.filter_by(
        id=step_id, campaign_id=campaign_id, tenant_id=str(tenant_id)
    ).first()
    if not step:
        return jsonify({"error": "Step not found"}), 404

    data = request.get_json() or {}
    for field in ("channel", "day_offset", "label", "config", "position"):
        if field in data:
            setattr(step, field, data[field])

    db.session.commit()
    return jsonify(step.to_dict())


@bp.route("/api/campaigns/<campaign_id>/steps/<step_id>", methods=["DELETE"])
@require_auth
def delete_step(campaign_id, step_id):
    tenant_id = request.tenant_id
    step = CampaignStep.query.filter_by(
        id=step_id, campaign_id=campaign_id, tenant_id=str(tenant_id)
    ).first()
    if not step:
        return jsonify({"error": "Step not found"}), 404

    deleted_position = step.position
    db.session.delete(step)

    # Reorder remaining steps
    remaining = (CampaignStep.query
                 .filter_by(campaign_id=campaign_id, tenant_id=str(tenant_id))
                 .filter(CampaignStep.position > deleted_position)
                 .order_by(CampaignStep.position)
                 .all())
    for s in remaining:
        s.position -= 1

    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/campaigns/<campaign_id>/steps/reorder", methods=["PUT"])
@require_auth
def reorder_steps(campaign_id):
    tenant_id = request.tenant_id
    campaign = _get_campaign_or_404(campaign_id, tenant_id)
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    items = request.get_json()
    if not isinstance(items, list):
        return jsonify({"error": "Expected array of {id, position}"}), 400

    # Temporarily set positions to negative to avoid unique constraint conflicts
    for item in items:
        step = CampaignStep.query.filter_by(
            id=item["id"], campaign_id=campaign_id, tenant_id=str(tenant_id)
        ).first()
        if step:
            step.position = -item["position"]
    db.session.flush()

    # Now set real positions
    for item in items:
        step = CampaignStep.query.filter_by(
            id=item["id"], campaign_id=campaign_id, tenant_id=str(tenant_id)
        ).first()
        if step:
            step.position = item["position"]

    db.session.commit()

    steps = (CampaignStep.query
             .filter_by(campaign_id=campaign_id, tenant_id=str(tenant_id))
             .order_by(CampaignStep.position)
             .all())
    return jsonify([s.to_dict() for s in steps])


@bp.route("/api/campaigns/<campaign_id>/steps/from-template", methods=["POST"])
@require_auth
def populate_from_template(campaign_id):
    tenant_id = request.tenant_id
    campaign = _get_campaign_or_404(campaign_id, tenant_id)
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    data = request.get_json() or {}
    template_id = data.get("template_id")
    if not template_id:
        return jsonify({"error": "template_id required"}), 400

    template = CampaignTemplate.query.filter_by(id=template_id).first()
    if not template:
        return jsonify({"error": "Template not found"}), 404

    # Clear existing steps
    CampaignStep.query.filter_by(campaign_id=campaign_id, tenant_id=str(tenant_id)).delete()

    # Create steps from template
    steps_data = template.steps if isinstance(template.steps, list) else json.loads(template.steps or "[]")
    created = []
    for i, tpl_step in enumerate(steps_data, 1):
        step = CampaignStep(
            campaign_id=campaign_id,
            tenant_id=str(tenant_id),
            position=i,
            channel=tpl_step.get("channel", "linkedin_message"),
            day_offset=tpl_step.get("day_offset", 0),
            label=tpl_step.get("label", f"Step {i}"),
            config={
                k: v for k, v in tpl_step.items()
                if k not in ("channel", "day_offset", "label", "step", "enabled")
            },
        )
        db.session.add(step)
        created.append(step)

    db.session.commit()
    return jsonify([s.to_dict() for s in created]), 201
```

**Step 2: Register blueprint in `api/__init__.py`**

Find where other blueprints are registered and add:

```python
from api.routes.campaign_step_routes import bp as campaign_step_bp
app.register_blueprint(campaign_step_bp)
```

**Step 3: Run tests**

Run: `python -m pytest tests/unit/test_campaign_steps.py -v --tb=short`
Expected: All 7 tests PASS

**Step 4: Commit**

```bash
git add api/routes/campaign_step_routes.py api/__init__.py tests/unit/test_campaign_steps.py
git commit -m "feat: campaign steps CRUD API with tests"
```

---

### Task 4: Update message generator to use CampaignStep

**Files:**
- Modify: `api/services/message_generator.py` (lines 238–261, 565–621)
- Modify: `api/services/generation_prompts.py` (line 259)
- Test: `tests/unit/test_generation_with_steps.py`

**Step 1: Write failing test**

```python
# tests/unit/test_generation_with_steps.py
"""Test that generation reads from campaign_steps instead of template_config."""
import json
import pytest
from unittest.mock import patch, MagicMock


def _setup_campaign_with_steps(client, auth_headers):
    """Create campaign + steps + contact."""
    # Create campaign
    cid = client.post("/api/campaigns", headers=auth_headers, json={
        "name": "Steps Gen Test", "channel": "linkedin_message",
    }).get_json()["id"]

    # Add steps
    client.post(f"/api/campaigns/{cid}/steps", headers=auth_headers, json={
        "channel": "linkedin_connect", "day_offset": 0, "label": "Connect",
        "config": {
            "max_length": 300, "tone": "informal",
            "example_messages": [{"body": "Hey, love your work!", "note": "casual"}],
        }
    })
    client.post(f"/api/campaigns/{cid}/steps", headers=auth_headers, json={
        "channel": "linkedin_message", "day_offset": 3, "label": "Follow-up",
        "config": {"max_length": 500, "tone": "informal"},
    })

    return cid


class TestGenerationWithSteps:
    """Generation uses campaign_steps when available."""

    def test_cost_estimate_reads_steps(self, client, auth_headers):
        cid = _setup_campaign_with_steps(client, auth_headers)
        resp = client.post(
            f"/api/campaigns/{cid}/generation-cost-estimate",
            headers=auth_headers, json={}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["enabled_steps"] == 2

    def test_example_messages_in_prompt(self, client, auth_headers):
        """Verify example_messages from step config are injected into the prompt."""
        cid = _setup_campaign_with_steps(client, auth_headers)
        steps = client.get(f"/api/campaigns/{cid}/steps", headers=auth_headers).get_json()
        step = steps[0]
        assert step["config"]["example_messages"][0]["body"] == "Hey, love your work!"
```

**Step 2: Modify `_generate_all` in `message_generator.py`**

At line ~253, where `template_config` is read, add a fallback to `campaign_steps`:

```python
# NEW: prefer campaign_steps over template_config
from api.models import CampaignStep

campaign_steps = (CampaignStep.query
    .filter_by(campaign_id=campaign_id)
    .order_by(CampaignStep.position)
    .all())

if campaign_steps:
    enabled_steps = [
        {
            "step": s.position,
            "channel": s.channel,
            "label": s.label,
            "enabled": True,
            "day_offset": s.day_offset,
            "campaign_step_id": s.id,
            **(s.config or {}),
        }
        for s in campaign_steps
    ]
else:
    # Fallback to legacy template_config
    enabled_steps = [s for s in template_config if s.get("enabled")]
```

**Step 3: Modify `build_generation_prompt` in `generation_prompts.py`**

Add `example_messages` parameter (after line ~272):

```python
def build_generation_prompt(
    *, channel: str, step_label: str, contact_data: dict,
    company_data: dict, enrichment_data: dict,
    generation_config: dict, step_number: int, total_steps: int,
    strategy_data: dict | None = None, formality: str | None = None,
    per_message_instruction: str | None = None,
    example_messages: list | None = None,  # NEW
    max_length: int | None = None,  # NEW
) -> str
```

Add example messages section to the prompt (before FORMAT INSTRUCTIONS):

```python
# Example messages section
if example_messages:
    examples_text = "\n\n## REFERENCE EXAMPLES\nUse these as style/tone reference (do NOT copy verbatim):\n"
    for i, ex in enumerate(example_messages, 1):
        examples_text += f"\nExample {i}:\n{ex['body']}\n"
        if ex.get("note"):
            examples_text += f"(Note: {ex['note']})\n"
    sections.append(examples_text)

# Override max_length if step specifies it
if max_length:
    sections.append(f"\n## LENGTH LIMIT\nMaximum {max_length} characters. Be concise.")
```

**Step 4: Pass example_messages in `_generate_single_message`**

At line ~597, update the `build_generation_prompt` call to pass new params:

```python
prompt = build_generation_prompt(
    channel=step["channel"],
    step_label=step.get("label", f"Step {step['step']}"),
    # ... existing params ...
    example_messages=step.get("example_messages"),
    max_length=step.get("max_length"),
)
```

Also set `campaign_step_id` on the created Message if present in step dict:

```python
# After message creation (line ~615)
if step.get("campaign_step_id"):
    message.campaign_step_id = step["campaign_step_id"]
```

**Step 5: Run tests**

Run: `python -m pytest tests/unit/test_generation_with_steps.py tests/unit/test_generation_prompts.py -v --tb=short`
Expected: PASS

**Step 6: Commit**

```bash
git add api/services/message_generator.py api/services/generation_prompts.py tests/unit/test_generation_with_steps.py
git commit -m "feat: generation reads from campaign_steps with example messages + max_length"
```

---

### Task 5: Frontend — StepsTab component

**Files:**
- Create: `frontend/src/pages/campaigns/StepsTab.tsx`
- Modify: `frontend/src/pages/campaigns/CampaignDetailPage.tsx` (lines 32, 148-155)

**Step 1: Create StepsTab component**

Build a React component that:
1. Fetches steps from `GET /api/campaigns/{id}/steps`
2. Renders ordered step cards with channel, day_offset, label, config summary
3. Expandable config editor per step (max_length slider, tone selector, example messages list, custom instructions textarea)
4. Add step button (POST to API, append to list)
5. Delete step button (DELETE, reorder)
6. Drag-to-reorder (PUT reorder endpoint) — can use simple up/down arrows for v1
7. "From template" dropdown (POST from-template)
8. Example messages: add/remove text areas with optional note field

Channel defaults for max_length:
- `linkedin_connect`: 300
- `linkedin_message`: 1900
- `email`: 5000
- `call`: 2000

**Step 2: Add Steps tab to CampaignDetailPage.tsx**

At line 32, add `'steps'` to TAB_IDS:
```typescript
const TAB_IDS = ['contacts', 'steps', 'generation', 'review', 'outreach', 'analytics', 'settings'] as const
```

At lines 148-155, add tab definition:
```typescript
{ id: 'steps', label: 'Steps', badge: stepsCount || undefined },
```

Add the tab render:
```typescript
{activeTab === 'steps' && <StepsTab campaignId={campaign.id} />}
```

**Step 3: Type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS

**Step 4: Commit**

```bash
git add frontend/src/pages/campaigns/StepsTab.tsx frontend/src/pages/campaigns/CampaignDetailPage.tsx
git commit -m "feat: StepsTab UI — add/edit/reorder/delete steps with example messages"
```

---

### Task 6: Template-to-steps migration helper

**Files:**
- Modify: `api/routes/campaign_routes.py` (at `start_campaign_generation`, line ~1407)

**Step 1: Auto-migrate on generation start**

When `start_campaign_generation` is called and the campaign has `template_config` but no `campaign_steps`, auto-create steps from the template config. This ensures backwards compatibility.

Add at line ~1420 (before generation starts):

```python
# Auto-migrate template_config to campaign_steps if no steps exist
from api.models import CampaignStep

existing_steps = CampaignStep.query.filter_by(campaign_id=campaign_id).count()
if existing_steps == 0 and campaign.template_config:
    tpl_steps = campaign.template_config if isinstance(campaign.template_config, list) else json.loads(campaign.template_config or "[]")
    for i, ts in enumerate([s for s in tpl_steps if s.get("enabled")], 1):
        step = CampaignStep(
            campaign_id=campaign_id,
            tenant_id=str(tenant_id),
            position=i,
            channel=ts.get("channel", "linkedin_message"),
            day_offset=ts.get("day_offset", 0),
            label=ts.get("label", f"Step {i}"),
            config={k: v for k, v in ts.items() if k not in ("channel", "day_offset", "label", "step", "enabled")},
        )
        db.session.add(step)
    db.session.commit()
```

**Step 2: Test with existing test**

Run: `python -m pytest tests/unit/test_generation_endpoints.py -v --tb=short`
Expected: PASS (existing generation tests still work)

**Step 3: Commit**

```bash
git add api/routes/campaign_routes.py
git commit -m "feat: auto-migrate template_config to campaign_steps on generation start"
```

---

## Phase 2: Assets + File Storage

### Task 7: Migration — asset table

**Files:**
- Create: `migrations/050_assets.sql`

```sql
CREATE TABLE IF NOT EXISTS assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL,
    filename VARCHAR(500) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    storage_path VARCHAR(1000) NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assets_tenant ON assets(tenant_id);
CREATE INDEX IF NOT EXISTS idx_assets_campaign ON assets(campaign_id);
```

**Commit:**

```bash
git add migrations/050_assets.sql
git commit -m "feat: add assets table (migration 050)"
```

---

### Task 8: Asset model + S3 service

**Files:**
- Modify: `api/models.py` — add Asset model
- Create: `api/services/asset_service.py` — S3 upload/download/delete
- Test: `tests/unit/test_asset_service.py`

**Asset model:**

```python
class Asset(db.Model):
    __tablename__ = "assets"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey("tenants.id"), nullable=False)
    campaign_id = db.Column(db.String(36), db.ForeignKey("campaigns.id"), nullable=True)
    filename = db.Column(db.String(500), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    storage_path = db.Column(db.String(1000), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    metadata = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    def to_dict(self):
        return {
            "id": self.id, "tenant_id": self.tenant_id, "campaign_id": self.campaign_id,
            "filename": self.filename, "content_type": self.content_type,
            "size_bytes": self.size_bytes, "metadata": self.metadata or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
```

**S3 service** — uses boto3, bucket from env `ASSET_S3_BUCKET`, supports upload (streaming), presigned download URL, delete.

**Tests** — mock boto3, test upload returns asset record, test presigned URL generation, test delete removes S3 object + DB record.

---

### Task 9: Asset API routes

**Files:**
- Create: `api/routes/asset_routes.py`
- Test: `tests/unit/test_asset_routes.py`

Endpoints: `POST /api/assets/upload` (multipart), `GET /api/assets`, `GET /api/assets/{id}/download`, `DELETE /api/assets/{id}`

Validation: max 10MB, allowed content types (image/jpeg, image/png, application/pdf).

---

### Task 10: Asset picker in StepsTab

**Files:**
- Modify: `frontend/src/pages/campaigns/StepsTab.tsx`

Add to step config expand:
- File upload button → `POST /api/assets/upload`
- Asset picker (dropdown of existing tenant assets)
- Per-asset toggle: "Attach to message" vs "Reference only"
- Display attached assets with filename + type icon

---

### Task 11: Inject reference assets into generation prompt

**Files:**
- Modify: `api/services/message_generator.py`
- Modify: `api/services/generation_prompts.py`

When a step has `asset_ids` with mode `reference`:
1. Load asset records from DB
2. Include `asset.metadata.summary` in the prompt as a REFERENCE MATERIAL section
3. For PDFs: extract text summary on upload (store in `asset.metadata.summary`)

---

## Phase 3: AI Step Designer

### Task 12: AI design endpoint

**Files:**
- Create: `api/services/step_designer.py`
- Modify: `api/routes/campaign_step_routes.py` — add `/ai-design` and `/ai-design/confirm`
- Test: `tests/unit/test_step_designer.py`

**Step designer service:**
1. Receives: `{goal, channel_preference, num_steps, context}`
2. Loads: campaign contacts summary (count, top industries, seniority), strategy doc, previous campaign feedback stats
3. Calls Claude with a structured prompt asking it to design an outreach sequence
4. Returns: `{proposal_id, steps: [{channel, day_offset, label, config}], reasoning: "..."}`
5. Proposal stored in Redis/memory with TTL (or JSONB on campaign)

**Confirm endpoint:** Takes `{proposal_id, steps}` (possibly user-edited), saves as CampaignStep rows.

---

### Task 13: AI design UI

**Files:**
- Modify: `frontend/src/pages/campaigns/StepsTab.tsx`

Add "Let AI design steps" mode:
1. Text input for campaign goal
2. Optional: channel preference, num steps
3. Submit → spinner → show proposed steps as editable cards + reasoning text
4. "Accept & Save" button → confirm endpoint → reload steps

---

## Phase 4: Learning Loop

### Task 14: Migration — message_feedback table

**Files:**
- Create: `migrations/051_message_feedback.sql`

```sql
CREATE TABLE IF NOT EXISTS message_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    campaign_id UUID REFERENCES campaigns(id),
    action VARCHAR(50) NOT NULL,
    edit_diff JSONB,
    edit_reason VARCHAR(100),
    edit_reason_text TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_message_feedback_campaign ON message_feedback(campaign_id);
CREATE INDEX IF NOT EXISTS idx_message_feedback_message ON message_feedback(message_id);
```

---

### Task 15: Auto-capture feedback

**Files:**
- Modify: `api/routes/message_routes.py` (PATCH message, batch action)
- Modify: `api/models.py` — add MessageFeedback model
- Test: `tests/unit/test_message_feedback.py`

On every message status change (approve, reject, edit, regenerate):
1. Create `MessageFeedback` record with action, edit_diff (before/after body), edit_reason
2. Denormalize campaign_id for fast queries

---

### Task 16: Feedback summary endpoint

**Files:**
- Modify: `api/routes/campaign_routes.py`
- Test: `tests/unit/test_campaign_feedback.py`

`GET /api/campaigns/{id}/feedback-summary`:
- Approval rate per step (approved / total)
- Top edit reasons per step
- Most-edited steps
- Regeneration count per step

---

### Task 17: Feed learning signals into generation

**Files:**
- Modify: `api/services/message_generator.py`
- Modify: `api/services/generation_prompts.py`

When generating messages for a new campaign:
1. Query `message_feedback` for the tenant's recent campaigns (last 5)
2. Find approved messages → use as positive few-shot examples in prompts
3. Find rejected/edited messages → extract patterns to avoid
4. Include feedback summary in step designer prompt (Phase 3)

---

### Task 18: Learning indicators in review UI

**Files:**
- Modify: `frontend/src/pages/campaigns/MessagesTab.tsx`

Add per-step badges showing:
- "Step 1: 85% approved"
- "Step 2: 60% approved — 3 edits for 'too formal'"
- Color coding: green (>80%), yellow (50-80%), red (<50%)

---

## Execution Order & Dependencies

```
Phase 1 (core — must ship first):
  Task 1 (migration) → Task 2 (model) → Task 3 (API) → Task 4 (generator) → Task 5 (UI) → Task 6 (compat)

Phase 2 (parallel after Phase 1 Tasks 1-3):
  Task 7 (migration) → Task 8 (model+S3) → Task 9 (API) → Task 10 (UI) → Task 11 (prompt)

Phase 3 (after Phase 1 complete):
  Task 12 (AI endpoint) → Task 13 (AI UI)

Phase 4 (after Phase 1 complete, parallel with Phase 3):
  Task 14 (migration) → Task 15 (auto-capture) → Task 16 (summary API) → Task 17 (prompt) → Task 18 (UI)
```

**Parallelism:** Phase 2 Tasks 7-9 can start alongside Phase 1 Task 5-6. Phase 3 and Phase 4 are independent and can run in parallel after Phase 1.
