-- Zernio publishing IDs for Instagram and TikTok
ALTER TABLE posts
  ADD COLUMN IF NOT EXISTS zernio_ig_id    TEXT,
  ADD COLUMN IF NOT EXISTS zernio_ig_error TEXT,
  ADD COLUMN IF NOT EXISTS zernio_tt_id    TEXT,
  ADD COLUMN IF NOT EXISTS zernio_tt_error TEXT;
