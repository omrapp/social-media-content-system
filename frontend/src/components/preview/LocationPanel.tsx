import { Tag, Music, Edit2, Play, Square } from "lucide-react";
import { MUSIC_SOURCE_WHY } from "./shared";
import { AssetResolvedChip } from "./AssetResolvedChip";
import { CategoryBadge } from "@/components/ui/CategoryBadge";
import type { UsePreview } from "@/hooks/usePreview";
import type { Media } from "@/types/media";

type Props = Pick<UsePreview,
  "locEdit" | "setLocEdit" | "locCategory" | "setLocCategory" | "locTags" |
  "setLocTags" | "saveLocation" | "locPending" |
  "currentTrackUrl" | "trackPlaying" | "toggleTrack"> & {
  media: Media;
};

export function LocationPanel({
  media, locEdit, setLocEdit, locCategory, setLocCategory, locTags, setLocTags,
  saveLocation, locPending,
  currentTrackUrl, trackPlaying, toggleTrack,
}: Props) {
  const displayCategory = locCategory || media.category;
  const displayTags = locTags.length ? locTags : (media.tags ?? []);

  return (
    <div className="p-4 border-b border-gray-800 space-y-2 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-widest text-gray-500">Category</span>
        <button
          onClick={() => setLocEdit(!locEdit)}
          className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1"
        >
          <Edit2 size={11} /> {locEdit ? "Done" : "Edit"}
        </button>
      </div>

      {locEdit ? (
        <div className="space-y-2">
          <div className="space-y-1">
            <label className="text-xs text-gray-500">Category</label>
            <input
              value={locCategory}
              onChange={(e) => setLocCategory(e.target.value)}
              placeholder="e.g. nature, food, culture…"
              className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-gray-500">Tags (comma-separated)</label>
            <input
              value={locTags.join(", ")}
              onChange={(e) => setLocTags(e.target.value.split(",").map((t) => t.trim()).filter(Boolean))}
              placeholder="e.g. Japan, Kyoto"
              className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200"
            />
          </div>
          <button
            disabled={locPending}
            onClick={saveLocation}
            className="w-full py-1.5 text-xs rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40"
          >
            {locPending ? "Saving…" : "Save category"}
          </button>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2 text-gray-400">
            <Tag size={13} />
            {displayCategory ? <CategoryBadge category={displayCategory} /> : <span>—</span>}
          </div>
          <div className="flex items-center gap-2 text-gray-400">
            <Tag size={13} />
            <span>{displayTags.length ? displayTags.join(", ") : "—"}</span>
          </div>
        </>
      )}

      {/* Music source (read-only) */}
      <div className="flex items-center gap-2 text-gray-400" title={MUSIC_SOURCE_WHY[media.music_source ?? "unknown"]}>
        <Music size={13} className="shrink-0" />
        <span className="capitalize shrink-0">{media.music_source ?? "unknown"}</span>
        {media.licensed_music && <span className="text-xs text-gray-600 truncate">· {media.licensed_music}</span>}
        {currentTrackUrl && (
          <button
            onClick={toggleTrack}
            title={trackPlaying ? "Stop track" : "Play track"}
            className="ml-auto shrink-0 text-gray-400 hover:text-white"
          >
            {trackPlaying ? <Square size={13} /> : <Play size={13} />}
          </button>
        )}
      </div>

      {/* Resolved asset-library entry for the reel's licensed track — name +
          link to the Assets page + favourite/usage quick-actions (1.11.0).
          Renders nothing when there's no match. There's no equivalent stored
          LUT filename on the media row yet (color grade isn't persisted per
          post today), so only music resolves here for now. */}
      <div className="flex items-center gap-2 text-xs text-gray-400">
        <AssetResolvedChip filename={media.licensed_music} type="music" icon="🎵" showActions />
      </div>
    </div>
  );
}
