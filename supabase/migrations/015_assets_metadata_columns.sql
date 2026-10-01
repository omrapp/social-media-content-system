-- Assets metadata cutover (v1.11.0): promote favourite/usage_count/tags/
-- pillars/mood from music-only meta JSONB to first-class columns on every
-- asset type (music/font/lut/intro/outro). Applied manually, same as 014.

alter table assets
  add column if not exists favourite boolean not null default false,
  add column if not exists usage_count integer not null default 0,
  add column if not exists last_used_at timestamptz,
  add column if not exists tags text[] not null default '{}',
  add column if not exists pillars text[] not null default '{}',
  add column if not exists mood text;

create index if not exists idx_assets_favourite on assets(favourite) where favourite;
create index if not exists idx_assets_pillars on assets using gin(pillars);
create index if not exists idx_assets_tags on assets using gin(tags);

-- One-time backfill: promote existing music meta.* into the new columns.
update assets set
  favourite    = coalesce((meta->>'favourite')::boolean, false),
  usage_count  = coalesce((meta->>'usage_count')::int, 0),
  last_used_at = nullif(meta->>'last_used_at','')::timestamptz,
  pillars      = coalesce((select array_agg(x) from jsonb_array_elements_text(meta->'pillars') x), '{}'),
  mood         = meta->>'mood'
where type = 'music';

-- LUT tags/pillars backfill from catalog.json is NOT done here (catalog.json
-- stays the curated-set source; reconcile's next run leaves lut rows' tags
-- empty until an admin tags them via the Assets page, or a follow-up backfill
-- script reads catalog.json — flagged as manual, not part of this migration).
