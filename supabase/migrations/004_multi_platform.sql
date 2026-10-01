-- Multi-platform publishing support
-- Adds YouTube Shorts + TikTok fields to posts table.

ALTER TABLE posts
  ADD COLUMN IF NOT EXISTS platforms        TEXT[]  DEFAULT '{instagram}',
  ADD COLUMN IF NOT EXISTS yt_video_id      TEXT,
  ADD COLUMN IF NOT EXISTS yt_error         TEXT,
  ADD COLUMN IF NOT EXISTS tiktok_video_id  TEXT,
  ADD COLUMN IF NOT EXISTS tiktok_error     TEXT;

-- Backfill: existing posts targeted Instagram only
UPDATE posts SET platforms = '{instagram}' WHERE platforms IS NULL;
