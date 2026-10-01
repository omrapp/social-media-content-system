// Audio Management page (Track shape per backend contract, 1.9.0)

export interface Track {
  id: string;
  filename: string;
  title: string;
  source: string;
  duration: number;
  popularity: number;
  license: string;
  mood: string;
  categories: string[];
  favourite: boolean;
  usage_count: number;
  last_used_at: string | null;
  url: string | null;
}

export interface AudioListResponse {
  tracks: Track[];
}

export interface DupGroup {
  keep: string;
  delete: string[];
  categories_merged: string[];
}

export interface Orphan {
  id: string;
  filename: string;
  title: string;
}

export interface RefreshPreview {
  new_files: string[];
  dup_groups: DupGroup[];
  would_delete_count: number;
  orphaned: Orphan[];
  orphaned_count: number;
}

export type SortKey = "title" | "favourite" | "usage_count" | "last_used_at";
