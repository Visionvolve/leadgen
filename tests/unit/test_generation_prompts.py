"""Tests for generation prompt building with playbook strategy + enrichment context.

Tests cover:
- Strategy section formatting from playbook extracted_data
- Graceful fallback when no playbook exists
- Enrichment data formatting (L2 deep research, person data)
- Strategy snapshot storage in campaign generation_config
- Backward compatibility (prompts work without strategy_data)
"""

import json
from unittest.mock import patch, MagicMock

from api.services.generation_prompts import (
    _build_strategy_section,
    _build_enrichment_section,
    build_generation_prompt,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_STRATEGY_DATA = {
    "icp": {
        "industries": ["SaaS", "FinTech"],
        "company_size": {"min": 50, "max": 500},
        "geographies": ["DACH", "Nordics"],
        "tech_signals": ["Kubernetes", "React"],
        "triggers": ["new CTO hire", "Series B+"],
        "disqualifiers": ["less than 10 employees"],
    },
    "personas": [
        {
            "title_patterns": ["CTO", "VP Engineering"],
            "pain_points": ["legacy modernization", "scaling teams"],
            "goals": ["ship faster", "reduce tech debt"],
        },
        {
            "title_patterns": ["Head of Data"],
            "pain_points": ["data silos", "ML deployment"],
            "goals": ["unified data platform"],
        },
    ],
    "messaging": {
        "tone": "consultative",
        "themes": ["AI-powered automation", "developer productivity"],
        "angles": ["ROI case study", "quick win pilot"],
        "proof_points": ["3x deployment speed", "40% cost reduction"],
    },
    "channels": {
        "primary": "LinkedIn",
        "secondary": ["email", "events"],
        "cadence": "weekly touchpoints",
    },
    "metrics": {
        "reply_rate_target": 0.15,
        "meeting_rate_target": 0.05,
        "pipeline_goal_eur": 500000,
        "timeline_months": 6,
    },
    "competitive_positioning": "Only vendor combining AI consulting with hands-on implementation",
    "value_proposition": "We help mid-market SaaS companies ship AI features 3x faster",
}

SAMPLE_CONTACT_DATA = {
    "first_name": "Jan",
    "last_name": "Novak",
    "job_title": "CTO",
    "email_address": "jan@example.com",
    "linkedin_url": "https://linkedin.com/in/jannovak",
    "seniority_level": "c_level",
    "department": "engineering",
}

SAMPLE_COMPANY_DATA = {
    "name": "TechCorp s.r.o.",
    "domain": "techcorp.cz",
    "industry": "technology",
    "hq_country": "Czech Republic",
    "summary": "Mid-size SaaS company focused on logistics automation",
}

SAMPLE_ENRICHMENT_DATA = {
    "l2": {
        "company_intel": "Leader in CEE logistics tech",
        "recent_news": "Raised Series B, EUR 15M",
        "ai_opportunities": "Route optimization, demand forecasting",
        "tech_stack": "Python, PostgreSQL, Kubernetes",
        "pain_hypothesis": "Manual dispatch processes, scaling bottleneck",
        "key_products": "RouteAI, FleetManager",
        "customer_segments": "3PL providers, e-commerce fulfillment",
        "competitors": "FourKites, project44",
        "digital_initiatives": "API platform launch Q2",
        "hiring_signals": "3 ML engineer openings",
    },
    "person": {
        "person_summary": "Former Google engineer, 15 years in logistics tech",
        "relationship_synthesis": "Connected through Prague AI meetup",
        "career_trajectory": "Google -> Shippo -> TechCorp (CTO)",
        "speaking_engagements": "DevConf.cz 2025, PyCon CZ 2024",
        "publications": "Blog on ML in logistics",
    },
}

SAMPLE_GENERATION_CONFIG = {
    "tone": "professional",
    "language": "en",
    "custom_instructions": "",
}


# ---------------------------------------------------------------------------
# Tests: _build_strategy_section
# ---------------------------------------------------------------------------


class TestBuildStrategySection:
    """Tests for _build_strategy_section formatting."""

    def test_full_strategy_data(self):
        """All strategy fields are included when present."""
        result = _build_strategy_section(SAMPLE_STRATEGY_DATA)

        assert "ICP:" in result
        assert "SaaS" in result
        assert "FinTech" in result
        assert "50-500 employees" in result
        assert "DACH" in result
        assert "Value Proposition:" in result
        assert "3x faster" in result
        assert "Messaging Framework:" in result
        assert "consultative" in result
        assert "AI-powered automation" in result
        assert "Competitive Position:" in result
        assert "Only vendor" in result
        assert "Buyer Personas:" in result
        assert "CTO" in result
        assert "VP Engineering" in result
        assert "legacy modernization" in result
        assert "Channel Strategy:" in result
        assert "LinkedIn" in result

    def test_empty_strategy_data(self):
        """Empty dict returns empty string."""
        result = _build_strategy_section({})
        assert result == ""

    def test_none_strategy_data(self):
        """None returns empty string."""
        result = _build_strategy_section(None)
        assert result == ""

    def test_partial_strategy_data(self):
        """Only available fields are included."""
        partial = {
            "icp": {
                "industries": ["Healthcare"],
            },
            "value_proposition": "HIPAA-compliant AI solutions",
        }
        result = _build_strategy_section(partial)

        assert "Healthcare" in result
        assert "HIPAA-compliant" in result
        assert "Messaging Framework" not in result
        assert "Competitive Position" not in result
        assert "Buyer Personas" not in result

    def test_icp_as_string(self):
        """ICP can be a plain string (non-structured)."""
        result = _build_strategy_section({"icp": "Mid-market SaaS in DACH"})
        assert "ICP: Mid-market SaaS in DACH" in result

    def test_competitive_positioning_as_list(self):
        """Competitive positioning can be a list."""
        result = _build_strategy_section(
            {"competitive_positioning": ["AI-first", "Hands-on implementation"]}
        )
        assert "AI-first" in result
        assert "Hands-on implementation" in result

    def test_personas_limited_to_three(self):
        """At most 3 personas are included."""
        many_personas = {
            "personas": [
                {
                    "title_patterns": [f"Persona {i}"],
                    "pain_points": [f"pain {i}"],
                    "goals": [],
                }
                for i in range(5)
            ]
        }
        result = _build_strategy_section(many_personas)

        assert "Persona 0" in result
        assert "Persona 1" in result
        assert "Persona 2" in result
        assert "Persona 3" not in result
        assert "Persona 4" not in result

    def test_messaging_as_string(self):
        """Messaging framework can be a plain string."""
        result = _build_strategy_section({"messaging": "Lead with ROI data"})
        assert "Messaging Framework: Lead with ROI data" in result


# ---------------------------------------------------------------------------
# Tests: _build_enrichment_section
# ---------------------------------------------------------------------------


class TestBuildEnrichmentSection:
    """Tests for _build_enrichment_section formatting."""

    def test_full_enrichment_data(self):
        """All enrichment fields included when present."""
        result = _build_enrichment_section(SAMPLE_ENRICHMENT_DATA)

        assert "Tech Stack: Python, PostgreSQL, Kubernetes" in result
        assert "Pain Points: Manual dispatch" in result
        assert "Products: RouteAI" in result
        assert "Customer Segments: 3PL providers" in result
        assert "Competitors: FourKites" in result
        assert "Digital Initiatives: API platform launch" in result
        assert "Hiring Signals: 3 ML engineer" in result
        assert "Career Trajectory: Google" in result
        assert "Speaking: DevConf.cz" in result
        assert "Publications: Blog on ML" in result

    def test_empty_enrichment(self):
        """Empty enrichment returns empty string."""
        result = _build_enrichment_section({})
        assert result == ""

    def test_none_enrichment(self):
        """None returns empty string."""
        result = _build_enrichment_section(None)
        assert result == ""

    def test_l2_only(self):
        """Only L2 data, no person data."""
        result = _build_enrichment_section(
            {
                "l2": {"tech_stack": "Java, Spring Boot"},
                "person": {},
            }
        )
        assert "Tech Stack: Java" in result
        assert "Career Trajectory" not in result

    def test_person_only(self):
        """Only person data, no L2 data."""
        result = _build_enrichment_section(
            {
                "l2": {},
                "person": {"career_trajectory": "McKinsey -> Startup -> CTO"},
            }
        )
        assert "Career Trajectory: McKinsey" in result
        assert "Tech Stack" not in result


# ---------------------------------------------------------------------------
# Tests: build_generation_prompt — strategy integration
# ---------------------------------------------------------------------------


class TestBuildGenerationPromptWithStrategy:
    """Tests for strategy context injection into generation prompt."""

    def test_prompt_includes_strategy_section(self):
        """Prompt includes STRATEGY section when strategy_data is provided."""
        prompt = build_generation_prompt(
            channel="email",
            step_label="Intro Email",
            contact_data=SAMPLE_CONTACT_DATA,
            company_data=SAMPLE_COMPANY_DATA,
            enrichment_data=SAMPLE_ENRICHMENT_DATA,
            generation_config=SAMPLE_GENERATION_CONFIG,
            step_number=1,
            total_steps=3,
            strategy_data=SAMPLE_STRATEGY_DATA,
        )

        assert "--- STRATEGY ---" in prompt
        assert "ICP:" in prompt
        assert "Value Proposition:" in prompt
        assert "Messaging Framework:" in prompt
        assert "Competitive Position:" in prompt

    def test_prompt_without_strategy(self):
        """Prompt works without strategy_data (graceful fallback)."""
        prompt = build_generation_prompt(
            channel="email",
            step_label="Intro Email",
            contact_data=SAMPLE_CONTACT_DATA,
            company_data=SAMPLE_COMPANY_DATA,
            enrichment_data=SAMPLE_ENRICHMENT_DATA,
            generation_config=SAMPLE_GENERATION_CONFIG,
            step_number=1,
            total_steps=3,
        )

        assert "--- STRATEGY ---" not in prompt
        # Other sections still present
        assert "--- CONTACT ---" in prompt
        assert "--- COMPANY ---" in prompt
        assert "--- SEQUENCE CONTEXT ---" in prompt
        assert "--- OUTPUT FORMAT ---" in prompt

    def test_prompt_with_none_strategy(self):
        """Explicitly passing None for strategy_data omits strategy section."""
        prompt = build_generation_prompt(
            channel="linkedin_connect",
            step_label="Connection Request",
            contact_data=SAMPLE_CONTACT_DATA,
            company_data=SAMPLE_COMPANY_DATA,
            enrichment_data={"l2": {}, "person": {}},
            generation_config=SAMPLE_GENERATION_CONFIG,
            step_number=1,
            total_steps=1,
            strategy_data=None,
        )

        assert "--- STRATEGY ---" not in prompt

    def test_prompt_with_empty_strategy(self):
        """Empty strategy dict omits strategy section."""
        prompt = build_generation_prompt(
            channel="email",
            step_label="Follow-up",
            contact_data=SAMPLE_CONTACT_DATA,
            company_data=SAMPLE_COMPANY_DATA,
            enrichment_data={"l2": {}, "person": {}},
            generation_config=SAMPLE_GENERATION_CONFIG,
            step_number=2,
            total_steps=3,
            strategy_data={},
        )

        assert "--- STRATEGY ---" not in prompt

    def test_strategy_appears_between_company_and_sequence(self):
        """STRATEGY section is placed between COMPANY and SEQUENCE CONTEXT."""
        prompt = build_generation_prompt(
            channel="email",
            step_label="Intro",
            contact_data=SAMPLE_CONTACT_DATA,
            company_data=SAMPLE_COMPANY_DATA,
            enrichment_data=SAMPLE_ENRICHMENT_DATA,
            generation_config=SAMPLE_GENERATION_CONFIG,
            step_number=1,
            total_steps=1,
            strategy_data=SAMPLE_STRATEGY_DATA,
        )

        company_pos = prompt.index("--- COMPANY ---")
        strategy_pos = prompt.index("--- STRATEGY ---")
        sequence_pos = prompt.index("--- SEQUENCE CONTEXT ---")

        assert company_pos < strategy_pos < sequence_pos

    def test_enrichment_section_included(self):
        """Prompt includes ENRICHMENT section when enrichment has deep data."""
        prompt = build_generation_prompt(
            channel="email",
            step_label="Intro",
            contact_data=SAMPLE_CONTACT_DATA,
            company_data=SAMPLE_COMPANY_DATA,
            enrichment_data=SAMPLE_ENRICHMENT_DATA,
            generation_config=SAMPLE_GENERATION_CONFIG,
            step_number=1,
            total_steps=1,
            strategy_data=SAMPLE_STRATEGY_DATA,
        )

        assert "--- ENRICHMENT ---" in prompt
        assert "Tech Stack:" in prompt
        assert "Pain Points:" in prompt

    def test_enrichment_section_omitted_when_empty(self):
        """ENRICHMENT section omitted when no deep data."""
        prompt = build_generation_prompt(
            channel="email",
            step_label="Intro",
            contact_data=SAMPLE_CONTACT_DATA,
            company_data=SAMPLE_COMPANY_DATA,
            enrichment_data={"l2": {}, "person": {}},
            generation_config=SAMPLE_GENERATION_CONFIG,
            step_number=1,
            total_steps=1,
        )

        assert "--- ENRICHMENT ---" not in prompt

    def test_backward_compatibility_no_new_args(self):
        """Prompt builds correctly with the original signature (no strategy)."""
        prompt = build_generation_prompt(
            channel="linkedin_message",
            step_label="InMail",
            contact_data={"first_name": "Test"},
            company_data={"name": "TestCo"},
            enrichment_data={"l2": {}, "person": {}},
            generation_config={"tone": "casual", "language": "cs"},
            step_number=1,
            total_steps=1,
        )

        assert "--- CONTACT ---" in prompt
        assert "--- COMPANY ---" in prompt
        assert "--- SEQUENCE CONTEXT ---" in prompt
        assert "Tone: casual" in prompt
        assert "Language: cs" in prompt


# ---------------------------------------------------------------------------
# Tests: Recipient name clarity + greeting validation
# ---------------------------------------------------------------------------


class TestRecipientNameClarity:
    """Tests that prompts clearly distinguish sender from recipient."""

    def test_contact_section_labels_recipient(self):
        """Contact section prominently labels the name as RECIPIENT."""
        from api.services.generation_prompts import _build_contact_section

        section = _build_contact_section(
            {"first_name": "Aneta", "last_name": "Novakova"},
            {"l2": {}, "person": {}},
        )
        assert "RECIPIENT NAME" in section
        assert "Aneta Novakova" in section
        assert "RECIPIENT FIRST NAME: Aneta" in section

    def test_system_prompt_distinguishes_sender_recipient(self):
        """SYSTEM_PROMPT explicitly separates sender and recipient identity."""
        from api.services.generation_prompts import SYSTEM_PROMPT

        assert "SENDER" in SYSTEM_PROMPT
        assert "RECIPIENT" in SYSTEM_PROMPT
        assert "RECIPIENT NAME IN GREETING" in SYSTEM_PROMPT
        # Sender identity is clearly marked
        assert "writing AS the SENDER" in SYSTEM_PROMPT
        # Recipient identity is clearly marked
        assert "writing TO the RECIPIENT" in SYSTEM_PROMPT

    def test_vocative_rule_references_recipient(self):
        """Vocative rule explicitly says to use the RECIPIENT's first name."""
        from api.services.generation_prompts import SYSTEM_PROMPT

        assert "RECIPIENT's first name" in SYSTEM_PROMPT
        # Additional vocative examples for names that caused bugs
        assert "Anna" in SYSTEM_PROMPT and "Anno" in SYSTEM_PROMPT
        assert "Aneta" in SYSTEM_PROMPT and "Aneto" in SYSTEM_PROMPT


class TestValidateGreetingName:
    """Tests for _validate_greeting_name post-generation check."""

    def test_exact_match(self):
        from api.services.message_generator import _validate_greeting_name

        assert _validate_greeting_name("Dobrý den, Aneto,\nráda bych...", "Aneta")

    def test_vocative_match(self):
        from api.services.message_generator import _validate_greeting_name

        assert _validate_greeting_name("Ahoj Anno,\ndovolte mi...", "Anna")

    def test_wrong_name_detected(self):
        from api.services.message_generator import _validate_greeting_name

        # Sender name "Hanka" used instead of recipient "Aneta"
        assert not _validate_greeting_name("Dobrý den, Hanko,\nráda bych...", "Aneta")

    def test_empty_first_name_passes(self):
        from api.services.message_generator import _validate_greeting_name

        assert _validate_greeting_name("Hello,\nsome body text", "")

    def test_empty_body_passes(self):
        from api.services.message_generator import _validate_greeting_name

        assert _validate_greeting_name("", "Aneta")

    def test_name_in_body_not_greeting(self):
        """Name appearing after the first 120 chars is NOT counted."""
        from api.services.message_generator import _validate_greeting_name

        body = "X" * 130 + "Aneta"
        assert not _validate_greeting_name(body, "Aneta")

    def test_case_insensitive(self):
        from api.services.message_generator import _validate_greeting_name

        assert _validate_greeting_name("dobrý den, aneto,", "Aneta")


# ---------------------------------------------------------------------------
# Tests: Strategy snapshot in generation_config
# ---------------------------------------------------------------------------


class TestStrategySnapshot:
    """Tests that strategy data is snapshotted in campaign.generation_config."""

    def test_load_strategy_data_returns_extracted_data(self, app, db):
        """_load_strategy_data returns extracted_data from StrategyDocument."""
        from api.models import Tenant, StrategyDocument
        from api.services.message_generator import _load_strategy_data

        tenant = Tenant(name="Snap Corp", slug="snap-corp")
        db.session.add(tenant)
        db.session.flush()

        doc = StrategyDocument(
            tenant_id=tenant.id,
            content="# Strategy",
            extracted_data=json.dumps(SAMPLE_STRATEGY_DATA),
            status="active",
        )
        db.session.add(doc)
        db.session.commit()

        result = _load_strategy_data(str(tenant.id))
        assert result is not None
        assert result["icp"]["industries"] == ["SaaS", "FinTech"]
        assert (
            result["value_proposition"]
            == "We help mid-market SaaS companies ship AI features 3x faster"
        )

    def test_load_strategy_data_returns_none_when_no_doc(self, app, db):
        """_load_strategy_data returns None when no StrategyDocument exists."""
        from api.models import Tenant
        from api.services.message_generator import _load_strategy_data

        tenant = Tenant(name="Empty Corp", slug="empty-corp")
        db.session.add(tenant)
        db.session.commit()

        result = _load_strategy_data(str(tenant.id))
        assert result is None

    def test_load_strategy_data_returns_none_for_empty_data(self, app, db):
        """_load_strategy_data returns None when extracted_data is empty dict."""
        from api.models import Tenant, StrategyDocument
        from api.services.message_generator import _load_strategy_data

        tenant = Tenant(name="Blank Corp", slug="blank-corp")
        db.session.add(tenant)
        db.session.flush()

        doc = StrategyDocument(
            tenant_id=tenant.id,
            content="",
            extracted_data=json.dumps({}),
            status="draft",
        )
        db.session.add(doc)
        db.session.commit()

        result = _load_strategy_data(str(tenant.id))
        assert result is None

    def test_strategy_snapshot_stored_in_generation_config(self, app, db):
        """_generate_all stores strategy_snapshot in campaign.generation_config."""
        from api.models import (
            Tenant,
            Owner,
            Campaign,
            Contact,
            CampaignContact,
            StrategyDocument,
        )
        from api.services.message_generator import _generate_all

        # Setup tenant + strategy doc
        tenant = Tenant(name="Snap Test", slug="snap-test")
        db.session.add(tenant)
        db.session.flush()

        owner = Owner(tenant_id=tenant.id, name="Test Owner")
        db.session.add(owner)
        db.session.flush()

        doc = StrategyDocument(
            tenant_id=tenant.id,
            content="# Strategy",
            extracted_data=json.dumps({"icp": {"industries": ["FinTech"]}}),
            status="active",
        )
        db.session.add(doc)

        # Create campaign with a contact
        campaign = Campaign(
            tenant_id=tenant.id,
            owner_id=owner.id,
            name="Test Campaign",
            status="generating",
            template_config=json.dumps(
                [
                    {"step": 1, "label": "Intro", "channel": "email", "enabled": True},
                ]
            ),
            generation_config=json.dumps({"tone": "professional", "language": "en"}),
        )
        db.session.add(campaign)
        db.session.flush()

        contact = Contact(
            tenant_id=tenant.id,
            first_name="Test",
            last_name="User",
            job_title="CTO",
            email_address="test@example.com",
        )
        db.session.add(contact)
        db.session.flush()

        cc = CampaignContact(
            campaign_id=campaign.id,
            contact_id=contact.id,
            tenant_id=tenant.id,
            status="pending",
        )
        db.session.add(cc)
        db.session.commit()

        # Mock the Anthropic API call
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(text='{"subject": "Hi", "body": "Test message"}')
        ]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        with patch.dict("sys.modules", {"anthropic": MagicMock()}) as _:
            import anthropic as mock_anthropic

            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = mock_response

            _generate_all(str(campaign.id), str(tenant.id), None)

        # Verify strategy_snapshot was stored
        row = db.session.execute(
            db.text("SELECT generation_config FROM campaigns WHERE id = :id"),
            {"id": campaign.id},
        ).fetchone()

        gen_config = row[0]
        if isinstance(gen_config, str):
            gen_config = json.loads(gen_config)

        assert "strategy_snapshot" in gen_config
        assert gen_config["strategy_snapshot"]["icp"]["industries"] == ["FinTech"]

    def test_no_snapshot_when_no_strategy(self, app, db):
        """generation_config is unchanged when no StrategyDocument exists."""
        from api.models import Tenant, Owner, Campaign, Contact, CampaignContact
        from api.services.message_generator import _generate_all

        tenant = Tenant(name="No Strat", slug="no-strat")
        db.session.add(tenant)
        db.session.flush()

        owner = Owner(tenant_id=tenant.id, name="Owner")
        db.session.add(owner)
        db.session.flush()

        campaign = Campaign(
            tenant_id=tenant.id,
            owner_id=owner.id,
            name="No Strategy Campaign",
            status="generating",
            template_config=json.dumps(
                [
                    {"step": 1, "label": "Intro", "channel": "email", "enabled": True},
                ]
            ),
            generation_config=json.dumps({"tone": "casual", "language": "cs"}),
        )
        db.session.add(campaign)
        db.session.flush()

        contact = Contact(
            tenant_id=tenant.id,
            first_name="Test",
            last_name="User",
            email_address="t@example.com",
        )
        db.session.add(contact)
        db.session.flush()

        cc = CampaignContact(
            campaign_id=campaign.id,
            contact_id=contact.id,
            tenant_id=tenant.id,
            status="pending",
        )
        db.session.add(cc)
        db.session.commit()

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"subject": "Hi", "body": "Test"}')]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        with patch.dict("sys.modules", {"anthropic": MagicMock()}) as _:
            import anthropic as mock_anthropic

            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = mock_response

            _generate_all(str(campaign.id), str(tenant.id), None)

        row = db.session.execute(
            db.text("SELECT generation_config FROM campaigns WHERE id = :id"),
            {"id": campaign.id},
        ).fetchone()

        gen_config = row[0]
        if isinstance(gen_config, str):
            gen_config = json.loads(gen_config)

        assert "strategy_snapshot" not in gen_config
        assert gen_config["tone"] == "casual"
        assert gen_config["language"] == "cs"
