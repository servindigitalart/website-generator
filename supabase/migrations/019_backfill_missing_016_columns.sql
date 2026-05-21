-- Backfill missing columns from migration 016.
--
-- The clinic_websites table was created before 016 was applied, so it has
-- only a subset of the originally designed schema. Migration 018 (durability
-- layer) was applied on top of that partial schema using IF NOT EXISTS, so
-- those columns are present. This migration adds everything 016 specified
-- that is still missing.
--
-- All additions use IF NOT EXISTS so this is fully idempotent.

ALTER TABLE clinic_websites
    ADD COLUMN IF NOT EXISTS clinic_name          TEXT,
    ADD COLUMN IF NOT EXISTS template_used        TEXT,
    ADD COLUMN IF NOT EXISTS custom_domain        TEXT,
    ADD COLUMN IF NOT EXISTS preview_url          TEXT,
    ADD COLUMN IF NOT EXISTS gsc_property_url     TEXT,
    ADD COLUMN IF NOT EXISTS gsc_verified         BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS gsc_sitemap_submitted BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS indexnow_key         TEXT,
    ADD COLUMN IF NOT EXISTS error_message        TEXT,
    ADD COLUMN IF NOT EXISTS last_seo_run         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS total_articles_generated INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_ranking_check   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS avg_position         DECIMAL(6,2),
    ADD COLUMN IF NOT EXISTS total_clicks_30d     INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_impressions_30d INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS live_at              TIMESTAMPTZ;
