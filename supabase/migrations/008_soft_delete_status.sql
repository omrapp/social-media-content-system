-- Add 'deleted' to media.status CHECK constraint.
-- DELETE /api/media soft-deletes by setting status='deleted'; every read path
-- already filters `status != 'deleted'`, but the constraint (migration 007)
-- never allowed the value — so the soft-delete write failed with a check
-- violation → 500 on delete. Allow it here.

ALTER TABLE media DROP CONSTRAINT IF EXISTS media_status_check;

ALTER TABLE media
    ADD CONSTRAINT media_status_check
    CHECK (status IN (
        'raw', 'resized', 'enhanced', 'edited',
        'uploaded', 'scheduled', 'preview', 'posted', 'error', 'deleted'
    ));
