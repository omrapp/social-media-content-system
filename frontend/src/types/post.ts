export interface Post {
  id: string;
  media_id: string;
  caption: string;
  status: string;
  scheduled_at: string;
  publish_after?: string;
  hashtags_en?: string[];
  hashtags_ar?: string[];
  approval_status?: ApprovalStatus;
  approved_at?: string;
  feedback?: string;
  edit_requests?: EditRequest[];
  platforms?: string[];
  ig_media_id?: string;
  yt_video_id?: string;
  yt_error?: string;
  tiktok_video_id?: string;
  tiktok_error?: string;
}

export type ApprovalStatus = "pending" | "approved" | "rejected" | "auto_approved";

export interface EditRequest {
  stage: "music_swap" | "color_grade" | "resize" | "caption_refine" | "reorder";
  params?: Record<string, unknown>;
  created_at?: string;
}
