// Assets admin page types (music/font/lut/intro/outro unified index, 1.10.0)
// Mirrors the `assets` Supabase table shape returned by /api/assets/all.

export type AssetType = "music" | "font" | "lut" | "intro" | "outro";

export interface AssetItem {
  id: string;
  type: AssetType;
  name: string;
  filename: string;
  local_path: string | null;
  url: string | null;
  local_exists: boolean;
  size_bytes: number | null;
  parent_asset_id: string | null;
  meta: Record<string, unknown>;
  created_at: string;
  favourite: boolean;
  usage_count: number;
  tags: string[];
  last_used_at: string | null;
  mood: string | null;
}

export interface AssetListResponse {
  assets: AssetItem[];
}

export interface AssetSyncPreview {
  added: unknown[];
  removed: unknown[];
  updated: unknown[];
  added_count: number;
  removed_count: number;
  updated_count: number;
}
