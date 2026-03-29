-- Migration 055: Product Catalog and Segment-Product Recommendations
-- Supports segment-based campaign assignment and product-aware message generation.

CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name VARCHAR(200) NOT NULL,
    name_en VARCHAR(200),
    category VARCHAR(50), -- animation, catalogue_show, custom_program
    performers_min SMALLINT,
    performers_max SMALLINT,
    duration_minutes SMALLINT,
    price_czk NUMERIC(10,2),
    price_eur NUMERIC(10,2),
    price_unit VARCHAR(20) DEFAULT 'per_person', -- per_person, flat, per_event
    tech_requirements JSONB DEFAULT '[]',
    best_for TEXT,
    description TEXT,
    description_cs TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS segment_product_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    segment VARCHAR(50) NOT NULL,
    product_id UUID NOT NULL REFERENCES products(id),
    recommendation_type VARCHAR(20) DEFAULT 'entry', -- entry, upsell
    priority SMALLINT DEFAULT 1,
    UNIQUE(tenant_id, segment, product_id)
);

CREATE INDEX IF NOT EXISTS idx_products_tenant ON products(tenant_id);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_spr_segment ON segment_product_recommendations(segment);
CREATE INDEX IF NOT EXISTS idx_spr_tenant ON segment_product_recommendations(tenant_id);
