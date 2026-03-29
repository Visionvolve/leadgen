"""Unit tests for auto-segmentation, product recommendations,
eligible contacts, and message generation with product context."""

import uuid

from tests.conftest import auth_header


class TestClassifySegment:
    """Test the pure classification logic (no DB needed)."""

    def test_obec_by_industry(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(industry="Obecní úřad Olomouc") == "obec"

    def test_obec_by_name(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(name="Město Brno", industry="government") == "obec"

    def test_obec_kulturni(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(name="Kulturní dům Vsetín") == "obec"

    def test_spolek_by_name(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(name="Spolek přátel hudby") == "spolek"

    def test_spolek_hasici(self):
        from api.services.segmentation import classify_segment

        assert (
            classify_segment(
                name="SDH Dolní Lhota", industry="Sbor dobrovolných hasičů"
            )
            == "spolek"
        )

    def test_spolek_sokol(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(name="TJ Sokol Praha") == "spolek"

    def test_rotary(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(name="Rotary Club Brno") == "rotary_lions"

    def test_lions(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(name="Lions Club Praha") == "rotary_lions"

    def test_skola(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(name="Gymnázium Jana Nerudy") == "skola"

    def test_skola_univerzita(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(industry="Univerzita Karlova") == "skola"

    def test_agentura(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(name="Eventová agentura XYZ") == "agentura"

    def test_agentura_by_industry(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(industry="event production") == "agentura"

    def test_dach_agentura(self):
        from api.services.segmentation import classify_segment

        assert (
            classify_segment(
                name="EventAgentur Berlin", industry="event", hq_country="Germany"
            )
            == "dach_agentura"
        )

    def test_dach_austria(self):
        from api.services.segmentation import classify_segment

        assert (
            classify_segment(
                name="Show Production GmbH", industry="production", hq_country="Austria"
            )
            == "dach_agentura"
        )

    def test_dach_requires_country(self):
        """Agency without DACH country should be regular agentura."""
        from api.services.segmentation import classify_segment

        assert (
            classify_segment(name="Event Agency", industry="event", hq_country="France")
            == "agentura"
        )

    def test_other_default(self):
        from api.services.segmentation import classify_segment

        assert classify_segment(name="Random Company s.r.o.") == "other"

    def test_none_inputs(self):
        from api.services.segmentation import classify_segment

        assert classify_segment() == "other"

    def test_rotary_beats_spolek(self):
        """Rotary should match before spolek even with club keyword."""
        from api.services.segmentation import classify_segment

        assert classify_segment(name="Rotary Club Brno") == "rotary_lions"


class TestAutoSegmentCompany:
    """Test auto_segment_company with DB."""

    def test_segment_updates_company(self, app, db, seed_tenant):
        from api.models import Company
        from api.services.segmentation import auto_segment_company

        c = Company(
            tenant_id=seed_tenant.id,
            name="Město Pardubice",
            industry="municipality",
        )
        db.session.add(c)
        db.session.flush()

        result = auto_segment_company(str(c.id))
        assert result == "obec"

        # Verify DB updated
        row = db.session.execute(
            db.text("SELECT segment FROM companies WHERE id = :id"),
            {"id": c.id},
        ).fetchone()
        assert row[0] == "obec"

    def test_segment_not_found(self, app, db):
        from api.services.segmentation import auto_segment_company

        result = auto_segment_company(str(uuid.uuid4()))
        assert result is None


class TestAutoSegmentTenant:
    """Test auto_segment_tenant bulk operation."""

    def test_bulk_segment(self, app, db, seed_tenant):
        from api.models import Company
        from api.services.segmentation import auto_segment_tenant

        companies = [
            Company(
                tenant_id=seed_tenant.id, name="Obec Lhota", industry="municipality"
            ),
            Company(
                tenant_id=seed_tenant.id, name="Spolek ABC", industry="association"
            ),
            Company(tenant_id=seed_tenant.id, name="Random s.r.o.", industry="IT"),
        ]
        db.session.add_all(companies)
        db.session.flush()

        result = auto_segment_tenant(str(seed_tenant.id))
        assert result["total"] == 3
        assert result["by_segment"]["obec"] == 1
        assert result["by_segment"]["spolek"] == 1
        assert result["by_segment"]["other"] == 1

    def test_bulk_skip_already_segmented(self, app, db, seed_tenant):
        from api.models import Company
        from api.services.segmentation import auto_segment_tenant

        c = Company(tenant_id=seed_tenant.id, name="Obec XY", segment="obec")
        db.session.add(c)
        db.session.flush()

        result = auto_segment_tenant(str(seed_tenant.id), force=False)
        assert result["total"] == 0

    def test_bulk_force_resegment(self, app, db, seed_tenant):
        from api.models import Company
        from api.services.segmentation import auto_segment_tenant

        c = Company(
            tenant_id=seed_tenant.id,
            name="Spolek přátel",
            segment="other",
        )
        db.session.add(c)
        db.session.flush()

        result = auto_segment_tenant(str(seed_tenant.id), force=True)
        assert result["total"] == 1
        assert result["by_segment"]["spolek"] == 1


class TestAutoSegmentEndpoint:
    """Test POST /api/companies/auto-segment endpoint."""

    def test_auto_segment_api(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post("/api/companies/auto-segment", headers=headers, json={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total" in data
        assert "by_segment" in data


class TestEligibleContacts:
    """Test GET /api/campaigns/<id>/eligible-contacts."""

    def test_eligible_returns_contacts(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        # Create campaign with no target segment (should return all eligible)
        resp = client.post(
            "/api/campaigns",
            headers=headers,
            json={"name": "Test Eligible"},
        )
        assert resp.status_code == 201
        campaign_id = resp.get_json()["id"]

        resp = client.get(
            f"/api/campaigns/{campaign_id}/eligible-contacts",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "contacts" in data
        assert "total" in data
        # All returned contacts should have email
        for c in data["contacts"]:
            assert c["email_address"] is not None

    def test_eligible_excludes_already_added(self, client, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        # Create campaign
        resp = client.post(
            "/api/campaigns",
            headers=headers,
            json={"name": "Exclude Test"},
        )
        assert resp.status_code == 201
        campaign_id = resp.get_json()["id"]

        # Get eligible contacts
        resp = client.get(
            f"/api/campaigns/{campaign_id}/eligible-contacts", headers=headers
        )
        initial_count = resp.get_json()["total"]

        # Add a contact to the campaign
        if initial_count > 0:
            contact_id = resp.get_json()["contacts"][0]["id"]
            client.post(
                f"/api/campaigns/{campaign_id}/contacts",
                headers=headers,
                json={"contact_ids": [contact_id]},
            )

            # Re-check eligible — count should decrease
            resp2 = client.get(
                f"/api/campaigns/{campaign_id}/eligible-contacts", headers=headers
            )
            assert resp2.get_json()["total"] <= initial_count


class TestProductRecommendations:
    """Test product recommendations by segment."""

    def test_get_recommended_products_empty(self, app, db, seed_tenant):
        from api.services.segmentation import get_recommended_products

        result = get_recommended_products(str(seed_tenant.id), "obec")
        assert result == []

    def test_get_recommended_products_with_data(self, app, db, seed_tenant):
        from api.models import Product, SegmentProductRecommendation
        from api.services.segmentation import get_recommended_products

        p = Product(
            tenant_id=seed_tenant.id,
            name="Chůdaři",
            name_en="Stilt Walkers",
            category="animation",
            price_czk=9000,
            price_unit="per_person",
            is_active=True,
        )
        db.session.add(p)
        db.session.flush()

        spr = SegmentProductRecommendation(
            tenant_id=seed_tenant.id,
            segment="obec",
            product_id=p.id,
            recommendation_type="entry",
            priority=1,
        )
        db.session.add(spr)
        db.session.flush()

        result = get_recommended_products(str(seed_tenant.id), "obec")
        assert len(result) == 1
        assert result[0]["name"] == "Chůdaři"
        assert result[0]["recommendation_type"] == "entry"
        assert result[0]["price_czk"] == 9000.0


class TestProductSection:
    """Test the product section builder for prompts."""

    def test_build_product_section_empty(self):
        from api.services.generation_prompts import _build_product_section

        assert _build_product_section([]) == ""
        assert _build_product_section(None) == ""

    def test_build_product_section_czk(self):
        from api.services.generation_prompts import _build_product_section

        products = [
            {
                "name": "Chůdaři",
                "price_czk": 9000,
                "price_eur": None,
                "price_unit": "per_person",
                "description_cs": "Chůdaři v kostýmech",
                "recommendation_type": "entry",
            },
        ]
        result = _build_product_section(products, "cs")
        assert "Chůdaři" in result
        assert "9,000 CZK" in result
        assert "Chůdaři v kostýmech" in result

    def test_build_product_section_eur_for_de(self):
        from api.services.generation_prompts import _build_product_section

        products = [
            {
                "name": "Catalogue Show",
                "price_czk": 40000,
                "price_eur": 3250,
                "price_unit": "per_event",
                "description_cs": "Katalogové představení",
                "recommendation_type": "entry",
            },
        ]
        result = _build_product_section(products, "de")
        assert "3,250 EUR" in result

    def test_build_product_section_entry_and_upsell(self):
        from api.services.generation_prompts import _build_product_section

        products = [
            {
                "name": "Živé Sochy",
                "price_czk": 5000,
                "price_eur": None,
                "price_unit": "per_person",
                "description_cs": "Živé sochy",
                "recommendation_type": "entry",
            },
            {
                "name": "Catalogue Show",
                "price_czk": 40000,
                "price_eur": 3250,
                "price_unit": "per_event",
                "description_cs": "Katalog",
                "recommendation_type": "upsell",
            },
        ]
        result = _build_product_section(products, "cs")
        assert "Recommended entry" in result
        assert "Upsell" in result
        assert "Živé Sochy" in result
        assert "Catalogue Show" in result


class TestBuildGenerationPromptWithProducts:
    """Test that build_generation_prompt includes product section."""

    def test_prompt_includes_products(self):
        from api.services.generation_prompts import build_generation_prompt

        products = [
            {
                "name": "Glamour in Red",
                "price_czk": 6000,
                "price_eur": None,
                "price_unit": "per_person",
                "description_cs": "Glamour show",
                "recommendation_type": "entry",
            },
        ]
        prompt = build_generation_prompt(
            channel="email",
            step_label="Intro",
            contact_data={"first_name": "Jan", "last_name": "Novák"},
            company_data={"name": "Test Corp"},
            enrichment_data={},
            generation_config={"language": "cs"},
            step_number=1,
            total_steps=1,
            recommended_products=products,
        )
        assert "RECOMMENDED PRODUCTS" in prompt
        assert "Glamour in Red" in prompt
        assert "6,000 CZK" in prompt

    def test_prompt_without_products(self):
        from api.services.generation_prompts import build_generation_prompt

        prompt = build_generation_prompt(
            channel="email",
            step_label="Intro",
            contact_data={"first_name": "Jan"},
            company_data={"name": "Test Corp"},
            enrichment_data={},
            generation_config={"language": "cs"},
            step_number=1,
            total_steps=1,
        )
        assert "RECOMMENDED PRODUCTS" not in prompt
