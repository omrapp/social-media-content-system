import { Loader2, RefreshCw } from "lucide-react";
import { FLAGS, type FlagKey } from "./shared";

type Props = {
  selectedFlags: Set<FlagKey>;
  toggleFlag: (key: FlagKey) => void;
  actionableFlagCount: number;
  flagBusy: boolean;
  applyFlags: () => void;
};

export function QuickFlagsPanel({
  selectedFlags, toggleFlag, actionableFlagCount, flagBusy, applyFlags,
}: Props) {
  return (
    <div className="p-4 space-y-2">
      <label className="text-xs font-semibold uppercase tracking-widest text-gray-500">Quick flags</label>
      <div className="space-y-1.5">
        {FLAGS.map(({ key, label, actionable }) => (
          <label key={key} className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
            <input
              type="checkbox"
              checked={selectedFlags.has(key)}
              onChange={() => toggleFlag(key)}
              className="accent-amber-500"
            />
            {label}
            {actionable && <span className="text-[10px] text-amber-500/70">↻</span>}
          </label>
        ))}
      </div>

      {/* Re-render for the actionable subset (music / color / aspect / order).
          Caption & category flags are annotation-only and don't touch the video. */}
      <button
        disabled={flagBusy || actionableFlagCount === 0}
        onClick={applyFlags}
        title="Re-render the video for the selected ↻ flags"
        className="w-full flex items-center justify-center gap-2 py-1.5 text-xs rounded-lg bg-amber-800 hover:bg-amber-700 disabled:opacity-40"
      >
        {flagBusy
          ? <><Loader2 size={12} className="animate-spin" /> Applying…</>
          : <><RefreshCw size={12} /> Apply flags{actionableFlagCount > 0 ? ` (${actionableFlagCount})` : ""}</>
        }
      </button>
      <p className="text-[10px] text-gray-600 leading-snug">
        ↻ flags re-render the video. Caption &amp; category flags are saved as notes only.
      </p>
    </div>
  );
}
