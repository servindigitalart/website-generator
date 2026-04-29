-- Clinic websites table
CREATE TABLE clinic_websites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    clinic_name TEXT,
    specialty TEXT DEFAULT 'general',
    template_used TEXT,

    -- URLs
    subdomain TEXT UNIQUE,
    site_url TEXT,
    custom_domain TEXT,
    preview_url TEXT,

    -- Vercel
    vercel_project_id TEXT,
    vercel_deployment_id TEXT,

    -- GSC + IndexNow
    gsc_property_url TEXT,
    gsc_verified BOOLEAN DEFAULT false,
    gsc_sitemap_submitted BOOLEAN DEFAULT false,
    indexnow_key TEXT,

    -- Status
    status TEXT DEFAULT 'pending'
        CHECK (status IN (
            'pending','generating','building',
            'deploying','live','error','paused'
        )),
    error_message TEXT,

    -- SEO tracking
    last_seo_run TIMESTAMPTZ,
    total_articles_generated INTEGER DEFAULT 0,
    last_ranking_check TIMESTAMPTZ,
    avg_position DECIMAL(6,2),
    total_clicks_30d INTEGER DEFAULT 0,
    total_impressions_30d INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    live_at TIMESTAMPTZ
);

-- SEO articles generated per site
CREATE TABLE clinic_seo_articles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    site_id UUID REFERENCES clinic_websites(id) ON DELETE CASCADE,

    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    keyword_target TEXT NOT NULL,
    keyword_position_before DECIMAL(6,2),
    keyword_position_after DECIMAL(6,2),

    content_mdx TEXT,
    meta_description TEXT,
    hero_image_url TEXT,

    -- Publishing
    published_at TIMESTAMPTZ,
    indexed_at TIMESTAMPTZ,
    indexnow_sent BOOLEAN DEFAULT false,
    gsc_sitemap_updated BOOLEAN DEFAULT false,

    -- Performance (updated weekly)
    clicks_7d INTEGER DEFAULT 0,
    impressions_7d INTEGER DEFAULT 0,
    avg_position_7d DECIMAL(6,2),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(site_id, slug)
);

-- Generated images per site
CREATE TABLE clinic_site_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    site_id UUID REFERENCES clinic_websites(id) ON DELETE CASCADE,

    section TEXT NOT NULL,
        -- hero|services|team|about|testimonials|blog_hero|etc
    page TEXT NOT NULL,
    prompt_used TEXT,
    r2_key TEXT,
    public_url TEXT,
    width INTEGER,
    height INTEGER,
    alt_text TEXT,
    approved BOOLEAN DEFAULT false,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- GSC keyword snapshots (weekly)
CREATE TABLE gsc_keyword_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID REFERENCES clinic_websites(id) ON DELETE CASCADE,
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,

    keyword TEXT NOT NULL,
    clicks INTEGER DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    ctr DECIMAL(6,4),
    position DECIMAL(6,2),
    snapshot_date DATE NOT NULL,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(site_id, keyword, snapshot_date)
);

-- Indexes
CREATE INDEX idx_clinic_websites_clinic
    ON clinic_websites(clinic_id, status);
CREATE INDEX idx_seo_articles_site
    ON clinic_seo_articles(site_id, published_at DESC);
CREATE INDEX idx_gsc_snapshots_site
    ON gsc_keyword_snapshots(site_id, snapshot_date DESC);
CREATE INDEX idx_site_images_site
    ON clinic_site_images(site_id, section);
