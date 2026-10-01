-- Migration 009: Add do_not_use flag to media table
-- Used by the Cancel action on the Preview page to permanently shelve a media
-- clip from the create queue without deleting the DB row.
ALTER TABLE media ADD COLUMN IF NOT EXISTS do_not_use BOOLEAN NOT NULL DEFAULT false;
