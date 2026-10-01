import { CheckCircle2, Loader2 } from "lucide-react";

interface Props {
  platform: "instagram" | "youtube" | "tiktok";
  active: boolean;       // in post.platforms
  published: boolean;    // successfully published
  publishId?: string;    // returned platform id (ig_media_id / yt_video_id / …)
  error?: string;
  canPublish: boolean;   // post status allows action
  busy: boolean;
  onPublish: () => void;
  onToggle: () => void;
}

const CFG = {
  instagram: {
    label:      "Instagram",
    activeBg:   "bg-pink-950/30 border-pink-800/50",
    dot:        "bg-pink-500",
    publishBtn: "bg-pink-700 hover:bg-pink-600",
    badgeCls:   "text-pink-300",
  },
  tiktok: {
    label:      "TikTok",
    activeBg:   "bg-slate-900/50 border-slate-700/50",
    dot:        "bg-slate-400",
    publishBtn: "bg-slate-600 hover:bg-slate-500",
    badgeCls:   "text-slate-300",
  },
  youtube: {
    label:      "YouTube",
    activeBg:   "bg-red-950/30 border-red-800/50",
    dot:        "bg-red-500",
    publishBtn: "bg-red-700 hover:bg-red-600",
    badgeCls:   "text-red-300",
  },
} as const;

export function PlatformPublishRow({
  platform, active, published, publishId, error, canPublish, busy, onPublish, onToggle,
}: Props) {
  const cfg = CFG[platform];

  return (
    <div className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border transition-colors ${
      active ? cfg.activeBg : "border-gray-800 bg-transparent"
    }`}>
      {/* Platform inclusion toggle dot */}
      <button
        onClick={canPublish ? onToggle : undefined}
        title={`${active ? "Remove" : "Include"} ${cfg.label}`}
        className={`w-2 h-2 rounded-full shrink-0 transition-opacity ${
          active ? cfg.dot : "bg-gray-700"
        } ${canPublish ? "cursor-pointer hover:opacity-70" : "cursor-default"}`}
      />

      {/* Platform name */}
      <span className={`flex-1 text-xs font-medium ${active ? "text-gray-200" : "text-gray-600"}`}>
        {cfg.label}
      </span>

      {/* Published badge — shows the returned platform id (flag) */}
      {published && (
        <span
          className="flex items-center gap-1 text-[11px] text-green-400 shrink-0 max-w-[130px] truncate"
          title={publishId ? `Published — ${publishId}` : "Published"}
        >
          <CheckCircle2 size={11} />
          {publishId ? `Done · ${publishId}` : "Done"}
        </span>
      )}

      {/* Error badge */}
      {!published && error && (
        <span className="text-[11px] text-orange-400 shrink-0 max-w-[90px] truncate" title={error}>
          ✗ Failed
        </span>
      )}

      {/* Publish button — stays clickable even after publishing (backend blocks
          the actual duplicate and just returns the existing id). */}
      {active && canPublish && (
        <button
          disabled={busy}
          onClick={onPublish}
          className={`shrink-0 flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-md text-white transition-colors disabled:opacity-40 ${cfg.publishBtn}`}
        >
          {busy ? <Loader2 size={10} className="animate-spin" /> : null}
          {published ? "Re-publish" : "Publish"}
        </button>
      )}
    </div>
  );
}
