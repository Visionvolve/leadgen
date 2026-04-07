"""Tests for BL-173: Enrichment-Grounded Message Personalization.

Verifies that the message generation prompt includes enrichment data fields
and that the system prompt instructs the LLM to use them.
"""


class TestEnrichmentGroundedPrompts:
    """Test that generation prompts include enrichment data for grounded personalization."""

    def test_company_section_includes_size_and_revenue(self):
        from api.services.generation_prompts import _build_company_section

        company_data = {
            "name": "Acme Corp",
            "domain": "acme.com",
            "industry": "Software",
            "hq_country": "Germany",
            "summary": "Leading SaaS provider",
            "company_size": "201-500",
            "employee_count": "350",
            "revenue_eur_m": "25.0",
            "business_model": "SaaS",
        }
        enrichment_data = {"l2": {}, "person": {}}

        result = _build_company_section(company_data, enrichment_data)

        assert "Company Size: 201-500" in result
        assert "Employees: ~350" in result
        assert "Revenue: ~25.0M EUR" in result
        assert "Business Model: SaaS" in result

    def test_company_section_includes_pitch_framing(self):
        from api.services.generation_prompts import _build_company_section

        company_data = {"name": "Acme Corp"}
        enrichment_data = {
            "l2": {
                "pitch_framing": "Focus on cost reduction through automation",
                "expansion": "Just opened a new office in Berlin",
            },
            "person": {},
        }

        result = _build_company_section(company_data, enrichment_data)

        assert "Recommended Approach: Focus on cost reduction" in result
        assert "Growth/Expansion: Just opened" in result

    def test_enrichment_section_includes_growth_and_ma(self):
        from api.services.generation_prompts import _build_enrichment_section

        enrichment_data = {
            "l2": {
                "tech_stack": "Python, React, PostgreSQL",
                "pain_hypothesis": "Manual data entry costing 20 hours/week",
                "growth_signals": "Hired 50 engineers in Q4, opened new office",
                "ma_activity": "Acquired DataCo in January 2026",
            },
            "person": {},
        }

        result = _build_enrichment_section(enrichment_data)

        assert "Growth Signals: Hired 50 engineers" in result
        assert "M&A Activity: Acquired DataCo" in result
        assert "Tech Stack: Python" in result
        assert "Pain Points: Manual data entry" in result

    def test_enrichment_section_includes_ai_champion_indicator(self):
        from api.services.generation_prompts import _build_enrichment_section

        enrichment_data = {
            "l2": {},
            "person": {
                "ai_champion_score": 9,
                "authority_score": 8,
                "career_trajectory": "CTO for 5 years, previously VP Engineering",
            },
        }

        result = _build_enrichment_section(enrichment_data)

        assert "AI Champion: High likelihood" in result
        assert "Authority: Senior decision-maker" in result
        assert "Career Trajectory: CTO for 5 years" in result

    def test_enrichment_section_skips_low_scores(self):
        from api.services.generation_prompts import _build_enrichment_section

        enrichment_data = {
            "l2": {},
            "person": {
                "ai_champion_score": 3,  # below threshold
                "authority_score": 4,  # below threshold
            },
        }

        result = _build_enrichment_section(enrichment_data)

        assert "AI Champion" not in result
        assert "Authority" not in result

    def test_system_prompt_requires_enrichment_usage(self):
        from api.services.generation_prompts import SYSTEM_PROMPT

        assert "ENRICHMENT" in SYSTEM_PROMPT
        assert "enrichment facts" in SYSTEM_PROMPT.lower()

    def test_full_prompt_includes_all_sections(self):
        from api.services.generation_prompts import build_generation_prompt

        prompt = build_generation_prompt(
            channel="email",
            step_label="Initial Outreach",
            contact_data={
                "first_name": "John",
                "last_name": "Doe",
                "job_title": "CTO",
                "seniority_level": "C-Level",
                "department": "Technology",
            },
            company_data={
                "name": "Acme Corp",
                "industry": "Software",
                "company_size": "201-500",
                "employee_count": "350",
                "revenue_eur_m": "25.0",
                "summary": "Leading SaaS provider",
            },
            enrichment_data={
                "l2": {
                    "tech_stack": "Python, React",
                    "pain_hypothesis": "Manual workflows",
                    "recent_news": "Raised Series B",
                    "growth_signals": "Hiring 50 engineers",
                },
                "person": {
                    "person_summary": "Experienced tech leader",
                    "relationship_synthesis": "Strong AI advocate",
                    "career_trajectory": "CTO for 5 years",
                },
            },
            generation_config={"tone": "professional", "language": "en"},
            step_number=1,
            total_steps=3,
        )

        # Company data
        assert "Company Size: 201-500" in prompt
        assert "Employees: ~350" in prompt

        # Enrichment section
        assert "Tech Stack: Python, React" in prompt
        assert "Pain Points: Manual workflows" in prompt
        assert "Growth Signals: Hiring 50 engineers" in prompt

        # Contact enrichment
        assert "Person Summary: Experienced tech leader" in prompt
        assert "Career Trajectory: CTO for 5 years" in prompt


class TestLoadEnrichmentContext:
    """Test that _load_enrichment_context fetches richer data."""

    def test_loads_company_size_and_revenue(self, app, db, seed_tenant):
        from api.models import Company, CompanyEnrichmentL2, Contact, ContactEnrichment
        from api.services.message_generator import _load_enrichment_context

        with app.app_context():
            c = Company(
                tenant_id=seed_tenant.id,
                name="Test Corp",
                domain="test.com",
                industry="Software",
                hq_country="DE",
                company_size="51-200",
                verified_employees=150,
                verified_revenue_eur_m=10.5,
                tier="tier_1_platinum",
                business_model="SaaS",
                summary="Test company summary",
                status="enriched_l2",
            )
            db.session.add(c)
            db.session.flush()

            l2 = CompanyEnrichmentL2(
                company_id=c.id,
                company_intel="Enterprise software leader",
                recent_news="Expanded to Asia",
                ai_opportunities="Process mining",
                pain_hypothesis="Manual QA processes",
                key_products="DataPipe, FlowEngine",
                tech_stack="Java, Kubernetes",
                pitch_framing="Focus on time-to-market reduction",
                growth_signals="30% YoY revenue growth",
                expansion="New Singapore office",
                ma_activity="Acquired TestCo",
            )
            db.session.add(l2)

            ct = Contact(
                tenant_id=seed_tenant.id,
                company_id=c.id,
                first_name="Jane",
                last_name="Smith",
            )
            db.session.add(ct)
            db.session.flush()

            ce = ContactEnrichment(
                contact_id=ct.id,
                person_summary="Senior tech leader",
                relationship_synthesis="AI enthusiast",
                career_trajectory="VP Eng -> CTO",
                speaking_engagements="Spoke at PyCon 2025",
                publications="Published in IEEE",
                ai_champion_score=9,
                authority_score=8,
            )
            db.session.add(ce)
            db.session.commit()

            company_data, enrichment_data = _load_enrichment_context(
                str(ct.id), str(c.id)
            )

            # Company data should include enrichment-grounded fields
            assert company_data["company_size"] == "51-200"
            assert company_data["employee_count"] == "150"
            assert company_data["revenue_eur_m"] == "10.5"
            assert company_data["business_model"] == "SaaS"

            # L2 should include new fields
            assert (
                enrichment_data["l2"]["pitch_framing"]
                == "Focus on time-to-market reduction"
            )
            assert enrichment_data["l2"]["growth_signals"] == "30% YoY revenue growth"
            assert enrichment_data["l2"]["expansion"] == "New Singapore office"
            assert enrichment_data["l2"]["ma_activity"] == "Acquired TestCo"

            # Person should include richer fields
            assert enrichment_data["person"]["career_trajectory"] == "VP Eng -> CTO"
            assert enrichment_data["person"]["ai_champion_score"] == 9
            assert enrichment_data["person"]["authority_score"] == 8
