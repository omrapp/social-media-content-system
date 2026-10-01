import { useCallback, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Shuffle, ChevronRight,
  Loader2, CheckCircle2, AlertCircle, Film, Sparkles,
  ArrowLeft, Layers, Video, Music, Palette, RefreshCw, X, Eraser,
} from "lucide-react";
import { api } from "@/lib/api";
import { useWs } from "@/hooks/useWs";
import { useApi } from "@/hooks/useApi";
import { upsertTask } from "@/lib/taskStore";
import { useActiveTasks } from "@/hooks/useTasks";
import { MusicPicker } from "@/components/MusicPicker";
import { LutPicker } from "@/components/LutPicker";
import { CategoryTagsPicker } from "@/components/CategoryTagsPicker";

type Mode = "single" | "merge";
type Strategy = "diverse" | "best" | "random";
type Step = "strategy" | "filters" | "customize" | "confirm" | "running" | "done" | "error";

interface ClipPreview {
  media_id: string;
  local_path?: string;
  category?: string;
  tags?: string[];
  duration_s?: number;
}

export function CreatePage() {
  const navigate = useNavigate();

  const [mode, setMode] = useState<Mode>("single");
  const [step, setStep] = useState<Step>("strategy");
  const [strategy, setStrategy] = useState<Strategy>("diverse");
  const [category, setCategory] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [resultMediaId, setResultMediaId] = useState<string | null>(null);
  const [pendingMediaId, setPendingMediaId] = useState<string | null>(null);
  const [mergeRunning, setMergeRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>([]);

  // ── Customize step state (music / LUT / clip preview) ───────────────────────
  const [music, setMusic] = useState("");        // MusicPicker value (track id)
  const [musicUrl, setMusicUrl] = useState("");  // served URL sent to backend
  const [lut, setLut] = useState("");            // LUTS_DIR-relative .cube file
  const [preview, setPreview] = useState<ClipPreview | null>(null);   // single: picked clip
  const [excludeIds, setExcludeIds] = useState<string[]>([]);        // clips already skipped
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [decaption, setDecaption] = useState(false);  // per-flow decaption override (defaults to global)
  // Per-run merge segment split (min stock B-roll + min local clips per reel).
  const [stockSeg, setStockSeg] = useState(8);
  const [localSeg, setLocalSeg] = useState(12);

  // ── Resume from global task store on mount ──────────────────────────────────
  // If a create task is still running (survived navigation or reload), jump
  // straight to the running view so the user sees their in-progress job.
  const activeTasks = useActiveTasks();
  useEffect(() => {
    const active = activeTasks.find((t) => t.type === "create");
    if (active && step === "strategy") {
      setStep("running");
      setLogs(["Resuming from task store — waiting for pipeline events…"]);
    }
  }, []); // intentionally run once on mount only

  // ── WS subscriptions (also update the global store) ────────────────────────
  // Note: the store is the source of truth for survive-navigation; these
  // handlers only update local UI state for the in-page log / step display.

  useWs("pipeline_complete", useCallback((data: Record<string, unknown>) => {
    const mid = data.media_id as string | undefined;
    // Merge mode: create-merge returns no media_id upfront; merged reels emit a
    // `mrg_*` media row. Match completion on that prefix (collision-safe vs
    // single-clip jobs).
    if (mergeRunning) {
      if (mid && mid.startsWith("mrg_")) {
        setMergeRunning(false);
        setResultMediaId(mid);
        setStep("done");
      }
      return;
    }
    if (!mid) {
      setLogs((prev) => [...prev, `[DONE] ${data.stage}`]);
      return;
    }
    // Ignore completions for other concurrent jobs (e.g. auto-create daemon)
    if (pendingMediaId && mid !== pendingMediaId) return;
    setResultMediaId(mid);
    setStep("done");
  }, [pendingMediaId, mergeRunning]));

  useWs("pipeline_failed", useCallback((data: Record<string, unknown>) => {
    const mid = data.media_id as string | undefined;
    if (mergeRunning) {
      // Merge failures arrive with no media_id or a mrg_* id.
      if (!mid || mid.startsWith("mrg_")) {
        setMergeRunning(false);
        setError(data.error as string ?? "Merge failed");
        setStep((prev) => prev === "done" ? "done" : "error");
      }
      return;
    }
    // Ignore failures from other concurrent jobs
    if (pendingMediaId && mid && mid !== pendingMediaId) return;
    setError(data.error as string ?? "Pipeline failed");
    setStep((prev) => prev === "done" ? "done" : "error");
  }, [pendingMediaId, mergeRunning]));

  useWs("pipeline_start", useCallback((data: Record<string, unknown>) => {
    setLogs((prev) => [...prev, `Running: ${data.stage}…`]);
  }, []));

  // ── Submit ──────────────────────────────────────────────────────────────────

  const submit = async () => {
    setStep("running");
    setLogs(["Selecting clip…"]);
    setError(null);

    const body: Record<string, unknown> = { strategy };
    if (category) body.category = category;
    if (tags.length) body.tags = tags;
    // Lock the previewed clip + wizard music/LUT picks. No pick → keep original
    // (no auto music / no colour grade). Per-flow decaption override sent explicitly.
    if (preview?.media_id) body.media_id = preview.media_id;
    if (musicUrl) body.music_path = musicUrl;
    else body.keep_original_audio = true;
    if (lut) body.lut = lut;
    else body.no_lut = true;
    body.decaption = decaption;

    try {
      const res = await api.post<{ media_id?: string; status?: string; source?: string }>(
        "/posts/create",
        body
      );
      // Register task in the global store NOW — before the WS event arrives.
      // This guarantees the task persists even if the user navigates away before
      // the pipeline_complete event fires.
      const mediaId = res?.media_id;
      if (mediaId) {
        setPendingMediaId(mediaId);
        const filterParts = [category, ...tags].filter(Boolean).join(", ");
        upsertTask({
          id: mediaId,
          type: "create",
          label: `Create video${filterParts ? ` (${filterParts})` : ""}`,
          status: "running",
          mediaId,
          stage: "started",
        });
      }
      setLogs((prev) => [...prev, "Pipeline started — waiting for completion…"]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
      setStep("error");
    }
  };

  // ── Submit (merge) ────────────────────────────────────────────────────────────
  // Category required; tags optional (secondary filter within it). The backend
  // renders the montage in the background — no media_id is returned, so
  // completion is matched by the `mrg_*` prefix in the WS handlers above.
  const submitMerge = async () => {
    setStep("running");
    setLogs(["Selecting clips for the montage…"]);
    setError(null);
    setMergeRunning(true);

    const body: Record<string, unknown> = { category };
    if (tags.length) body.tags = tags;
    // Wizard music/LUT picks → per-request merge overrides. No music pick → fall
    // back to the auto mood-matched music bed (backend default audio_mode=music),
    // NOT the clips' raw audio; no LUT pick → skip the edit-tail grade.
    const overrides: Record<string, unknown> = {};
    if (musicUrl) overrides.music_path = musicUrl;
    if (lut) overrides.lut = lut;
    // Per-run stock/local segment split → merge_clips reads these off `settings`.
    if (splitEnabled) {
      overrides.min_stock_segments = stockSeg;
      overrides.min_local_segments = localSeg;
    }
    if (Object.keys(overrides).length) body.overrides = overrides;
    body.decaption = decaption;

    try {
      await api.post<{ status?: string; source?: string }>("/posts/create-merge", body);
      const filterParts = [category, ...tags].filter(Boolean).join(", ");
      upsertTask({
        id: `merge-${category}-${Date.now()}`,
        type: "create",
        label: `Merge reel${filterParts ? ` (${filterParts})` : ""}`,
        status: "running",
        stage: "merging",
      });
      setLogs((prev) => [...prev, "Merge render started — this can take a few minutes…"]);
    } catch (e) {
      setMergeRunning(false);
      setError(e instanceof Error ? e.message : "Request failed");
      setStep("error");
    }
  };

  // ── Customize step ──────────────────────────────────────────────────────────
  // Single mode: dry-run select a clip so the user can preview it (and re-pick a
  // different one) before running the pipeline. `exclude` carries already-skipped
  // clip ids so "Pick a new video" cycles forward.
  const loadPreview = useCallback(async (exclude: string[]) => {
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const res = await api.post<ClipPreview>("/posts/select-preview", {
        strategy,
        category: category || undefined,
        tags: tags.length ? tags : undefined,
        exclude_ids: exclude,
      });
      setPreview(res);
    } catch (e) {
      setPreview(null);
      setPreviewError(e instanceof Error ? e.message : "No matching clip found");
    } finally {
      setPreviewLoading(false);
    }
  }, [strategy, category, tags]);

  const goCustomize = () => {
    setStep("customize");
    setDecaption(decaptionGlobal);   // seed per-flow toggle from the global setting
    if (mode === "single") {
      setExcludeIds([]);
      setPreview(null);
      loadPreview([]);
    }
  };

  const repick = () => {
    const next = preview ? [...excludeIds, preview.media_id] : excludeIds;
    setExcludeIds(next);
    loadPreview(next);
  };

  const resetCustomize = () => {
    setMusic("");
    setMusicUrl("");
    setLut("");
    setPreview(null);
    setExcludeIds([]);
    setPreviewLoading(false);
    setPreviewError(null);
    setDecaption(false);
  };

  const reset = () => {
    setStep(mode === "merge" ? "filters" : "strategy");
    setStrategy("diverse");
    setCategory("");
    setTags([]);
    setResultMediaId(null);
    setPendingMediaId(null);
    setMergeRunning(false);
    setError(null);
    setLogs([]);
    resetCustomize();
  };

  const switchMode = (m: Mode) => {
    if (m === mode) return;
    setMode(m);
    setStep(m === "merge" ? "filters" : "strategy");
    setStrategy("diverse");
    setCategory("");
    setTags([]);
    setResultMediaId(null);
    setPendingMediaId(null);
    setMergeRunning(false);
    setError(null);
    setLogs([]);
    resetCustomize();
  };

  // ── Data fetches ────────────────────────────────────────────────────────────

  const { data: categoriesResp, loading: categoriesLoading } = useApi<{ categories: string[] }>("/taxonomy/categories");
  // Global decaption default — seeds the per-flow toggle in the Customize step.
  const { data: decapCfg } = useApi<{ value?: { enabled?: boolean } }>("/settings/decaption");
  const decaptionGlobal = decapCfg?.value?.enabled ?? false;

  const categories = categoriesResp?.categories ?? [];

  // Merge availability: live count of raw VIDEO clips matching the filters, and
  // the recommended floor (merge.min_main_videos) for a full montage.
  const { data: mergeCfg } = useApi<{ value?: {
    min_main_videos?: number;
    split_stock_local?: boolean;
    min_stock_segments?: number;
    min_local_segments?: number;
  } }>(
    mode === "merge" ? "/settings/merge" : null
  );
  const minVideos = mergeCfg?.value?.min_main_videos ?? 10;
  const splitEnabled = mergeCfg?.value?.split_stock_local ?? true;
  // Seed the per-run segment split from the saved merge defaults once they load.
  useEffect(() => {
    const v = mergeCfg?.value;
    if (!v) return;
    if (typeof v.min_stock_segments === "number") setStockSeg(v.min_stock_segments);
    if (typeof v.min_local_segments === "number") setLocalSeg(v.min_local_segments);
  }, [mergeCfg]);
  const countQuery =
    mode === "merge" && category
      ? `/media/count?category=${encodeURIComponent(category)}` +
        tags.map((t) => `&tags=${encodeURIComponent(t)}`).join("")
      : null;
  const { data: countResp, loading: countLoading } = useApi<{ count: number }>(countQuery);
  const videoCount = countResp?.count ?? null;

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate(-1)}
          className="p-1.5 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={18} />
        </button>
        <div>
          <h2 className="text-2xl font-bold text-white flex items-center gap-2">
            <Film size={22} className="text-purple-400" />
            Create Video
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">Single clip or a multi-clip merge montage → run the pipeline → preview post.</p>
        </div>
      </div>

      <ModeToggle mode={mode} onChange={switchMode} />

      <StepIndicator step={step} mode={mode} />

      {mode === "single" && step === "strategy" && (
        <StrategyStep
          strategy={strategy}
          onSelect={(s) => { setStrategy(s); setStep("filters"); }}
        />
      )}

      {mode === "single" && step === "filters" && (
        <FiltersStep
          strategy={strategy}
          category={category}
          tags={tags}
          categories={categories}
          categoriesLoading={categoriesLoading}
          onCategoryChange={setCategory}
          onTagsChange={setTags}
          onBack={() => setStep("strategy")}
          onNext={goCustomize}
        />
      )}

      {mode === "single" && step === "customize" && (
        <CustomizeStep
          mode="single"
          category={category}
          music={music}
          lut={lut}
          preview={preview}
          previewLoading={previewLoading}
          previewError={previewError}
          decaption={decaption}
          decaptionGlobal={decaptionGlobal}
          onDecaptionChange={setDecaption}
          onMusicChange={(id, url) => { setMusic(id); setMusicUrl(url); }}
          onLutChange={setLut}
          onContinue={() => setStep("confirm")}
          onRepick={repick}
          onBack={() => setStep("filters")}
          onCancel={reset}
        />
      )}

      {mode === "single" && step === "confirm" && (
        <ConfirmStep
          strategy={strategy}
          category={category}
          tags={tags}
          mediaId={preview?.media_id ?? null}
          music={music}
          lut={lut}
          decaption={decaption}
          onBack={() => setStep("customize")}
          onConfirm={submit}
        />
      )}

      {mode === "merge" && step === "filters" && (
        <MergeFiltersStep
          category={category}
          tags={tags}
          categories={categories}
          categoriesLoading={categoriesLoading}
          videoCount={videoCount}
          countLoading={countLoading}
          minVideos={minVideos}
          onCategoryChange={setCategory}
          onTagsChange={setTags}
          onNext={goCustomize}
        />
      )}

      {mode === "merge" && step === "customize" && splitEnabled && (
        <MergeSegmentSplit
          stockSeg={stockSeg}
          localSeg={localSeg}
          onStockChange={setStockSeg}
          onLocalChange={setLocalSeg}
        />
      )}

      {mode === "merge" && step === "customize" && (
        <CustomizeStep
          mode="merge"
          category={category}
          music={music}
          lut={lut}
          preview={null}
          previewLoading={false}
          previewError={null}
          decaption={decaption}
          decaptionGlobal={decaptionGlobal}
          onDecaptionChange={setDecaption}
          onMusicChange={(id, url) => { setMusic(id); setMusicUrl(url); }}
          onLutChange={setLut}
          onContinue={() => setStep("confirm")}
          onRepick={repick}
          onBack={() => setStep("filters")}
          onCancel={reset}
        />
      )}

      {mode === "merge" && step === "confirm" && (
        <MergeConfirmStep
          category={category}
          tags={tags}
          videoCount={videoCount}
          minVideos={minVideos}
          music={music}
          lut={lut}
          decaption={decaption}
          onBack={() => setStep("customize")}
          onConfirm={submitMerge}
        />
      )}

      {step === "running" && <RunningStep logs={logs} />}

      {step === "done" && resultMediaId && (
        <DoneStep
          mediaId={resultMediaId}
          onAnother={reset}
          onPreview={() => navigate(`/preview/${resultMediaId}`)}
          onQueue={() => navigate("/queue")}
        />
      )}

      {step === "error" && (
        <ErrorStep error={error} onRetry={reset} />
      )}
    </div>
  );
}

function MergeSegmentSplit({
  stockSeg, localSeg, onStockChange, onLocalChange,
}: {
  stockSeg: number;
  localSeg: number;
  onStockChange: (n: number) => void;
  onLocalChange: (n: number) => void;
}) {
  const clamp = (n: number) => Math.max(0, Math.min(30, Math.round(n) || 0));
  const total = stockSeg + localSeg;
  const field = (
    label: string, hint: string, value: number, onChange: (n: number) => void,
  ) => (
    <div className="flex-1 min-w-[130px]">
      <label className="block text-xs font-medium text-gray-300">{label}</label>
      <p className="text-[11px] text-gray-600 mb-1.5">{hint}</p>
      <input
        type="number" min={0} max={30} value={value}
        onChange={(e) => onChange(clamp(Number(e.target.value)))}
        className="w-full rounded-lg px-2.5 py-2 text-sm text-gray-200 focus:outline-none"
        style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
      />
    </div>
  );
  return (
    <div className="rounded-xl p-4 mb-4 space-y-3" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-200">Segment mix</h3>
        <span className="text-xs text-gray-500 tabular-nums">
          min <span className="text-gray-300 font-medium">{total}</span> clips total
        </span>
      </div>
      <div className="flex flex-wrap gap-4">
        {field("Stock clips", "Pexels/Pixabay B-roll", stockSeg, onStockChange)}
        {field("Local clips", "Your archive footage", localSeg, onLocalChange)}
      </div>
      <p className="text-[11px] text-gray-600 leading-relaxed">
        Minimum clips pulled from each source. A thin pool on one side tops up from the other,
        so the reel always reaches the target length.
      </p>
    </div>
  );
}

function StepIndicator({ step, mode }: { step: Step; mode: Mode }) {
  const steps: { key: Step; label: string }[] =
    mode === "merge"
      ? [
          { key: "filters", label: "Filters" },
          { key: "customize", label: "Customize" },
          { key: "confirm", label: "Confirm" },
          { key: "running", label: "Running" },
          { key: "done", label: "Done" },
        ]
      : [
          { key: "strategy", label: "Strategy" },
          { key: "filters", label: "Filters" },
          { key: "customize", label: "Customize" },
          { key: "confirm", label: "Confirm" },
          { key: "running", label: "Running" },
          { key: "done", label: "Done" },
        ];
  const activeIdx = steps.findIndex((s) => s.key === step || (step === "error" && s.key === "running"));

  return (
    <div className="flex items-center gap-2">
      {steps.map((s, i) => (
        <div key={s.key} className="flex items-center gap-2">
          <div className={`flex items-center gap-1.5 text-xs font-medium transition-colors ${
            i < activeIdx ? "text-green-400" :
            i === activeIdx ? "text-white" : "text-gray-600"
          }`}>
            <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${
              i < activeIdx ? "bg-green-500/20 text-green-400" :
              i === activeIdx ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-600"
            }`}>
              {i < activeIdx ? "✓" : i + 1}
            </span>
            <span className="hidden sm:block">{s.label}</span>
          </div>
          {i < steps.length - 1 && (
            <div className={`flex-1 h-px w-8 ${i < activeIdx ? "bg-green-500/40" : "bg-gray-800"}`} />
          )}
        </div>
      ))}
    </div>
  );
}

function ModeToggle({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  const opts: { key: Mode; label: string; desc: string; icon: React.ElementType }[] = [
    { key: "single", label: "Single clip", desc: "One raw clip → reel", icon: Video },
    { key: "merge", label: "Merge reel", desc: "Many clips → montage", icon: Layers },
  ];
  return (
    <div className="grid grid-cols-2 gap-3">
      {opts.map((o) => {
        const Icon = o.icon;
        const active = mode === o.key;
        return (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            className={`flex items-center gap-3 p-3.5 rounded-xl border text-left transition-all ${
              active
                ? "border-purple-500 bg-purple-500/10 ring-1 ring-purple-500/20"
                : "border-gray-700 bg-gray-900 hover:border-gray-600"
            }`}
          >
            <Icon size={18} className={active ? "text-purple-400" : "text-gray-500"} />
            <div>
              <div className="text-sm font-semibold text-white">{o.label}</div>
              <div className="text-xs text-gray-500">{o.desc}</div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function AvailabilityBadge({
  count, loading, minVideos, category,
}: { count: number | null; loading: boolean; minVideos: number; category: string }) {
  if (!category) {
    return (
      <p className="text-xs text-gray-500">Select a category to see how many videos are available.</p>
    );
  }
  if (loading || count === null) {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-500">
        <Loader2 size={12} className="animate-spin" /> Counting available videos…
      </div>
    );
  }
  // red <2 (can't merge), amber 2..min-1 (works but thin), green >=min (full montage)
  const tone =
    count < 2 ? "red" : count < minVideos ? "amber" : "green";
  const map: Record<string, string> = {
    red: "bg-red-950/40 border-red-800/50 text-red-300",
    amber: "bg-amber-950/40 border-amber-800/50 text-amber-300",
    green: "bg-green-950/40 border-green-800/50 text-green-300",
  };
  return (
    <div className={`flex items-center justify-between rounded-lg border px-3 py-2 text-xs ${map[tone]}`}>
      <span className="flex items-center gap-1.5 font-medium">
        <Video size={13} />
        {count} video{count === 1 ? "" : "s"} available
      </span>
      <span className="opacity-70">
        {count < 2
          ? "need ≥2 to merge"
          : count < minVideos
          ? `≥${minVideos} recommended`
          : "ready for a full montage"}
      </span>
    </div>
  );
}

function MergeFiltersStep({
  category, tags,
  categories, categoriesLoading,
  videoCount, countLoading, minVideos,
  onCategoryChange, onTagsChange, onNext,
}: {
  category: string; tags: string[];
  categories: string[]; categoriesLoading: boolean;
  videoCount: number | null; countLoading: boolean; minVideos: number;
  onCategoryChange: (v: string) => void;
  onTagsChange: (v: string[]) => void;
  onNext: () => void;
}) {
  const canProceed = !!category && (videoCount === null || videoCount >= 2);
  const noCategories = !categoriesLoading && categories.length === 0;

  return (
    <div className="space-y-5">
      <h3 className="text-sm font-medium text-gray-400">
        Pick a category (required). Tags are an optional secondary filter.
      </h3>

      {noCategories && (
        <div className="bg-amber-950/30 border border-amber-800/50 rounded-xl p-4 text-sm">
          <p className="text-amber-300 font-medium mb-1">No indexed media found</p>
          <p className="text-amber-400/70 text-xs">
            Go to <strong>Downloads</strong> to fetch videos, then run <strong>Pipeline → Index</strong>.
          </p>
        </div>
      )}

      <CategoryTagsPicker
        category={category}
        tags={tags}
        onCategoryChange={onCategoryChange}
        onTagsChange={onTagsChange}
        categoryPlaceholder={categoriesLoading ? "Loading…" : "Select category"}
        disabled={categoriesLoading}
        variant="wizard"
      />

      <AvailabilityBadge count={videoCount} loading={countLoading} minVideos={minVideos} category={category} />

      <div className="flex gap-3 pt-2">
        <button
          onClick={onNext}
          disabled={!canProceed}
          className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-800 disabled:text-gray-500 disabled:cursor-not-allowed rounded-lg text-sm font-medium text-white transition-colors"
        >
          Continue <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}

function MergeConfirmStep({
  category, tags, videoCount, minVideos, music, lut, decaption, onBack, onConfirm,
}: {
  category: string; tags: string[];
  videoCount: number | null; minVideos: number;
  music?: string; lut?: string; decaption?: boolean;
  onBack: () => void; onConfirm: () => void;
}) {
  const thin = videoCount !== null && videoCount < minVideos;
  return (
    <div className="space-y-5">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-3">
        <h3 className="text-sm font-medium text-gray-400 mb-4">Review your montage</h3>

        <Row label="Mode" value="Merge reel (multi-clip montage)" />
        <Row label="Category" value={category} />
        {tags.length > 0 && <Row label="Tags" value={tags.join(", ")} />}
        {videoCount !== null && <Row label="Videos available" value={String(videoCount)} />}
        <Row label="Music" value={music ? music : "Original clip audio (kept)"} />
        <Row label="LUT" value={lut ? lut : "None (original look)"} />
        <Row label="Decaption" value={decaption ? "On" : "Off"} />

        {thin && (
          <p className="text-xs text-amber-400/80 pt-1">
            Fewer than {minVideos} videos — the montage will still build but repeats more cuts per clip.
          </p>
        )}

        <div className="pt-3 border-t border-gray-800 text-xs text-gray-500 space-y-1">
          <p>Stitches video clips (no images) into one cinematic reel: <span className="text-gray-300">merge → caption → edit → upload</span>.</p>
          <p>A preview post will be created and queued for approval.</p>
        </div>
      </div>

      <div className="flex gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-2 px-4 py-2 border border-gray-700 rounded-lg text-sm text-gray-300 hover:bg-gray-800 transition-colors"
        >
          <ArrowLeft size={14} /> Back
        </button>
        <button
          onClick={onConfirm}
          className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-semibold text-white transition-colors"
        >
          <Layers size={15} /> Create Merge Reel
        </button>
      </div>
    </div>
  );
}

function StrategyStep({ strategy, onSelect }: { strategy: Strategy; onSelect: (s: Strategy) => void }) {
  const options: { key: Strategy; label: string; desc: string; icon: React.ElementType; color: string }[] = [
    {
      key: "diverse",
      label: "Diverse pick",
      desc: "Cross-category pick with cooldown, avoiding recently-used categories. Recommended.",
      icon: Layers,
      color: "purple",
    },
    {
      key: "best",
      label: "Best clip",
      desc: "Pick the highest hook-score raw clip matching your category/tags.",
      icon: Sparkles,
      color: "blue",
    },
    {
      key: "random",
      label: "Random",
      desc: "Pick a random unposted clip matching your filters.",
      icon: Shuffle,
      color: "orange",
    },
  ];

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-gray-400">How should we pick the clip?</h3>
      {options.map((opt) => {
        const Icon = opt.icon;
        const colorMap: Record<string, string> = {
          purple: "border-purple-500 bg-purple-500/10 ring-purple-500/20",
          blue: "border-blue-500 bg-blue-500/10 ring-blue-500/20",
          orange: "border-orange-500 bg-orange-500/10 ring-orange-500/20",
        };
        const iconMap: Record<string, string> = {
          purple: "text-purple-400",
          blue: "text-blue-400",
          orange: "text-orange-400",
        };
        return (
          <button
            key={opt.key}
            onClick={() => onSelect(opt.key)}
            className={`w-full text-left p-4 rounded-xl border transition-all group ${
              strategy === opt.key
                ? `${colorMap[opt.color]} ring-1`
                : "border-gray-700 bg-gray-900 hover:border-gray-600"
            }`}
          >
            <div className="flex items-center gap-3">
              <Icon size={18} className={strategy === opt.key ? iconMap[opt.color] : "text-gray-500 group-hover:text-gray-400"} />
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-white">{opt.label}</span>
                  <ChevronRight size={14} className="text-gray-600 group-hover:text-gray-400" />
                </div>
                <p className="text-xs text-gray-500 mt-0.5">{opt.desc}</p>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function FiltersStep({
  strategy, category, tags,
  categories, categoriesLoading,
  onCategoryChange, onTagsChange,
  onBack, onNext,
}: {
  strategy: Strategy;
  category: string; tags: string[];
  categories: string[]; categoriesLoading: boolean;
  onCategoryChange: (v: string) => void;
  onTagsChange: (v: string[]) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  // 'diverse' picks cross-category with cooldown — no filters apply.
  const needsFilters = strategy !== "diverse";
  const canProceed = strategy === "diverse" ? true : !!category;

  const noCategories = !categoriesLoading && categories.length === 0;

  return (
    <div className="space-y-5">
      <h3 className="text-sm font-medium text-gray-400">
        {strategy === "diverse" ? "No filters needed — picks across categories automatically" : "Select filters"}
      </h3>

      {noCategories && (
        <div className="bg-amber-950/30 border border-amber-800/50 rounded-xl p-4 text-sm">
          <p className="text-amber-300 font-medium mb-1">No indexed media found</p>
          <p className="text-amber-400/70 text-xs">
            Go to <strong>Downloads</strong> to fetch your Instagram posts, then run the <strong>Pipeline → Index</strong> stage to populate categories.
          </p>
        </div>
      )}

      {needsFilters && (
        <CategoryTagsPicker
          category={category}
          tags={tags}
          onCategoryChange={onCategoryChange}
          onTagsChange={onTagsChange}
          categoryPlaceholder={categoriesLoading ? "Loading…" : "Select category"}
          disabled={categoriesLoading}
          variant="wizard"
        />
      )}

      <div className="flex gap-3 pt-2">
        <button
          onClick={onBack}
          className="flex items-center gap-2 px-4 py-2 border border-gray-700 rounded-lg text-sm text-gray-300 hover:bg-gray-800 transition-colors"
        >
          <ArrowLeft size={14} /> Back
        </button>
        <button
          onClick={onNext}
          disabled={!canProceed}
          className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-800 disabled:text-gray-500 disabled:cursor-not-allowed rounded-lg text-sm font-medium text-white transition-colors"
        >
          Continue <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}

function CustomizeStep({
  mode, category, music, lut, preview, previewLoading, previewError,
  decaption, decaptionGlobal, onDecaptionChange,
  onMusicChange, onLutChange, onContinue, onRepick, onBack, onCancel,
}: {
  mode: Mode;
  category: string;
  music: string;
  lut: string;
  preview: ClipPreview | null;
  previewLoading: boolean;
  previewError: string | null;
  decaption: boolean;
  decaptionGlobal: boolean;
  onDecaptionChange: (v: boolean) => void;
  onMusicChange: (id: string, url: string) => void;
  onLutChange: (file: string) => void;
  onContinue: () => void;
  onRepick: () => void;
  onBack: () => void;
  onCancel: () => void;
}) {
  const isSingle = mode === "single";
  // Single mode can only continue once a clip has been picked.
  const canContinue = !isSingle || (!!preview && !previewLoading);

  return (
    <div className="space-y-5">
      <h3 className="text-sm font-medium text-gray-400">
        {isSingle
          ? "Review the picked clip, then choose music and a colour grade (both optional)."
          : "Choose music and a colour grade for the montage (both optional)."}
      </h3>

      {/* Picked clip preview (single mode only) */}
      {isSingle && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          {previewLoading ? (
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <Loader2 size={14} className="animate-spin" /> Picking a clip…
            </div>
          ) : previewError ? (
            <div className="flex items-start gap-2 text-xs text-red-300">
              <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
              <span className="font-mono break-words">{previewError}</span>
            </div>
          ) : preview ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-white">
                <Video size={15} className="text-purple-400" /> Picked clip
              </div>
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between gap-3">
                  <span className="text-gray-500">Media ID</span>
                  <code className="text-gray-300 truncate">{preview.media_id}</code>
                </div>
                {preview.local_path && (
                  <div className="flex justify-between gap-3">
                    <span className="text-gray-500 shrink-0">Path</span>
                    <code className="text-gray-400 truncate" title={preview.local_path}>{preview.local_path}</code>
                  </div>
                )}
                <div className="flex justify-between gap-3">
                  <span className="text-gray-500">Category</span>
                  <span className="text-gray-300 truncate">
                    {[preview.category, ...(preview.tags ?? [])].filter(Boolean).join(", ") || "—"}
                  </span>
                </div>
                {preview.duration_s != null && (
                  <div className="flex justify-between gap-3">
                    <span className="text-gray-500">Duration</span>
                    <span className="text-gray-300">{preview.duration_s.toFixed(1)}s</span>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <p className="text-xs text-gray-500">No clip picked yet.</p>
          )}
        </div>
      )}

      {/* Music */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wide flex items-center gap-1.5">
          <Music size={12} /> Music (optional)
        </label>
        <MusicPicker
          value={music}
          onChange={(id, url) => onMusicChange(id, url)}
          category={category || undefined}
        />
      </div>

      {/* LUT */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wide flex items-center gap-1.5">
          <Palette size={12} /> Colour grade / LUT (optional)
        </label>
        <LutPicker value={lut} onChange={onLutChange} />
        {!lut && (
          <p className="text-[11px] text-gray-500 mt-1">No LUT — keeps the original video look.</p>
        )}
      </div>

      {!music && (
        <p className="text-[11px] text-gray-500 -mt-3">
          No track — {isSingle ? "keeps the clip's original audio" : "we'll add a mood-matched music bed automatically"}.
        </p>
      )}

      {/* Decaption toggle */}
      <label className="flex items-start gap-3 p-3 rounded-lg border border-gray-800 bg-gray-900 cursor-pointer">
        <input
          type="checkbox"
          checked={decaption}
          onChange={(e) => onDecaptionChange(e.target.checked)}
          className="mt-0.5 h-4 w-4 accent-purple-600 cursor-pointer"
        />
        <span className="flex-1">
          <span className="flex items-center gap-1.5 text-sm font-medium text-gray-200">
            <Eraser size={13} className="text-purple-400" /> Remove burned-in captions (decaption)
          </span>
          <span className="block text-[11px] text-gray-500 mt-0.5">
            Strip burned-in IG captions/watermarks from source clips for this reel.
            Global default: <span className="text-gray-400">{decaptionGlobal ? "on" : "off"}</span>
            {decaption !== decaptionGlobal && <span className="text-amber-400"> · overridden</span>}.
            Needs one-time setup (see Docs).
          </span>
        </span>
      </label>

      {/* Actions: continue · re-pick (single) · cancel */}
      <div className="flex flex-wrap gap-3 pt-1">
        <button
          onClick={onContinue}
          disabled={!canContinue}
          className="flex-1 min-w-[8rem] flex items-center justify-center gap-2 px-4 py-2.5 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-800 disabled:text-gray-500 disabled:cursor-not-allowed rounded-lg text-sm font-semibold text-white transition-colors"
        >
          Continue <ChevronRight size={15} />
        </button>
        {isSingle && (
          <button
            onClick={onRepick}
            disabled={previewLoading}
            className="flex items-center justify-center gap-2 px-4 py-2.5 border border-gray-700 rounded-lg text-sm text-gray-300 hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <RefreshCw size={14} /> Pick new video
          </button>
        )}
        <button
          onClick={onBack}
          className="flex items-center justify-center gap-2 px-4 py-2.5 border border-gray-700 rounded-lg text-sm text-gray-300 hover:bg-gray-800 transition-colors"
        >
          <ArrowLeft size={14} /> Back
        </button>
        <button
          onClick={onCancel}
          className="flex items-center justify-center gap-2 px-4 py-2.5 border border-red-900/60 text-red-300 rounded-lg text-sm hover:bg-red-950/40 transition-colors"
        >
          <X size={14} /> Cancel
        </button>
      </div>
    </div>
  );
}

function ConfirmStep({
  strategy, category, tags, mediaId, music, lut, decaption, onBack, onConfirm,
}: {
  strategy: Strategy; category: string; tags: string[];
  mediaId?: string | null; music?: string; lut?: string; decaption?: boolean;
  onBack: () => void; onConfirm: () => void;
}) {
  const strategyLabels: Record<Strategy, string> = {
    diverse: "Diverse pick (cross-category, cooldown)",
    best: "Best clip (highest hook score)",
    random: "Random clip",
  };

  return (
    <div className="space-y-5">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-3">
        <h3 className="text-sm font-medium text-gray-400 mb-4">Review your selection</h3>

        <Row label="Strategy" value={strategyLabels[strategy]} />
        {mediaId && <Row label="Clip" value={mediaId} />}
        {category && <Row label="Category" value={category} />}
        {tags.length > 0 && <Row label="Tags" value={tags.join(", ")} />}
        <Row label="Music" value={music ? music : "Auto mood-matched bed"} />
        <Row label="LUT" value={lut ? lut : "None (original look)"} />
        <Row label="Decaption" value={decaption ? "On" : "Off"} />

        <div className="pt-3 border-t border-gray-800 text-xs text-gray-500 space-y-1">
          <p>The pipeline will run: <span className="text-gray-300">resize → caption</span></p>
          <p>A preview post will be created and queued for approval.</p>
        </div>
      </div>

      <div className="flex gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-2 px-4 py-2 border border-gray-700 rounded-lg text-sm text-gray-300 hover:bg-gray-800 transition-colors"
        >
          <ArrowLeft size={14} /> Back
        </button>
        <button
          onClick={onConfirm}
          className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-semibold text-white transition-colors"
        >
          <Film size={15} /> Create Video
        </button>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-sm border-b border-gray-800/50 last:border-0">
      <span className="text-gray-500">{label}</span>
      <span className="text-white font-medium capitalize">{value}</span>
    </div>
  );
}

function RunningStep({ logs }: { logs: string[] }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 text-blue-400">
        <Loader2 size={20} className="animate-spin flex-shrink-0" />
        <div>
          <p className="text-sm font-semibold text-white">Pipeline running…</p>
          <p className="text-xs text-gray-500">This usually takes 30–120 seconds. You can navigate away — the task continues.</p>
        </div>
      </div>

      <div className="bg-gray-950 border border-gray-800 rounded-xl p-4 font-mono text-xs space-y-1.5 min-h-32 max-h-64 overflow-y-auto">
        {logs.map((line, i) => (
          <p
            key={i}
            className={
              line.includes("[DONE]") || line.includes("completion")
                ? "text-green-400"
                : line.includes("error") || line.includes("failed")
                ? "text-red-400"
                : "text-gray-400"
            }
          >
            <span className="text-gray-600 mr-2 select-none">{String(i + 1).padStart(2, "0")}</span>
            {line}
          </p>
        ))}
        {logs.length === 0 && <p className="text-gray-600">Waiting for pipeline events…</p>}
      </div>

      <p className="text-xs text-gray-600 text-center">
        Track progress in the <strong className="text-gray-400">⚡ Task Center</strong> in the header.
      </p>
    </div>
  );
}

function DoneStep({
  mediaId, onAnother, onPreview, onQueue,
}: {
  mediaId: string;
  onAnother: () => void;
  onPreview: () => void;
  onQueue: () => void;
}) {
  return (
    <div className="space-y-5">
      <div className="bg-green-950/30 border border-green-800/50 rounded-xl p-5 flex items-start gap-3">
        <CheckCircle2 size={20} className="text-green-400 flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-white">Video created successfully!</p>
          <p className="text-xs text-gray-400 mt-1">
            Your clip has been processed and queued as a preview post. Review it before it auto-publishes.
          </p>
          <code className="block text-xs text-gray-500 mt-2">{mediaId}</code>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <button
          onClick={onPreview}
          className="flex flex-col items-center gap-2 p-4 bg-gray-900 border border-gray-700 hover:border-blue-500 hover:bg-blue-500/5 rounded-xl text-sm font-medium text-gray-300 hover:text-white transition-all"
        >
          <Film size={18} className="text-blue-400" />
          Preview
        </button>
        <button
          onClick={onQueue}
          className="flex flex-col items-center gap-2 p-4 bg-gray-900 border border-gray-700 hover:border-purple-500 hover:bg-purple-500/5 rounded-xl text-sm font-medium text-gray-300 hover:text-white transition-all"
        >
          <CheckCircle2 size={18} className="text-purple-400" />
          View Queue
        </button>
        <button
          onClick={onAnother}
          className="flex flex-col items-center gap-2 p-4 bg-gray-900 border border-gray-700 hover:border-green-500 hover:bg-green-500/5 rounded-xl text-sm font-medium text-gray-300 hover:text-white transition-all"
        >
          <Sparkles size={18} className="text-green-400" />
          Create Another
        </button>
      </div>
    </div>
  );
}

function ErrorStep({ error, onRetry }: { error: string | null; onRetry: () => void }) {
  const navigate = useNavigate();
  const isNoMedia = error?.includes("No unposted clips");

  return (
    <div className="space-y-4">
      <div className="bg-red-950/30 border border-red-800/50 rounded-xl p-5 flex items-start gap-3">
        <AlertCircle size={20} className="text-red-400 flex-shrink-0 mt-0.5" />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-white">
            {isNoMedia ? "No content available" : "Pipeline failed"}
          </p>
          <p className="text-xs text-red-300 mt-1 font-mono break-words">{error ?? "Unknown error"}</p>
          {isNoMedia && (
            <div className="mt-3 text-xs text-gray-400 space-y-1">
              <p className="font-medium text-gray-300">To fix this:</p>
              <p>1. Download posts via <strong className="text-white">Downloads</strong></p>
              <p>2. Run <strong className="text-white">Pipeline → Index</strong> to register media</p>
              <p>3. Run <strong className="text-white">Pipeline → Classify</strong> to tag category</p>
            </div>
          )}
        </div>
      </div>
      <div className="flex gap-3">
        {isNoMedia && (
          <button
            onClick={() => navigate("/downloads")}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm text-white font-medium transition-colors"
          >
            Go to Downloads
          </button>
        )}
        <button
          onClick={onRetry}
          className="flex items-center gap-2 px-4 py-2 border border-gray-700 rounded-lg text-sm text-gray-300 hover:bg-gray-800 transition-colors"
        >
          <ArrowLeft size={14} /> Try again
        </button>
      </div>
    </div>
  );
}
