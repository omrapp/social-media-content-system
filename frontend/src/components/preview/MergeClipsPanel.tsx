import { useState } from "react";
import { motion } from "framer-motion";
import { X, Scissors, Loader2, ArrowUp, ArrowDown, ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { MusicPicker } from "@/components/MusicPicker";
import { CategoryTagsPicker } from "@/components/CategoryTagsPicker";

const TRANSITIONS = [
  "fade", "fadeblack", "fadewhite", "dissolve", "wipeleft", "wiperight",
  "wipeup", "wipedown", "slideleft", "slideright", "slideup", "slidedown",
  "smoothleft", "smoothright", "circleopen", "circleclose", "radial", "pixelize",
];

interface Props {
  /** Pre-selected media ids from the Library (hand-pick mode). Empty = auto only. */
  initialIds?: string[];
  onClose: () => void;
  /** Called after a merge is kicked off so the caller can clear its selection. */
  onSubmitted?: () => void;
}

export function MergeClipsPanel({ initialIds = [], onClose, onSubmitted }: Props) {
  const hasPicked = initialIds.length >= 2;
  const [mode, setMode] = useState<"handpick" | "auto">(hasPicked ? "handpick" : "auto");
  const [order, setOrder] = useState<string[]>(initialIds);

  // auto-select fields
  const [category, setCategory] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [autoCount, setAutoCount] = useState(true);
  const [count, setCount] = useState(4);

  // music override (auto tab)
  const [musicId, setMusicId] = useState("");
  const [musicPath, setMusicPath] = useState("");

  // advanced overrides (auto tab)
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [slowMotion, setSlowMotion] = useState(true);
  const [kenBurns, setKenBurns] = useState(true);
  const [transitionVariety, setTransitionVariety] = useState(true);
  const [audioMode, setAudioMode] = useState<"music" | "original">("music");

  // shared overrides
  const [transition, setTransition] = useState("fade");
  const [duration, setDuration] = useState(30);
  const [busy, setBusy] = useState(false);

  const move = (i: number, d: -1 | 1) => {
    setOrder((prev) => {
      const next = [...prev];
      const j = i + d;
      if (j < 0 || j >= next.length) return prev;
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const submit = async () => {
    if (busy) return;
    let body: Record<string, unknown>;
    if (mode === "handpick") {
      if (order.length < 2) { toast.error("Pick at least 2 clips to merge"); return; }
      body = {
        media_ids: order,
        order,
        overrides: { transition, target_duration_s: duration },
        source: "api",
      };
    } else {
      if (!category) { toast.error("Choose a category"); return; }
      const overrides: Record<string, unknown> = {
        target_duration_s: duration,
        transition,
        audio_mode: audioMode,
        slow_motion: slowMotion,
        ken_burns: kenBurns,
        transition_variety: transitionVariety,
      };
      if (musicPath) overrides.music_path = musicPath;
      body = {
        category,
        tags: tags.length ? tags : undefined,
        ...(autoCount ? {} : { count }),
        overrides,
        source: "api",
      };
    }
    setBusy(true);
    try {
      await api.post("/posts/create-merge", body);
      toast.success("Merge started — preview will appear in the Queue shortly");
      onSubmitted?.();
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Merge failed to start");
    } finally {
      setBusy(false);
    }
  };

  const submitDisabled = busy || (mode === "auto" && !category) || (mode === "handpick" && order.length < 2);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }} onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.18 }}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl overflow-hidden max-h-[90vh] flex flex-col"
        style={{ background: "rgba(17,19,31,1)", border: "1px solid rgba(255,255,255,0.08)" }}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
          <div className="flex items-center gap-2">
            <Scissors size={16} className="text-indigo-400" />
            <h3 className="font-bold text-sm">Merge into one reel</h3>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-white/5 rounded-lg cursor-pointer"><X size={16} /></button>
        </div>

        <div className="p-5 space-y-4 overflow-y-auto">
          {/* mode tabs — auto primary, hand-pick secondary */}
          <div className="flex gap-1 p-1 rounded-xl" style={{ background: "rgba(255,255,255,0.04)" }}>
            <button
              onClick={() => setMode("auto")}
              className={`flex-1 py-1.5 text-xs rounded-lg transition-colors cursor-pointer ${mode === "auto" ? "bg-indigo-600 text-white" : "text-gray-400 hover:text-white"}`}
            >
              Auto-select
            </button>
            <button
              onClick={() => setMode("handpick")}
              disabled={!hasPicked}
              className={`flex-1 py-1.5 text-xs rounded-lg transition-colors disabled:opacity-30 cursor-pointer ${mode === "handpick" ? "bg-indigo-600 text-white" : "text-gray-400 hover:text-white"}`}
            >
              Hand-picked ({initialIds.length})
            </button>
          </div>

          {mode === "handpick" ? (
            <div className="space-y-1.5 max-h-52 overflow-y-auto">
              {order.map((id, i) => (
                <div key={id} className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-mono" style={{ background: "rgba(255,255,255,0.03)" }}>
                  <span className="text-gray-600 w-4">{i + 1}</span>
                  <span className="flex-1 truncate text-gray-300">{id}</span>
                  <button onClick={() => move(i, -1)} disabled={i === 0} className="p-1 disabled:opacity-20 hover:bg-white/5 rounded cursor-pointer"><ArrowUp size={12} /></button>
                  <button onClick={() => move(i, 1)} disabled={i === order.length - 1} className="p-1 disabled:opacity-20 hover:bg-white/5 rounded cursor-pointer"><ArrowDown size={12} /></button>
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              <div className="col-span-2">
                <CategoryTagsPicker
                  category={category}
                  tags={tags}
                  onCategoryChange={setCategory}
                  onTagsChange={setTags}
                  categoryPlaceholder="Category (required)…"
                  variant="compact"
                />
              </div>

              {/* count — Auto by default, omit field when on */}
              <label className="col-span-2 flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
                <input type="checkbox" checked={autoCount} onChange={(e) => setAutoCount(e.target.checked)} className="accent-indigo-500 cursor-pointer" />
                Auto count <span className="text-gray-600">(derive from length)</span>
              </label>
              {!autoCount && (
                <label className="col-span-2 flex items-center justify-between text-xs text-gray-400">
                  Clips: <span className="text-white font-medium">{count}</span>
                  <input type="range" min={2} max={8} value={count} onChange={(e) => setCount(Number(e.target.value))} className="ml-3 flex-1 accent-indigo-500 cursor-pointer" />
                </label>
              )}

              {/* music override */}
              <div className="col-span-2 space-y-1">
                <div className="flex items-center justify-between text-xs text-gray-400">
                  <span>Music {musicPath ? "" : <span className="text-gray-600">(Auto — mood-matched)</span>}</span>
                  {musicPath && (
                    <button type="button" onClick={() => { setMusicId(""); setMusicPath(""); }} className="text-[10px] text-gray-500 hover:text-white cursor-pointer">Clear → Auto</button>
                  )}
                </div>
                <MusicPicker
                  value={musicId}
                  onChange={(id, url) => { setMusicId(id); setMusicPath(url); }}
                  category={category || undefined}
                  tags={tags}
                />
              </div>
            </div>
          )}

          {/* shared overrides */}
          <div className="grid grid-cols-2 gap-2 pt-1">
            <label className="text-xs text-gray-400 space-y-1">
              <span>Transition</span>
              <select value={transition} onChange={(e) => setTransition(e.target.value)} className="w-full px-3 py-2 text-xs rounded-lg bg-gray-900 border border-gray-700 focus:outline-none cursor-pointer">
                {TRANSITIONS.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="text-xs text-gray-400 space-y-1">
              <span>Length: {duration}s</span>
              <input type="range" min={30} max={45} value={duration} onChange={(e) => setDuration(Number(e.target.value))} className="w-full accent-indigo-500 cursor-pointer mt-2" />
            </label>
          </div>

          {/* advanced (auto only) */}
          {mode === "auto" && (
            <div className="pt-1">
              <button
                type="button"
                onClick={() => setShowAdvanced((o) => !o)}
                className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white cursor-pointer"
              >
                <ChevronDown size={13} className={`transition-transform ${showAdvanced ? "rotate-180" : ""}`} />
                Advanced
              </button>
              {showAdvanced && (
                <div className="mt-2 space-y-2 rounded-lg p-3" style={{ background: "rgba(255,255,255,0.03)" }}>
                  <label className="flex items-center justify-between text-xs text-gray-400 cursor-pointer">
                    Slow motion
                    <input type="checkbox" checked={slowMotion} onChange={(e) => setSlowMotion(e.target.checked)} className="accent-indigo-500 cursor-pointer" />
                  </label>
                  <label className="flex items-center justify-between text-xs text-gray-400 cursor-pointer">
                    Ken Burns pan/zoom
                    <input type="checkbox" checked={kenBurns} onChange={(e) => setKenBurns(e.target.checked)} className="accent-indigo-500 cursor-pointer" />
                  </label>
                  <label className="flex items-center justify-between text-xs text-gray-400 cursor-pointer">
                    Transition variety
                    <input type="checkbox" checked={transitionVariety} onChange={(e) => setTransitionVariety(e.target.checked)} className="accent-indigo-500 cursor-pointer" />
                  </label>
                  <label className="flex items-center justify-between text-xs text-gray-400">
                    Audio
                    <select value={audioMode} onChange={(e) => setAudioMode(e.target.value as "music" | "original")} className="px-2 py-1 text-xs rounded-lg bg-gray-900 border border-gray-700 focus:outline-none cursor-pointer">
                      <option value="music">Music bed</option>
                      <option value="original">Original audio</option>
                    </select>
                  </label>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-white/5 flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 text-xs rounded-lg hover:bg-white/5 cursor-pointer transition-colors">Cancel</button>
          <button onClick={submit} disabled={submitDisabled} className="px-4 py-2 text-xs rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 flex items-center gap-1.5 cursor-pointer transition-colors">
            {busy && <Loader2 size={12} className="animate-spin" />}
            Merge
          </button>
        </div>
      </motion.div>
    </div>
  );
}
