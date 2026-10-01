-- Migration 010: Hashtag A/B testing (Enhancement D)
-- caption_gen now emits a second hashtag set (hashtags_en_b) alongside the
-- primary hashtags_en. enqueue_post randomly assigns A or B to each post and
-- records the choice in posts.hashtag_variant so feedback_aggregator can
-- correlate the variant back to reach/engagement.
ALTER TABLE media ADD COLUMN IF NOT EXISTS hashtags_en_b TEXT[] DEFAULT '{}';
ALTER TABLE posts ADD COLUMN IF NOT EXISTS hashtag_variant TEXT;
CREATE INDEX IF NOT EXISTS idx_posts_hashtag_variant ON posts(hashtag_variant);
