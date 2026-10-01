-- Phase 0: publish hardening
-- 1. Expand posts status constraint to allow 'cancelled'
--    (approve keeps status=preview; reject→cancelled; scheduler.cancel_post→cancelled)
-- 2. Add slot_at column for assigned daily publish slot

-- ── 1. Status constraint ──────────────────────────────────────────────────────
-- Drop + recreate because ALTER CONSTRAINT is not supported for CHECK constraints.
ALTER TABLE posts DROP CONSTRAINT IF EXISTS posts_status_check;
ALTER TABLE posts ADD CONSTRAINT posts_status_check
    CHECK (status IN ('draft', 'scheduled', 'preview', 'publishing', 'posted', 'error', 'cancelled'));

-- ── 2. slot_at column ─────────────────────────────────────────────────────────
ALTER TABLE posts ADD COLUMN IF NOT EXISTS slot_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_posts_slot_at ON posts(slot_at);
