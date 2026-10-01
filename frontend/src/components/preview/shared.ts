import type { Media } from "@/types/media";

// Quick-flag definitions — persisted as edit_requests JSONB.
// `actionable` flags map to pipeline stages and can trigger a video re-render;
// the rest are annotation-only tags for later manual editing.
export const FLAGS = [
  { key: "caption_too_long",  label: "Caption too long", actionable: false },
  { key: "wrong_music",       label: "Wrong music",      actionable: true  },
  { key: "wrong_category",    label: "Wrong category",   actionable: false },
  { key: "color_off",         label: "Color off",        actionable: true  },
  { key: "aspect_wrong",      label: "Aspect wrong",     actionable: true  },
  { key: "clip_order_wrong",  label: "Clip order wrong", actionable: true  },
] as const;

export type FlagKey = typeof FLAGS[number]["key"];

// Flags that trigger a pipeline re-render when applied.
export const ACTIONABLE_FLAGS = new Set<FlagKey>(
  FLAGS.filter((f) => f.actionable).map((f) => f.key),
);

// Explains why the auto-music stage did or didn't add a track.
export const MUSIC_SOURCE_WHY: Record<string, string> = {
  licensed: "music added (original was silent / noisy / talking)",
  original: "kept original audio (real music or ambient)",
  none: "no music (needed a track, none available)",
  unknown: "not analyzed yet",
};

export const PLATFORMS = ["instagram", "tiktok", "youtube"] as const;
export type Platform = typeof PLATFORMS[number];

// Backend serves files at <origin>/static/media/<rel>. That origin is the API base
// minus the trailing /api (dev: "" → Vite proxies /static to :8000).
export const MEDIA_BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/api\/?$/, "");

export function resolveUrl(media: Media): string {
  if (media.r2_url) return media.r2_url;
  if (media.media_preview_url) return media.media_preview_url;
  // local_path is stored relative to organized/ (e.g. "Greece/stories/1.jpg");
  // tolerate legacy absolute paths that still contain an organized/ segment.
  const path = (media as unknown as { local_path?: string }).local_path ?? "";
  if (path) {
    const rel = path.includes("organized/") ? path.split("organized/")[1] : path;
    if (rel) return `${MEDIA_BASE}/static/media/${rel}`;
  }
  return "";
}
