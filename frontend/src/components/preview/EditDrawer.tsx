import { Wand2, Loader2 } from "lucide-react";
import { MusicPicker } from "@/components/MusicPicker";
import { LutPicker } from "@/components/LutPicker";
import type { UsePreview } from "@/hooks/usePreview";
import type { Media } from "@/types/media";

type Props = Pick<UsePreview,
  "editMusic" | "setEditMusic" | "editLut" | "setEditLut" | "editFeedback" |
  "setEditFeedback" | "editBusy" | "applyMusic" | "applyLut" | "handleDispatchEdit" |
  "locCategory" | "locTags"> & {
  media: Media;
};

export function EditDrawer({
  media, editMusic, setEditMusic, editLut, setEditLut, editFeedback,
  setEditFeedback, editBusy, applyMusic, applyLut, handleDispatchEdit,
  locCategory, locTags,
}: Props) {
  return (
    <div className="p-4 border-t border-gray-800 space-y-4 bg-gray-950">
      {/* Quick apply: Music */}
      <div className="space-y-1.5">
        <label className="text-xs font-semibold uppercase tracking-widest text-gray-500">Music track</label>
        <div className="flex gap-2 items-start">
          <div className="flex-1 min-w-0">
            <MusicPicker
              value={editMusic?.id ?? ""}
              onChange={(id, url, startSec, endSec) => setEditMusic({ id, url, startSec, endSec })}
              category={locCategory || media.category}
              tags={locTags.length ? locTags : media.tags}
            />
          </div>
          <button
            disabled={editBusy || !editMusic}
            onClick={applyMusic}
            title="Apply music swap (no feedback required)"
            className="shrink-0 px-2.5 py-2 text-xs rounded-lg bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white font-medium"
          >
            Apply
          </button>
        </div>
      </div>

      {/* Quick apply: LUT */}
      <div className="space-y-1.5">
        <label className="text-xs font-semibold uppercase tracking-widest text-gray-500">Color grade (LUT)</label>
        <div className="flex gap-2 items-center">
          <div className="flex-1 min-w-0">
            <LutPicker value={editLut} onChange={setEditLut} />
          </div>
          <button
            disabled={editBusy || !editLut}
            onClick={applyLut}
            title="Apply LUT color grade (no feedback required)"
            className="shrink-0 px-2.5 py-2 text-xs rounded-lg bg-amber-700 hover:bg-amber-600 disabled:opacity-40 text-white font-medium"
          >
            Apply
          </button>
        </div>
      </div>

      {/* Divider + advanced dispatch */}
      <div className="border-t border-gray-800 pt-3 space-y-3">
        <label className="text-xs font-semibold uppercase tracking-widest text-gray-500">Custom feedback</label>
        <textarea
          value={editFeedback}
          onChange={(e) => setEditFeedback(e.target.value)}
          placeholder="e.g. slower music, fix saturation, shorten caption…"
          rows={3}
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm resize-none"
        />
        <button
          disabled={editBusy || !editFeedback.trim()}
          onClick={handleDispatchEdit}
          className="w-full flex items-center justify-center gap-2 py-2 text-sm rounded-lg bg-purple-700 hover:bg-purple-600 disabled:opacity-40"
        >
          {editBusy ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
          {editBusy ? "Dispatching…" : "Dispatch edit"}
        </button>
      </div>
    </div>
  );
}
