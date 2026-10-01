export interface FileStats {
  video: number;
  image: number;
  other: number;
  total_size_mb: number;
}

export interface HighlightBreakdown {
  name: string;
  count: number;
  last_downloaded: string | null;
}

export interface OrganizedCategory {
  category: string;
  video: number;
  image: number;
  total_size_mb: number;
}

export interface CategoryFunnel {
  category: string;
  raw: number;
  resized: number;
  edited: number;
  uploaded: number;
  posted: number;
  error: number;
  total: number;
}

export interface DownloadStatus {
  posts: { downloaded: number; files: FileStats };
  highlights: { downloaded: number; files: FileStats; breakdown: HighlightBreakdown[] };
  organized: OrganizedCategory[];
  uploads?: { video: number; image: number; total_size_mb: number };
}

export interface UploadResult {
  filename: string;
  ok: boolean;
  id?: string;
  local_path?: string;
  error?: string;
}

export interface NewCheck {
  new_posts: number;
  total_on_ig?: number;
  error?: string;
}

// ── Google Drive + Photos import (Phase 2) ──
export interface GoogleStatus {
  configured: boolean;
}

export interface DriveFile {
  id: string;
  name: string;
  size: number | null;
  mimeType: string;
  thumbnailLink?: string | null;
  duration_ms?: number | null;
}

export interface DriveList {
  files: DriveFile[];
  next_page_token: string;
}

export interface PhotosSession {
  id: string;
  picker_uri: string;
  poll_interval_ms: number;
}

export interface PhotosPoll {
  id: string;
  media_items_set: boolean;
}

export interface ImportResponse {
  results: (UploadResult & { duplicate?: boolean })[];
  saved: number;
  error?: string;
  duplicate?: boolean;
}

// ── Stock B-roll sourcing (Phase A, 1.8.0) ──
export interface StockStatus {
  configured: boolean;
}

export interface StockCandidate {
  id: string;
  provider: "pexels" | "pixabay";
  thumbnail_url: string;
  preview_url: string;
  duration_s: number;
  width: number;
  height: number;
}

export interface StockSearchResponse {
  results: StockCandidate[];
}

export interface StockClip {
  id: string;
  provider: string;
  provider_id: string;
  category: string;
  tags: string[];
  status: string;
  width: number | null;
  height: number | null;
  duration_s: number | null;
  size_mb: number;
  created_at: string | null;
}

export interface StockCategoryGroup {
  category: string;
  count: number;
  total_size_mb: number;
  clips: StockClip[];
}

export interface StockLibrary {
  categories: StockCategoryGroup[];
  total_clips: number;
  total_size_mb: number;
  imported_keys: string[];
}
