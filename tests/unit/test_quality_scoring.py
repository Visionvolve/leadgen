"""Tests for the block-level quality scoring module."""

from tests.conftest import auth_header as _auth_header


class TestComputeFieldCoverage:
    """Test compute_field_coverage()."""

    def test_full_coverage(self):
        from api.services.quality_scoring import compute_field_coverage

        data = {
            "digital_initiatives": "Some initiatives",
            "leadership_changes": "New CEO",
            "hiring_signals": "Growing team",
            "ai_hiring": "ML engineers",
            "tech_partnerships": "AWS",
            "ai_adoption_level": "advanced",
            "growth_indicators": "expanding",
            "job_posting_count": 42,
            "digital_maturity_score": "8",
            "it_spend_indicators": "high",
        }
        assert compute_field_coverage(data, "signals") == 1.0

    def test_partial_coverage(self):
        from api.services.quality_scoring import compute_field_coverage

        data = {
            "digital_initiatives": "Some initiatives",
            "leadership_changes": None,
            "hiring_signals": "Growing team",
        }
        assert compute_field_coverage(data, "signals") == 0.2

    def test_empty_values_excluded(self):
        from api.services.quality_scoring import compute_field_coverage

        data = {
            "digital_initiatives": "unverified",
            "leadership_changes": "unknown",
            "hiring_signals": "null",
            "ai_hiring": "none",
            "tech_partnerships": "n/a",
            "ai_adoption_level": "",
            "growth_indicators": "  Unknown  ",
            "job_posting_count": None,
            "digital_maturity_score": None,
            "it_spend_indicators": None,
        }
        assert compute_field_coverage(data, "signals") == 0.0

    def test_empty_list_not_counted(self):
        from api.services.quality_scoring import compute_field_coverage

        data = {
            "media_mentions": [],
            "press_releases": [],
            "sentiment_score": 0.5,
            "thought_leadership": "Great speaker",
            "news_summary": "Active in press",
        }
        # 3 out of 5 populated (empty lists not counted)
        assert compute_field_coverage(data, "news") == 0.6

    def test_unknown_block_returns_zero(self):
        from api.services.quality_scoring import compute_field_coverage

        assert compute_field_coverage({"foo": "bar"}, "nonexistent_block") == 0.0

    def test_zero_coverage(self):
        from api.services.quality_scoring import compute_field_coverage

        assert compute_field_coverage({}, "signals") == 0.0


class TestComputeQualityScore:
    """Test compute_quality_score()."""

    def test_perfect_score(self):
        from api.services.quality_scoring import compute_quality_score

        score = compute_quality_score(1.0, 1.0, [])
        assert score == 100

    def test_zero_everything(self):
        from api.services.quality_scoring import compute_quality_score

        score = compute_quality_score(0.0, 0.0, ["a", "b", "c", "d", "e"])
        assert score == 0

    def test_no_confidence_defaults_to_half(self):
        from api.services.quality_scoring import compute_quality_score

        # fc=1.0 -> 60, conf=None->0.5 -> 15, no flags -> 10
        score = compute_quality_score(1.0, None, [])
        assert score == 85

    def test_flags_reduce_score(self):
        from api.services.quality_scoring import compute_quality_score

        score_no_flags = compute_quality_score(0.5, 0.5, [])
        score_2_flags = compute_quality_score(0.5, 0.5, ["flag1", "flag2"])
        assert score_2_flags < score_no_flags

    def test_score_clamped_to_0_100(self):
        from api.services.quality_scoring import compute_quality_score

        score = compute_quality_score(0.0, 0.0, ["a"] * 10)
        assert score >= 0
        assert score <= 100

    def test_with_zero_confidence(self):
        from api.services.quality_scoring import compute_quality_score

        score = compute_quality_score(1.0, 0.0, [])
        # 60 + 0 + 10 = 70
        assert score == 70


class TestAssessBlockQuality:
    """Test assess_block_quality()."""

    def test_high_quality_block(self):
        from api.services.quality_scoring import assess_block_quality

        data = {
            "digital_initiatives": "Cloud migration",
            "leadership_changes": "New CTO",
            "hiring_signals": "Expanding eng team",
            "ai_hiring": "5 ML roles",
            "tech_partnerships": "AWS Advanced",
            "ai_adoption_level": "advanced",
            "growth_indicators": "Revenue up 30%",
            "job_posting_count": 25,
            "digital_maturity_score": "8",
            "it_spend_indicators": "High",
        }
        result = assess_block_quality(
            data=data,
            block_code="signals",
            confidence=0.9,
        )
        assert result.quality_score >= 80
        assert result.field_coverage == 1.0
        assert result.confidence == 0.9
        assert "incomplete_research" not in result.qc_flags

    def test_low_quality_adds_universal_flags(self):
        from api.services.quality_scoring import assess_block_quality

        data = {"digital_initiatives": "Something"}
        result = assess_block_quality(
            data=data,
            block_code="signals",
            confidence=0.2,
        )
        assert "incomplete_research" in result.qc_flags
        assert "low_confidence" in result.qc_flags
        assert result.quality_score < 50

    def test_extra_flags_included(self):
        from api.services.quality_scoring import assess_block_quality

        data = {
            "digital_initiatives": "Cloud",
            "leadership_changes": "CTO",
            "hiring_signals": "Growing",
            "ai_hiring": "ML",
            "tech_partnerships": "AWS",
            "ai_adoption_level": "early",
            "growth_indicators": "expanding",
            "job_posting_count": 10,
            "digital_maturity_score": "7",
            "it_spend_indicators": "medium",
        }
        result = assess_block_quality(
            data=data,
            block_code="signals",
            confidence=0.8,
            extra_flags=["no_ai_signals"],
        )
        assert "no_ai_signals" in result.qc_flags

    def test_deduplicates_flags(self):
        from api.services.quality_scoring import assess_block_quality

        data = {}
        result = assess_block_quality(
            data=data,
            block_code="signals",
            confidence=0.2,
            extra_flags=["low_confidence", "incomplete_research"],
        )
        assert len(result.qc_flags) == len(set(result.qc_flags))

    def test_none_confidence_handled(self):
        from api.services.quality_scoring import assess_block_quality

        data = {"media_mentions": [{"title": "News"}], "news_summary": "Summary"}
        result = assess_block_quality(
            data=data,
            block_code="news",
            confidence=None,
        )
        assert result.confidence is None
        assert "low_confidence" not in result.qc_flags


class TestParseConfidence:
    """Test parse_confidence()."""

    def test_float_value(self):
        from api.services.quality_scoring import parse_confidence

        assert parse_confidence(0.85) == 0.85

    def test_string_value(self):
        from api.services.quality_scoring import parse_confidence

        assert parse_confidence("0.7") == 0.7

    def test_percentage_value(self):
        from api.services.quality_scoring import parse_confidence

        assert parse_confidence(85) == 0.85

    def test_none_value(self):
        from api.services.quality_scoring import parse_confidence

        assert parse_confidence(None) is None

    def test_invalid_string(self):
        from api.services.quality_scoring import parse_confidence

        assert parse_confidence("high") is None

    def test_clamped_to_range(self):
        from api.services.quality_scoring import parse_confidence

        # Values > 1.0 are treated as percentages (divided by 100)
        assert parse_confidence(85) == 0.85
        assert parse_confidence(100) == 1.0
        # Negative values clamped to 0
        assert parse_confidence(-0.5) == 0.0


class TestBlockFieldSpecs:
    """Test that block field specs cover all expected blocks."""

    def test_all_blocks_defined(self):
        from api.services.quality_scoring import BLOCK_FIELD_SPECS

        expected_blocks = [
            "l2_profile",
            "l2_opportunity",
            "signals",
            "news",
            "registry",
            "person",
            "social",
            "career",
            "contact_details",
        ]
        for block in expected_blocks:
            assert block in BLOCK_FIELD_SPECS, f"Missing block spec: {block}"
            assert len(BLOCK_FIELD_SPECS[block]) > 0, f"Empty field spec: {block}"


class TestQualityAPIEndpoints:
    """Test quality API endpoints."""

    def test_company_quality_endpoint(self, client, seed_companies_contacts):
        """Test GET /api/companies/<id>/quality returns correct structure."""
        from api.models import Company

        company = Company.query.first()
        headers = _auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.get(
            f"/api/companies/{company.id}/quality",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "company_id" in data
        assert "blocks" in data
        assert "aggregate" in data
        for block in [
            "l1",
            "l2_profile",
            "l2_opportunity",
            "signals",
            "news",
            "registry",
        ]:
            assert block in data["blocks"]

    def test_company_quality_not_found(self, client, seed_companies_contacts):
        """Test GET /api/companies/<bad_id>/quality returns 404."""
        headers = _auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get(
            "/api/companies/00000000-0000-0000-0000-000000000000/quality",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_contact_quality_endpoint(self, client, seed_companies_contacts):
        """Test GET /api/contacts/<id>/quality returns correct structure."""
        from api.models import Contact

        contact = Contact.query.first()
        headers = _auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.get(
            f"/api/contacts/{contact.id}/quality",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "contact_id" in data
        assert "blocks" in data
        assert "aggregate" in data
        for block in ["person", "social", "career", "contact_details"]:
            assert block in data["blocks"]

    def test_contact_quality_not_found(self, client, seed_companies_contacts):
        """Test GET /api/contacts/<bad_id>/quality returns 404."""
        headers = _auth_header(client)
        headers["X-Namespace"] = "test-corp"
        resp = client.get(
            "/api/contacts/00000000-0000-0000-0000-000000000000/quality",
            headers=headers,
        )
        assert resp.status_code == 404
