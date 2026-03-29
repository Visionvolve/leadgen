-- Migration 056: Seed United Arts product catalog and segment-product recommendations
-- Uses the united-arts tenant. Run AFTER 055_product_catalog.sql.

-- Find the united-arts tenant ID dynamically
DO $$
DECLARE
    ua_tenant UUID;
    p_flying UUID;
    p_chudari UUID;
    p_hrajici UUID;
    p_sochy UUID;
    p_glamour UUID;
    p_catalogue UUID;
    p_custom UUID;
BEGIN
    SELECT id INTO ua_tenant FROM tenants WHERE slug = 'united-arts';
    IF ua_tenant IS NULL THEN
        RAISE NOTICE 'united-arts tenant not found, skipping seed';
        RETURN;
    END IF;

    -- Insert products (ON CONFLICT skip if already seeded)
    INSERT INTO products (id, tenant_id, name, name_en, category, performers_min, performers_max, duration_minutes, price_czk, price_eur, price_unit, tech_requirements, best_for, description, description_cs, is_active)
    VALUES
        (gen_random_uuid(), ua_tenant, 'Flying Welcome Drink', 'Flying Welcome Drink', 'animation', 2, 6, 90, 5000, NULL, 'per_person', '["anchor point 500kg", "4m height minimum"]', 'Corporate galas, premium events', 'Aerial bartending act with performers suspended from anchor points serving welcome drinks.', 'Letecký welcome drink — artisté zavěšení na úchytech servírují nápoje.', true),
        (gen_random_uuid(), ua_tenant, 'Chůdaři', 'Stilt Walkers', 'animation', 2, 8, 90, 9000, NULL, 'per_person', '["flat space", "3m height clearance"]', 'City days, festivals, outdoor celebrations', 'Stilt walkers in costume animating outdoor events and festivals.', 'Chůdaři v kostýmech animující venkovní akce a festivaly.', true),
        (gen_random_uuid(), ua_tenant, 'Hrající Chůdař', 'Playing Stilt Walker', 'animation', 1, 1, 90, 10000, NULL, 'per_person', '["flat space", "3m height clearance"]', 'Smaller events, city celebrations, fairs', 'Solo musical stilt walker performing at smaller events.', 'Hrající chůdař — sólový muzikální chůdař pro menší akce.', true),
        (gen_random_uuid(), ua_tenant, 'Živé Sochy', 'Living Statues', 'animation', 2, 4, 90, 5000, NULL, 'per_person', '["dressing room", "parking"]', 'Balls, galas, corporate receptions', 'Living statue performers creating elegant atmosphere at formal events.', 'Živé sochy — performeři vytvářející elegantní atmosféru.', true),
        (gen_random_uuid(), ua_tenant, 'Glamour in Red', 'Glamour in Red', 'animation', 2, 4, 90, 6000, NULL, 'per_person', '["dressing room", "parking"]', 'Balls, charity galas, fashion events', 'Glamorous performers in red creating a luxurious visual experience.', 'Glamour in Red — okázalí performeři v červeném pro luxusní zážitek.', true),
        (gen_random_uuid(), ua_tenant, 'Catalogue Show', 'Catalogue Show', 'catalogue_show', 4, 8, 30, 40000, 3250, 'per_event', '["stage 6x4m", "rigging points", "sound system"]', 'Gala evenings, corporate events, festival headliners', '30-minute block show from the Losers Cirque Company catalogue.', 'Katalogové představení — 30min blok z repertoáru Losers Cirque Company.', true),
        (gen_random_uuid(), ua_tenant, 'Custom Program', 'Custom Program', 'custom_program', 6, 20, 120, 175000, 13000, 'per_event', '["stage", "rigging", "sound", "lighting", "dressing rooms"]', 'Full evening entertainment, brand activations, signature events', 'Bespoke full-evening program designed for the client.', 'Custom program — večerní program na míru klientovi.', true)
    ON CONFLICT DO NOTHING;

    -- Get product IDs for segment mapping
    SELECT id INTO p_flying FROM products WHERE tenant_id = ua_tenant AND name = 'Flying Welcome Drink' LIMIT 1;
    SELECT id INTO p_chudari FROM products WHERE tenant_id = ua_tenant AND name = 'Chůdaři' LIMIT 1;
    SELECT id INTO p_hrajici FROM products WHERE tenant_id = ua_tenant AND name = 'Hrající Chůdař' LIMIT 1;
    SELECT id INTO p_sochy FROM products WHERE tenant_id = ua_tenant AND name = 'Živé Sochy' LIMIT 1;
    SELECT id INTO p_glamour FROM products WHERE tenant_id = ua_tenant AND name = 'Glamour in Red' LIMIT 1;
    SELECT id INTO p_catalogue FROM products WHERE tenant_id = ua_tenant AND name = 'Catalogue Show' LIMIT 1;
    SELECT id INTO p_custom FROM products WHERE tenant_id = ua_tenant AND name = 'Custom Program' LIMIT 1;

    -- Segment → Product Recommendations
    -- Obce (municipalities) — outdoor
    INSERT INTO segment_product_recommendations (tenant_id, segment, product_id, recommendation_type, priority) VALUES
        (ua_tenant, 'obec', p_chudari, 'entry', 1),
        (ua_tenant, 'obec', p_hrajici, 'entry', 2),
        (ua_tenant, 'obec', p_catalogue, 'upsell', 1)
    ON CONFLICT DO NOTHING;

    -- Spolky (clubs) — balls/galas
    INSERT INTO segment_product_recommendations (tenant_id, segment, product_id, recommendation_type, priority) VALUES
        (ua_tenant, 'spolek', p_sochy, 'entry', 1),
        (ua_tenant, 'spolek', p_glamour, 'entry', 2),
        (ua_tenant, 'spolek', p_catalogue, 'upsell', 1)
    ON CONFLICT DO NOTHING;

    -- Rotary/Lions — charity galas
    INSERT INTO segment_product_recommendations (tenant_id, segment, product_id, recommendation_type, priority) VALUES
        (ua_tenant, 'rotary_lions', p_glamour, 'entry', 1),
        (ua_tenant, 'rotary_lions', p_flying, 'entry', 2),
        (ua_tenant, 'rotary_lions', p_custom, 'upsell', 1)
    ON CONFLICT DO NOTHING;

    -- Školy (schools) — proms
    INSERT INTO segment_product_recommendations (tenant_id, segment, product_id, recommendation_type, priority) VALUES
        (ua_tenant, 'skola', p_sochy, 'entry', 1),
        (ua_tenant, 'skola', p_catalogue, 'upsell', 1)
    ON CONFLICT DO NOTHING;

    -- Agentury (agencies) — corporate
    INSERT INTO segment_product_recommendations (tenant_id, segment, product_id, recommendation_type, priority) VALUES
        (ua_tenant, 'agentura', p_catalogue, 'entry', 1),
        (ua_tenant, 'agentura', p_custom, 'entry', 2),
        (ua_tenant, 'agentura', p_flying, 'entry', 3)
    ON CONFLICT DO NOTHING;

    -- DACH agencies
    INSERT INTO segment_product_recommendations (tenant_id, segment, product_id, recommendation_type, priority) VALUES
        (ua_tenant, 'dach_agentura', p_catalogue, 'entry', 1),
        (ua_tenant, 'dach_agentura', p_custom, 'upsell', 1)
    ON CONFLICT DO NOTHING;

    RAISE NOTICE 'Seeded % products and segment recommendations for united-arts', 7;
END $$;
