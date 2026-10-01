-- Assets index (v1.10.0): one table for all 5 asset types (music/font/lut/
-- intro/outro), backed by a PUBLIC Supabase Storage bucket. DB row is source
-- of truth (public_url + storage_path); local disk stays the fast-serve
-- cache/fallback the FFmpeg pipeline reads directly (reconcile only ever
-- adds/updates/prunes rows here, never deletes local files).
--
-- Bucket is public-read BY DESIGN — these are non-sensitive branding/music/LUT
-- assets, not user data. No signed URLs needed.

create table if not exists assets (
  id text primary key,                     -- e.g. "music_<uuid>", "font_<uuid>" — mirrors music_fetcher's id convention
  type text not null check (type in ('music','font','lut','intro','outro')),
  name text not null,                       -- display name
  filename text not null,                   -- basename on disk / in bucket
  storage_path text,                        -- bucket-relative key, nullable until uploaded to Storage
  public_url text,                          -- stable public Storage URL, nullable until uploaded
  local_path text,                          -- relative-to-assets/ path, nullable if Storage-only
  size_bytes bigint,
  checksum text,                            -- content hash, dedupe (mirrors music_fetcher._group_by_hash)
  parent_asset_id text references assets(id) on delete set null,  -- trim/derived lineage
  meta jsonb not null default '{}'::jsonb,  -- duration/pillars/mood/favourite/usage_count/last_used_at (music);
                                             -- tags/pillars/intensity (lut); category (intro/outro); {} (font)
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_assets_type on assets(type);
create unique index if not exists idx_assets_storage_path on assets(storage_path) where storage_path is not null;
create index if not exists idx_assets_checksum on assets(checksum);
