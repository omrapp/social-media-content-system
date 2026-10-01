export interface Media {
  id: string;
  source: string;
  media_type: string;
  caption: string;
  status: string;
  category: string;
  tags?: string[];
  thumbnail_url: string;
  r2_url: string;
  hook_score: number;
  taken_at?: string;
  series_id?: string;
  episode_number?: number;
  episode_total?: number;
  series_arc_position?: string;
  original_caption?: string;
  original_hashtags?: string[];
  original_music?: string;
  music_source?: MusicSource;
  licensed_music?: string;
  media_preview_url?: string;
}

export type MediaStatus =
  | "raw"
  | "resized"
  | "edited"
  | "uploaded"
  | "scheduled"
  | "preview"
  | "posted"
  | "error"
  | "deleted";

export type Category = string;

export type MusicSource = "original" | "licensed" | "none" | "unknown";
