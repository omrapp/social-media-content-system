-- Allow merged reels as a media source (merge_clips.py emits source='merge').
-- Includes 'upload' so the live schema (which already permits uploads) is preserved.
ALTER TABLE media DROP CONSTRAINT IF EXISTS media_source_check;
ALTER TABLE media ADD CONSTRAINT media_source_check
    CHECK (source IN ('post', 'highlight', 'story', 'upload', 'merge'));
