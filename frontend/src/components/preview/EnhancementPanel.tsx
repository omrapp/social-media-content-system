import { Sparkles, Loader2 } from "lucide-react";
import type { UsePreview } from "@/hooks/usePreview";

type Props = Pick<UsePreview,
  "wmEnabled" | "setWmEnabled" | "wmPosition" | "setWmPosition" |
  "skipStabilize" | "toggleSkipStabilize" | "enhanceBusy" | "handleEnhance">;

export function EnhancementPanel({
  wmEnabled, setWmEnabled, wmPosition, setWmPosition,
  skipStabilize, toggleSkipStabilize, enhanceBusy, handleEnhance,
}: Props) {
  return (
    <div className="p-4 border-t border-gray-800 space-y-3">
      <label className="text-xs font-semibold uppercase tracking-widest text-gray-500 flex items-center gap-1.5">
        <Sparkles size={11} /> Enhancement
      </label>

      <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
        <input
          type="checkbox"
          checked={wmEnabled}
          onChange={(e) => setWmEnabled(e.target.checked)}
          className="accent-amber-500"
        />
        Remove watermarks
      </label>

      <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer" title="Disables vidstab stabilization for this video on next enhance run">
        <input
          type="checkbox"
          checked={skipStabilize}
          onChange={(e) => toggleSkipStabilize(e.target.checked)}
          className="accent-blue-500"
        />
        Skip stabilization
      </label>

      {wmEnabled && (
        <div className="flex gap-1 ml-5">
          {(["bottom", "top", "both"] as const).map((pos) => (
            <button
              key={pos}
              onClick={() => setWmPosition(pos)}
              className={`text-xs px-2.5 py-1 rounded border transition-colors capitalize ${
                wmPosition === pos
                  ? "border-amber-600 bg-amber-900/30 text-amber-300"
                  : "border-gray-700 text-gray-500 hover:border-gray-500"
              }`}
            >
              {pos}
            </button>
          ))}
        </div>
      )}

      {enhanceBusy && (
        <div className="h-1 rounded-full bg-gray-800 overflow-hidden">
          <div className="h-full w-3/4 rounded-full bg-amber-500 animate-pulse" />
        </div>
      )}

      <button
        disabled={enhanceBusy}
        onClick={handleEnhance}
        className="w-full flex items-center justify-center gap-2 py-1.5 text-xs rounded-lg bg-gray-800 hover:bg-gray-700 disabled:opacity-40"
      >
        {enhanceBusy
          ? <><Loader2 size={12} className="animate-spin" /> Processing…</>
          : <><Sparkles size={12} /> Apply enhancement</>
        }
      </button>
    </div>
  );
}
