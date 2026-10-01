-- Generic taxonomy cutover: collapse the travel-specific pillar/country/city
-- fields into a single `category` (free text) + the existing `tags` array,
-- so the pipeline works for any short-form content, not just travel reels.
-- Also drops the series/story-arc feature (100% country-keyed, no generic
-- equivalent).

-- ============================================================
-- media
-- ============================================================
ALTER TABLE media ADD COLUMN IF NOT EXISTS category TEXT;
UPDATE media SET category = pillar WHERE pillar IS NOT NULL;
UPDATE media SET tags = array_remove(ARRAY[country, city], NULL)
    WHERE tags IS NULL OR array_length(tags, 1) IS NULL;
ALTER TABLE media DROP COLUMN IF EXISTS pillar;
ALTER TABLE media DROP COLUMN IF EXISTS country;
ALTER TABLE media DROP COLUMN IF EXISTS city;

DROP INDEX IF EXISTS idx_media_pillar;
CREATE INDEX IF NOT EXISTS idx_media_category ON media(category);

-- ============================================================
-- captions
-- ============================================================
ALTER TABLE captions ADD COLUMN IF NOT EXISTS category TEXT;
UPDATE captions SET category = pillar WHERE pillar IS NOT NULL;
ALTER TABLE captions DROP COLUMN IF EXISTS pillar;
ALTER TABLE captions DROP COLUMN IF EXISTS country;
ALTER TABLE captions DROP COLUMN IF EXISTS city;

-- ============================================================
-- assets — pillars[] merges into the existing tags[] column
-- ============================================================
UPDATE assets SET tags = array_cat(COALESCE(tags, '{}'), COALESCE(pillars, '{}'));
DROP INDEX IF EXISTS idx_assets_pillars;
ALTER TABLE assets DROP COLUMN IF EXISTS pillars;

-- ============================================================
-- series — 100% country-keyed, no generic equivalent; dropped entirely
-- ============================================================
DROP TABLE IF EXISTS series;
