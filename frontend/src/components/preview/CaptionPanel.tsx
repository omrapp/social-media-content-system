import { RefreshCw } from "lucide-react";
import type { UsePreview } from "@/hooks/usePreview";

type Props = Pick<UsePreview,
  "captionDraft" | "captionDirty" | "editCaption" | "saveCaption" |
  "discardCaption" | "saveCapPending" | "regenBusy" | "doRegen">;

export function CaptionPanel({
  captionDraft, captionDirty, editCaption, saveCaption,
  discardCaption, saveCapPending, regenBusy, doRegen,
}: Props) {
  return (
    <div className="p-4 border-b border-gray-800 space-y-2">
      <label className="text-xs font-semibold uppercase tracking-widest text-gray-500">Caption</label>
      <textarea
        value={captionDraft}
        onChange={(e) => editCaption(e.target.value)}
        rows={8}
        className={`w-full bg-gray-800 border rounded px-3 py-2 text-sm resize-none text-gray-200 ${
          captionDirty ? "border-amber-600" : "border-gray-700"
        }`}
      />
      {captionDirty && (
        <div className="flex gap-2">
          <button onClick={saveCaption} disabled={saveCapPending} className="text-xs text-green-400 hover:text-green-300 disabled:opacity-40">Save</button>
          <button onClick={discardCaption} className="text-xs text-gray-500">Discard</button>
        </div>
      )}
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-600">{captionDraft.length} chars</p>
        <button
          disabled={regenBusy}
          onClick={doRegen}
          className="flex items-center gap-1 text-xs text-gray-500 hover:text-purple-400 disabled:opacity-40"
          title="Regenerate caption with AI using current location"
        >
          <RefreshCw size={11} className={regenBusy ? "animate-spin" : ""} />
          {regenBusy ? "Generating…" : "AI regen"}
        </button>
      </div>
    </div>
  );
}
