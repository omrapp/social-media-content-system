/**
 * Editor container hook — all state for /editor/:mediaId.
 *
 * Mirrors the page/container-hook split used by usePreview.ts: Editor.tsx stays
 * presentational, everything stateful lives here.
 *
 * Owns: EDL load/hydrate, proxy generation + WS progress, debounced autosave,
 * dirty tracking, an in-memory undo/redo ring, and export dispatch + WS
 * progress.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { useWs } from "@/hooks/useWs";
import { useSettings } from "@/lib/settings";
import {
  MAX_CUT_S,
  MAX_TOTAL_S,
  MIN_CUT_S,
  cutDuration,
  reelDuration,
  type Cut,
  type EDL,
  type ImageLayer,
  type Reel,
  type TextLayer,
  type EditorDocResponse,
  type EditorVersionDocResponse,
  type ExportStartResponse,
  type ProxyMap,
  type ProxyStartResponse,
} from "@/types/editor";

const UNDO_LIMIT = 50;

export type ExportPhase = "idle" | "running" | "done" | "error";

function cloneEDL(edl: EDL): EDL {
  return structuredClone(edl);
}

/** Stable id for a newly split/duplicated cut. */
function newCutId(): string {
  return `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

export function useEditor(mediaId: string | undefined) {
  const path = mediaId ? `/editor/${mediaId}` : null;
  const { data: doc, loading, error, refetch } = useApi<EditorDocResponse>(path);
  const { data: settingsData } = useSettings();
  const editorCfg = (settingsData?.settings?.editor ?? {}) as Record<string, unknown>;

  const [edl, setEdl] = useState<EDL | null>(null);
  const [dirty, setDirty] = useState(false);
  const [savedVersion, setSavedVersion] = useState<number>(0);
  const [selectedCutId, setSelectedCutId] = useState<string | null>(null);
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>(null);

  const [proxies, setProxies] = useState<ProxyMap>({});
  const [proxyProgress, setProxyProgress] = useState<{ done: number; total: number } | null>(null);

  const [exportPhase, setExportPhase] = useState<ExportPhase>("idle");
  const [exportMessage, setExportMessage] = useState<string>("");

  // Undo/redo. In-memory only and deliberately so: persisted history is the
  // versions list on the server, which is a different affordance.
  const undoStack = useRef<EDL[]>([]);
  const redoStack = useRef<EDL[]>([]);
  const [historyTick, setHistoryTick] = useState(0);

  // ── load ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!doc?.edl) return;
    setEdl(cloneEDL(doc.edl));
    setSavedVersion(doc.version ?? 0);
    setDirty(false);
    undoStack.current = [];
    redoStack.current = [];
    setHistoryTick((t) => t + 1);
  }, [doc]);

  /** Every mutation funnels through here so undo and dirty tracking cannot be
   *  bypassed by a caller that forgets to record history. */
  const commit = useCallback((mutate: (draft: EDL) => void) => {
    setEdl((prev) => {
      if (!prev) return prev;
      undoStack.current.push(cloneEDL(prev));
      if (undoStack.current.length > UNDO_LIMIT) undoStack.current.shift();
      redoStack.current = [];
      const next = cloneEDL(prev);
      mutate(next);
      return next;
    });
    setDirty(true);
    setHistoryTick((t) => t + 1);
  }, []);

  const undo = useCallback(() => {
    setEdl((prev) => {
      const past = undoStack.current.pop();
      if (!past || !prev) return prev;
      redoStack.current.push(cloneEDL(prev));
      return past;
    });
    setDirty(true);
    setHistoryTick((t) => t + 1);
  }, []);

  const redo = useCallback(() => {
    setEdl((prev) => {
      const next = redoStack.current.pop();
      if (!next || !prev) return prev;
      undoStack.current.push(cloneEDL(prev));
      return next;
    });
    setDirty(true);
    setHistoryTick((t) => t + 1);
  }, []);

  const canUndo = undoStack.current.length > 0;
  const canRedo = redoStack.current.length > 0;
  void historyTick; // re-render trigger for canUndo/canRedo

  // ── cut operations (clamps mirror editor_edl.py so the UI can't build a doc
  //    the backend will reject) ───────────────────────────────────────────────
  const maxCuts = Number(editorCfg.max_cuts ?? 40);

  const reorderCuts = useCallback((from: number, to: number) => {
    commit((d) => {
      const [moved] = d.cuts.splice(from, 1);
      if (moved) d.cuts.splice(to, 0, moved);
    });
  }, [commit]);

  const trimCut = useCallback((id: string, inS: number, outS: number) => {
    commit((d) => {
      const c = d.cuts.find((x) => x.id === id);
      if (!c) return;
      const lo = Math.max(0, inS);
      const hi = Math.max(lo + MIN_CUT_S, outS);
      c.in_s = lo;
      c.out_s = Math.min(hi, lo + MAX_CUT_S);
    });
  }, [commit]);

  const splitCut = useCallback((id: string, atS: number) => {
    commit((d) => {
      const i = d.cuts.findIndex((x) => x.id === id);
      if (i < 0) return;
      const c = d.cuts[i];
      const local = atS - c.in_s;
      // Both halves must survive the backend's minimum, else the split is a no-op.
      if (local < MIN_CUT_S || cutDuration(c) - local < MIN_CUT_S) return;
      if (d.cuts.length >= maxCuts) return;
      const right: Cut = { ...structuredClone(c), id: newCutId(), in_s: atS };
      c.out_s = atS;
      d.cuts.splice(i + 1, 0, right);
    });
  }, [commit, maxCuts]);

  const deleteCut = useCallback((id: string) => {
    commit((d) => {
      if (d.cuts.length <= 2) return; // a merge needs >= 2 segments
      d.cuts = d.cuts.filter((x) => x.id !== id);
    });
  }, [commit]);

  const duplicateCut = useCallback((id: string) => {
    commit((d) => {
      const i = d.cuts.findIndex((x) => x.id === id);
      if (i < 0 || d.cuts.length >= maxCuts) return;
      d.cuts.splice(i + 1, 0, { ...structuredClone(d.cuts[i]), id: newCutId() });
    });
  }, [commit, maxCuts]);

  const totalDuration = useMemo(() => (edl ? reelDuration(edl.cuts) : 0), [edl]);
  const overLength = totalDuration > MAX_TOTAL_S;

  // ── reel-level look + audio (Phase 4) ─────────────────────────────────────
  // Shallow patch on purpose: nested specs (grade/eq/music) are replaced whole
  // by the panels, which keeps every write one undo step.
  const updateReel = useCallback((patch: Partial<Reel>) => {
    commit((d) => { d.reel = { ...d.reel, ...patch }; });
  }, [commit]);

  // ── text layers (Phase 3) ─────────────────────────────────────────────────
  const maxTextLayers = Number(editorCfg.max_text_layers ?? 20);

  const addTextLayer = useCallback(() => {
    const id = `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    commit((d) => {
      if (d.layers.text.length >= maxTextLayers) return;
      d.layers.text.push({
        id,
        // Non-empty by default: compile() rejects an empty layer, so an
        // "add" that produced one would break export until the user typed.
        content: "New text",
        font: "",
        size: 64,
        color: "#ffffff",
        x: 0.5,
        y: 0.5,
        anchor: "center",
        start_s: 0,
        // 0 = "until the end of the reel" on both sides of the contract.
        end_s: 0,
        animation: "fade",
      });
    });
    setSelectedLayerId(id);
    return id;
  }, [commit, maxTextLayers]);

  const updateTextLayer = useCallback((id: string, patch: Partial<TextLayer>) => {
    commit((d) => {
      const i = d.layers.text.findIndex((l) => l.id === id);
      if (i >= 0) d.layers.text[i] = { ...d.layers.text[i], ...patch };
    });
  }, [commit]);

  const deleteTextLayer = useCallback((id: string) => {
    commit((d) => { d.layers.text = d.layers.text.filter((l) => l.id !== id); });
    setSelectedLayerId((cur) => (cur === id ? null : cur));
  }, [commit]);

  // ── image / sticker layers (Phase 5) ──────────────────────────────────────
  // Deliberately reuses `selectedLayerId` rather than adding a second selection
  // slot: the inspector tab already disambiguates which lane an id belongs to,
  // and both panels resolve their layer with a find() that yields null for an
  // id from the other lane, so a cross-lane id is inert rather than wrong.
  const maxImageLayers = Number(editorCfg.max_image_layers ?? 10);

  const addImageLayer = useCallback((asset: string) => {
    const id = `i${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    commit((d) => {
      if (d.layers.image.length >= maxImageLayers) return;
      // z is "one above whatever is already there" so a newly added sticker is
      // visible instead of landing underneath an existing one.
      const topZ = d.layers.image.reduce((m, l) => Math.max(m, l.z), -1);
      d.layers.image.push({
        id,
        asset,
        x: 0.5,
        y: 0.5,
        // w defaults to 0.3 (30% of the frame) rather than null: null means
        // "native pixel size", and a 2000px sticker at native size on a 1080px
        // canvas would fill — and overflow — the whole reel on add.
        w: 0.3,
        h: null,
        start_s: 0,
        // 0 = "until the end of the reel", same convention as text layers.
        end_s: 0,
        opacity: 1,
        z: Math.min(99, topZ + 1),
      });
    });
    setSelectedLayerId(id);
    return id;
  }, [commit, maxImageLayers]);

  const updateImageLayer = useCallback((id: string, patch: Partial<ImageLayer>) => {
    commit((d) => {
      const i = d.layers.image.findIndex((l) => l.id === id);
      if (i >= 0) d.layers.image[i] = { ...d.layers.image[i], ...patch };
    });
  }, [commit]);

  const deleteImageLayer = useCallback((id: string) => {
    commit((d) => { d.layers.image = d.layers.image.filter((l) => l.id !== id); });
    setSelectedLayerId((cur) => (cur === id ? null : cur));
  }, [commit]);

  // ── version history (Phase 5) ─────────────────────────────────────────────
  /** Swap the working doc for `next`, as ONE undo step.
   *
   *  Both loading a version and reverting to the original go through commit(),
   *  so they leave `dirty` true and are ⌘Z-able. That is the point: neither is
   *  destructive — history is only ever appended to, and the user has to save
   *  to turn a load/revert into a new version. */
  const replaceEdl = useCallback((next: EDL) => {
    commit((d) => { Object.assign(d, cloneEDL(next)); });
    // Ids from the replaced doc no longer exist; clear rather than leave the
    // inspector pointing at a cut/layer that is gone.
    setSelectedCutId(null);
    setSelectedLayerId(null);
  }, [commit]);

  const loadVersion = useCallback(async (version: number) => {
    if (!mediaId) return;
    try {
      const res = await api.get<EditorVersionDocResponse>(`/editor/${mediaId}/versions/${version}`);
      replaceEdl(res.edl);
      toast.success(`Loaded v${version} — save to keep it`);
    } catch (e) {
      toast.error(`Could not load v${version}: ${(e as Error).message}`);
    }
  }, [mediaId, replaceEdl]);

  const revertToOriginal = useCallback(async () => {
    if (!mediaId) return;
    try {
      // ?fresh=1 re-hydrates from the media row, ignoring every saved version.
      const res = await api.get<EditorDocResponse>(`/editor/${mediaId}?fresh=1`);
      replaceEdl(res.edl);
      toast.success("Reverted to the rendered reel — save to keep it");
    } catch (e) {
      toast.error(`Revert failed: ${(e as Error).message}`);
    }
  }, [mediaId, replaceEdl]);

  // ── save / autosave ───────────────────────────────────────────────────────
  const save = useCallback(async (label?: string) => {
    if (!mediaId || !edl) return;
    try {
      const res = await api.put<{ version: number }>(`/editor/${mediaId}`, { edl, label: label ?? null });
      setSavedVersion(res.version);
      setDirty(false);
    } catch (e) {
      toast.error(`Save failed: ${(e as Error).message}`);
    }
  }, [mediaId, edl]);

  const autosaveSeconds = Number(editorCfg.autosave_seconds ?? 15);
  useEffect(() => {
    if (!dirty || !edl || overLength) return;
    const t = setTimeout(() => { void save(); }, Math.max(2, autosaveSeconds) * 1000);
    return () => clearTimeout(t);
  }, [dirty, edl, overLength, autosaveSeconds, save]);

  // ── proxies ───────────────────────────────────────────────────────────────
  // The EDL is sent along: proxies are cut to each segment's in/out, so
  // re-cutting after a trim needs the edited doc, not the server's hydrate().
  const edlRef = useRef<EDL | null>(null);
  edlRef.current = edl;

  const buildProxies = useCallback(async () => {
    if (!mediaId) return;
    try {
      const res = await api.post<ProxyStartResponse>(
        `/editor/${mediaId}/proxies`,
        edlRef.current ? { edl: edlRef.current } : {},
      );
      if (res.status === "no_cuts") return;
      setProxyProgress({ done: 0, total: res.cuts ?? 0 });
    } catch (e) {
      toast.error(`Proxy generation failed: ${(e as Error).message}`);
    }
  }, [mediaId]);

  useWs("editor_proxy_progress", useCallback((d: Record<string, unknown>) => {
    if (d.media_id !== mediaId) return;
    setProxyProgress({ done: Number(d.done ?? 0), total: Number(d.total ?? 0) });
  }, [mediaId]));

  useWs("editor_proxy_complete", useCallback((d: Record<string, unknown>) => {
    if (d.media_id !== mediaId) return;
    setProxies((prev) => ({ ...prev, ...((d.proxies as ProxyMap) ?? {}) }));
    setProxyProgress(null);
  }, [mediaId]));

  // Kick off proxy generation once the doc is loaded — the player has nothing
  // to show until at least one proxy exists.
  const proxiesRequested = useRef(false);
  useEffect(() => {
    if (!edl || proxiesRequested.current) return;
    proxiesRequested.current = true;
    void buildProxies();
  }, [edl, buildProxies]);

  // ── export ────────────────────────────────────────────────────────────────
  const startExport = useCallback(async () => {
    if (!mediaId || !edl) return;
    if (overLength) {
      toast.error(`Reel is ${totalDuration.toFixed(1)}s — over the ${MAX_TOTAL_S}s limit`);
      return;
    }
    if (dirty) await save();
    setExportPhase("running");
    setExportMessage("Queued…");
    try {
      // POST export takes the doc itself — it is compiled synchronously so an
      // invalid edit 400s here instead of failing minutes later in a worker.
      await api.post<ExportStartResponse>(`/editor/${mediaId}/export`, { edl });
    } catch (e) {
      setExportPhase("error");
      setExportMessage((e as Error).message);
    }
  }, [mediaId, edl, dirty, overLength, totalDuration, save]);

  useWs("editor_export_progress", useCallback((d: Record<string, unknown>) => {
    if (d.media_id !== mediaId) return;
    setExportMessage(String(d.message ?? d.stage ?? "Rendering…"));
  }, [mediaId]));

  useWs("editor_export_complete", useCallback((d: Record<string, unknown>) => {
    if (d.media_id !== mediaId) return;
    setExportPhase("done");
    setExportMessage("Export complete");
    toast.success("Reel exported");
  }, [mediaId]));

  useWs("editor_export_failed", useCallback((d: Record<string, unknown>) => {
    if (d.media_id !== mediaId) return;
    setExportPhase("error");
    setExportMessage(String(d.error ?? "Export failed"));
    toast.error("Export failed");
  }, [mediaId]));

  return {
    // data
    edl, loading, error, refetch,
    approx: Boolean(doc?.approx),
    previewLut: Boolean(editorCfg.preview_lut ?? true),
    savedVersion, dirty,
    totalDuration, overLength,

    // selection
    selectedCutId, setSelectedCutId,
    selectedLayerId, setSelectedLayerId,

    // mutations
    commit, reorderCuts, trimCut, splitCut, deleteCut, duplicateCut,
    updateReel,
    addTextLayer, updateTextLayer, deleteTextLayer, maxTextLayers,
    addImageLayer, updateImageLayer, deleteImageLayer, maxImageLayers,
    undo, redo, canUndo, canRedo,

    // history
    loadVersion, revertToOriginal,

    // io
    save, proxies, proxyProgress, buildProxies,
    startExport, exportPhase, exportMessage,
  };
}
