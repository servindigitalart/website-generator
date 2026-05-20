-- Add r2_source_key to clinic_websites so PublishAgent can always
-- locate the Astro source archive for a site without guessing.
-- Key format: sources/{clinic_id}/{site_id}.zip

ALTER TABLE clinic_websites
    ADD COLUMN IF NOT EXISTS r2_source_key TEXT;

-- Add city column — needed by weekly_seo_runner for article localisation
ALTER TABLE clinic_websites
    ADD COLUMN IF NOT EXISTS city TEXT;

-- Postgres function for atomic article counter increment
-- Called by PublishAgent._increment_article_count() via supabase.rpc()
CREATE OR REPLACE FUNCTION increment_article_count(p_site_id UUID, p_amount INT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE clinic_websites
       SET total_articles_generated = COALESCE(total_articles_generated, 0) + p_amount
     WHERE id = p_site_id;
END;
$$;
