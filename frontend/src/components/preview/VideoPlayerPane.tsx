import { ArrowLeft, ChevronLeft, ChevronRight } from "lucide-react";
import { FLAGS, type FlagKey } from "./shared";
import type { UsePreview } from "@/hooks/usePreview";

type Props = Pick<UsePreview,
  "navigate" | "prevId" | "nextId" | "navIdx" | "orderedIds" |
  "videoUrl" | "videoKey" | "videoRef"> & {
  selectedFlags: Set<FlagKey>;
};

export function VideoPlayerPane({
  navigate, prevId, nextId, navIdx, orderedIds,
  videoUrl, videoKey, videoRef, selectedFlags,
}: Props) {
  // Append the videoKey as a cache-buster so a re-rendered file at the same URL
  // (r2_url / static path) actually reloads instead of serving the stale copy.
  const src = videoUrl
    ? `${videoUrl}${videoUrl.includes("?") ? "&" : "?"}v=${videoKey}`
    : "";
  return (
    <div className="flex-1 bg-black flex items-center justify-center relative min-h-0">
      <button
        onClick={() => navigate(-1)}
        className="absolute top-4 left-4 flex items-center gap-2 text-gray-400 hover:text-white text-sm bg-black/50 rounded-lg px-3 py-1.5 z-10"
      >
        <ArrowLeft size={14} /> Back
      </button>

      {/* Prev / next through Queue order */}
      <div className="absolute top-4 right-4 flex items-center gap-1.5 z-10">
        <button
          onClick={() => prevId && navigate(`/preview/${prevId}`)}
          disabled={!prevId}
          title="Previous in queue"
          className="flex items-center gap-1 text-gray-400 hover:text-white text-sm bg-black/50 rounded-lg px-2.5 py-1.5 disabled:opacity-30 disabled:hover:text-gray-400"
        >
          <ChevronLeft size={14} /> Prev
        </button>
        {navIdx >= 0 && orderedIds.length > 0 && (
          <span className="text-xs text-gray-500 bg-black/50 rounded-lg px-2 py-1.5 tabular-nums">
            {navIdx + 1}/{orderedIds.length}
          </span>
        )}
        <button
          onClick={() => nextId && navigate(`/preview/${nextId}`)}
          disabled={!nextId}
          title="Next in queue"
          className="flex items-center gap-1 text-gray-400 hover:text-white text-sm bg-black/50 rounded-lg px-2.5 py-1.5 disabled:opacity-30 disabled:hover:text-gray-400"
        >
          Next <ChevronRight size={14} />
        </button>
      </div>

      {videoUrl ? (
        <div className="relative max-h-full" style={{ aspectRatio: "9/16" }}>
          <video
            key={videoKey}
            ref={videoRef}
            src={src}
            controls
            loop
            className="w-full h-full object-contain"
          />
          {selectedFlags.size > 0 && (
            <div className="absolute bottom-14 left-0 right-0 flex flex-wrap gap-1.5 px-3 pointer-events-none">
              {Array.from(selectedFlags).map((key) => {
                const label = FLAGS.find((f) => f.key === key)?.label ?? key;
                return (
                  <span key={key} className="text-xs bg-amber-900/85 border border-amber-600/70 text-amber-300 px-2 py-0.5 rounded backdrop-blur-sm">
                    ⚑ {label}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        <div className="text-gray-600 text-sm">No preview URL available</div>
      )}
    </div>
  );
}
