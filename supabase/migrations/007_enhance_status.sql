-- Add 'enhanced' to media.status CHECK constraint
-- New pipeline flow: raw → resized → enhanced → edited → uploaded → ...

ALTER TABLE media DROP CONSTRAINT IF EXISTS media_status_check;

ALTER TABLE media
    ADD CONSTRAINT media_status_check
    CHECK (status IN (
        'raw', 'resized', 'enhanced', 'edited',
        'uploaded', 'scheduled', 'preview', 'posted', 'error'
    ));
