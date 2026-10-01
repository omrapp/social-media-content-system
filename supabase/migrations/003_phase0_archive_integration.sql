-- ============================================================
-- Travel Content System — Phase 0
-- Archive integration: extend media with original-content + approval columns,
-- add settings key/value store, broaden pillar to free-text taxonomy.
-- ============================================================

ALTER TABLE media
    ADD COLUMN IF NOT EXISTS original_caption  TEXT,
    ADD COLUMN IF NOT EXISTS original_hashtags JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS original_music    TEXT,
    ADD COLUMN IF NOT EXISTS music_source      TEXT DEFAULT 'unknown'
        CHECK (music_source IN ('original', 'licensed', 'none', 'unknown')),
    ADD COLUMN IF NOT EXISTS licensed_music    TEXT,
    ADD COLUMN IF NOT EXISTS approval_status   TEXT DEFAULT 'pending'
        CHECK (approval_status IN ('pending', 'approved', 'rejected', 'auto_approved')),
    ADD COLUMN IF NOT EXISTS feedback          TEXT,
    ADD COLUMN IF NOT EXISTS edit_requests     JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS media_preview_url TEXT,
    ADD COLUMN IF NOT EXISTS publish_after     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS approved_at       TIMESTAMPTZ;

-- Archive carries pillars beyond the original {hidden, budget, culture} taxonomy
-- (nature, food, beach, etc). Replace the strict check with a free-text column;
-- canonical taxonomy now lives in settings.
ALTER TABLE media DROP CONSTRAINT IF EXISTS media_pillar_check;

-- Stories source from the bulk archive.
ALTER TABLE media DROP CONSTRAINT IF EXISTS media_source_check;
ALTER TABLE media ADD CONSTRAINT media_source_check
    CHECK (source IN ('post', 'highlight', 'story'));

CREATE INDEX IF NOT EXISTS idx_media_approval ON media(approval_status);
CREATE INDEX IF NOT EXISTS idx_media_publish_after ON media(publish_after)
    WHERE publish_after IS NOT NULL;

-- ============================================================
-- settings — key/value JSON store (admin-tunable runtime config)
-- ============================================================
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER settings_updated_at
    BEFORE UPDATE ON settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Authenticated full access" ON settings
    FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY "Service role bypass" ON settings
    FOR ALL USING (auth.role() = 'service_role');
