-- Reel Editor EDL versions (v2.0.0): one row per saved edit document. The
-- editor is non-destructive — the EDL describes cuts/layers/grade over the
-- ORIGINAL source clips, and export always renders a NEW media row, so this
-- table is the only place a user's edit survives. Versioned (append-only,
-- pruned to editor.keep_versions) so a reel can be reopened or reverted.
-- Applied manually, same as 014/015.
--
-- doc is the EDL v1 JSON (backend/pipeline/editor_edl.py). approx=true marks a
-- doc hydrated lossily from a legacy metadata.merge that predates the persisted
-- plan — the UI shows an "approximate" banner for those.

create table if not exists edit_projects (
  id uuid primary key default gen_random_uuid(),
  media_id text references media(id) on delete cascade,  -- the reel being edited
  post_id uuid,                                          -- post the reel is queued under, nullable
  version integer not null,                              -- monotonic per media_id, 1-based
  doc jsonb not null,                                    -- EDL v1 document
  label text,                                            -- optional user-facing version name
  approx boolean not null default false,                 -- doc hydrated lossily from a legacy reel
  created_at timestamptz not null default now()
);

create index if not exists idx_edit_projects_media on edit_projects(media_id, version desc);

-- RLS mirror of the 001:180-205 / 005:30-35 dual-policy pattern. Backend writes
-- go through SUPABASE_SERVICE_KEY (bypass); the frontend reads with an
-- authenticated JWT. drop-then-create keeps the file re-runnable (postgres has
-- no `create policy if not exists`).
alter table edit_projects enable row level security;

drop policy if exists "Authenticated full access" on edit_projects;
create policy "Authenticated full access" on edit_projects
  for all using (auth.uid() is not null);

drop policy if exists "Service role bypass" on edit_projects;
create policy "Service role bypass" on edit_projects
  for all using (auth.role() = 'service_role');
