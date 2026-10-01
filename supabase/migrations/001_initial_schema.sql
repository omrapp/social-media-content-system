-- ============================================================
-- Travel Content System — Initial Schema
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pg_cron" WITH SCHEMA "extensions";
CREATE EXTENSION IF NOT EXISTS "pg_net" WITH SCHEMA "extensions";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- 1. media — Source content from Instagram
-- ============================================================
CREATE TABLE media (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('post', 'highlight')),
    highlight_name TEXT,
    media_type TEXT NOT NULL CHECK (media_type IN ('VIDEO', 'IMAGE', 'CAROUSEL_ALBUM')),
    local_path TEXT,
    caption TEXT,
    taken_at TIMESTAMPTZ,
    duration_s REAL,
    width INT,
    height INT,
    hook_score REAL,
    status TEXT NOT NULL DEFAULT 'raw'
        CHECK (status IN ('raw', 'resized', 'edited', 'uploaded', 'scheduled', 'preview', 'posted', 'error')),
    reel_ready_path TEXT,
    r2_url TEXT,
    r2_key TEXT,
    thumbnail_url TEXT,
    country TEXT,
    city TEXT,
    pillar TEXT CHECK (pillar IN ('hidden', 'budget', 'culture')),
    tags TEXT[],
    metadata JSONB DEFAULT '{}',
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_media_status ON media(status);
CREATE INDEX idx_media_source ON media(source);
CREATE INDEX idx_media_pillar ON media(pillar);
CREATE INDEX idx_media_highlight ON media(highlight_name);

-- ============================================================
-- 2. posts — Publishing queue (replaces queue.json)
-- ============================================================
CREATE TABLE posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'scheduled', 'preview', 'publishing', 'posted', 'error')),
    scheduled_at TIMESTAMPTZ,
    publish_after TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    caption TEXT,
    hashtags_en TEXT[] DEFAULT '{}',
    hashtags_ar TEXT[] DEFAULT '{}',
    alt_text TEXT,
    surface TEXT NOT NULL DEFAULT 'REELS'
        CHECK (surface IN ('REELS', 'FEED', 'STORY', 'CAROUSEL')),
    ig_media_id TEXT,
    ig_container_id TEXT,
    error_message TEXT,
    retry_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_posts_status ON posts(status);
CREATE INDEX idx_posts_scheduled ON posts(scheduled_at);
CREATE INDEX idx_posts_media ON posts(media_id);
CREATE UNIQUE INDEX idx_posts_ig_media ON posts(ig_media_id) WHERE ig_media_id IS NOT NULL;

-- ============================================================
-- 3. captions — Generation history
-- ============================================================
CREATE TABLE captions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    caption TEXT NOT NULL,
    hashtags_en TEXT[] DEFAULT '{}',
    hashtags_ar TEXT[] DEFAULT '{}',
    alt_text TEXT,
    pillar TEXT,
    country TEXT,
    city TEXT,
    context TEXT,
    model TEXT DEFAULT 'claude-haiku-4-5-20251001',
    is_selected BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_captions_media ON captions(media_id);

-- ============================================================
-- 4. analytics — Engagement metrics
-- ============================================================
CREATE TABLE analytics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    ig_media_id TEXT,
    impressions INT DEFAULT 0,
    reach INT DEFAULT 0,
    likes INT DEFAULT 0,
    comments INT DEFAULT 0,
    shares INT DEFAULT 0,
    saves INT DEFAULT 0,
    plays INT DEFAULT 0,
    engagement_rate REAL DEFAULT 0,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_analytics_post ON analytics(post_id);
CREATE INDEX idx_analytics_fetched ON analytics(fetched_at);

-- ============================================================
-- 5. pipeline_runs — Execution logs
-- ============================================================
CREATE TABLE pipeline_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed')),
    items_processed INT DEFAULT 0,
    items_failed INT DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_log TEXT,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_pipeline_runs_stage ON pipeline_runs(stage);
CREATE INDEX idx_pipeline_runs_status ON pipeline_runs(status);

-- ============================================================
-- 6. notifications — In-app alerts
-- ============================================================
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL CHECK (type IN ('error', 'success', 'warning', 'info')),
    title TEXT NOT NULL,
    message TEXT,
    read BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notifications_read ON notifications(read);

-- ============================================================
-- Triggers: auto-update updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER media_updated_at
    BEFORE UPDATE ON media
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER posts_updated_at
    BEFORE UPDATE ON posts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- RLS — Single admin user, full access when authenticated
-- ============================================================
ALTER TABLE media ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE captions ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated full access" ON media
    FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY "Authenticated full access" ON posts
    FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY "Authenticated full access" ON captions
    FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY "Authenticated full access" ON analytics
    FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY "Authenticated full access" ON pipeline_runs
    FOR ALL USING (auth.uid() IS NOT NULL);
CREATE POLICY "Authenticated full access" ON notifications
    FOR ALL USING (auth.uid() IS NOT NULL);

-- Service role bypass for Edge Functions
CREATE POLICY "Service role bypass" ON media
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role bypass" ON posts
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role bypass" ON captions
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role bypass" ON analytics
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role bypass" ON pipeline_runs
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role bypass" ON notifications
    FOR ALL USING (auth.role() = 'service_role');
