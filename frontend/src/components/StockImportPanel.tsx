import { useState, useCallback, useEffect } from "react";
import {
  Clapperboard, Search, Loader2, CheckCircle, AlertTriangle, Download as DownloadIcon,
  ChevronDown, ChevronRight, Globe, Film, HardDrive, Trash2,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { useSettings } from "@/lib/settings";
import { CategoryTagsPicker } from "@/components/CategoryTagsPicker";
import type {
  StockStatus, StockCandidate, StockSearchResponse, ImportResponse,
  StockLibrary, StockCategoryGroup, StockClip,
} from "@/types/downloads";

const SELECT_STYLE = {
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
} as const;

type Provider = "pexels" | "pixabay" | "both";

function fmtDur(s?: number | null): string {
  if (!s) return "";
  const sec = Math.round(s);
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

function fmtSize(mb?: number | null): string {
  if (!mb) return "—";
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
}

/** One imported stock clip row: provider · dims · duration · size · tags + delete. */
function ClipRow({ clip, onDeleted }: { clip: StockClip; onDeleted: () => void }) {
  const [deleting, setDeleting] = useState(false);
  const dims = clip.width && clip.height ? `${clip.width}×${clip.height}` : "";
  const tags = [clip.category, ...(clip.tags ?? [])].filter(Boolean).join(" · ");

  const del = async () => {
    setDeleting(true);
    try {
      await api.delete(`/downloads/stock/${clip.id}`);
      onDeleted();  // parent refetches — this row disappears from the library
    } catch {
      setDeleting(false);  // keep the row visible on failure
    }
  };

  return (
    <div className="flex items-center gap-2 py-1.5 text-xs text-gray-500">
      <Film size={12} className="text-indigo-400 shrink-0" />
      <span className="capitalize text-gray-400 w-14 shrink-0">{clip.provider}</span>
      <span className="flex-1 truncate">{tags || <span className="text-gray-700">untagged</span>}</span>
      <span className="tabular-nums font-mono text-[10px] text-gray-600 w-20 text-right shrink-0">{dims}</span>
      <span className="tabular-nums font-mono text-[10px] text-gray-600 w-10 text-right shrink-0">{fmtDur(clip.duration_s)}</span>
      <span className="tabular-nums font-mono text-[10px] text-gray-500 w-16 text-right shrink-0">{fmtSize(clip.size_mb)}</span>
      <button
        onClick={del} disabled={deleting}
        className="p-1 rounded-md shrink-0 cursor-pointer transition-colors hover:bg-red-500/10 disabled:opacity-40"
        title="Delete this clip from storage + database"
      >
        {deleting ? <Loader2 size={12} className="animate-spin text-gray-500" /> : <Trash2 size={12} className="text-gray-600 hover:text-red-400" />}
      </button>
    </div>
  );
}

/** Collapsible per-category group of imported stock clips. */
function CategoryGroup({ group, onDeleted }: { group: StockCategoryGroup; onDeleted: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-2 py-2 rounded-xl hover:bg-white/[0.03] text-left cursor-pointer transition-colors"
      >
        {open ? <ChevronDown size={13} className="text-gray-600 shrink-0" /> : <ChevronRight size={13} className="text-gray-600 shrink-0" />}
        <Globe size={13} className="text-blue-500 shrink-0" />
        <span className="flex-1 text-sm text-gray-300 font-medium capitalize">{group.category}</span>
        <span className="text-xs text-gray-600 tabular-nums font-mono">{group.count} clip{group.count === 1 ? "" : "s"}</span>
        <span className="text-xs text-gray-700 ml-2 font-mono">{fmtSize(group.total_size_mb)}</span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="ml-7 border-l border-white/[0.06] pl-3 overflow-hidden"
          >
            {group.clips.map((clip) => <ClipRow key={clip.id} clip={clip} onDeleted={onDeleted} />)}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Imported-stock library summary: totals + per-category breakdown of imports. */
function LibrarySummary({ library, onDeleted }: { library: StockLibrary; onDeleted: () => void }) {
  if (library.total_clips === 0) {
    return (
      <div className="rounded-xl px-3 py-2.5 text-xs text-gray-600" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}>
        No stock footage imported yet — search below and import clips.
      </div>
    );
  }
  return (
    <div className="rounded-xl p-3 space-y-1" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}>
      <div className="flex items-center gap-4 px-2 pb-2 mb-1 border-b border-white/[0.06]">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-gray-300">
          <Clapperboard size={13} className="text-indigo-400" /> Stock library
        </span>
        <span className="flex items-center gap-1.5 text-xs text-gray-500 tabular-nums font-mono">
          <Film size={12} /> {library.total_clips} clip{library.total_clips === 1 ? "" : "s"}
        </span>
        <span className="flex items-center gap-1.5 text-xs text-gray-500 tabular-nums font-mono">
          <HardDrive size={12} /> {fmtSize(library.total_size_mb)}
        </span>
        <span className="ml-auto text-[11px] text-gray-700 tabular-nums font-mono">{library.categories.length} categor{library.categories.length === 1 ? "y" : "ies"}</span>
      </div>
      {library.categories.map((g) => <CategoryGroup key={g.category} group={g} onDeleted={onDeleted} />)}
    </div>
  );
}

export function StockImportPanel({
  refetch, refetchFunnel, library, refetchLibrary,
}: {
  refetch: () => void;
  refetchFunnel: () => void;
  library: StockLibrary | null;
  refetchLibrary: () => void;
}) {
  const { data: status, loading } = useApi<StockStatus>("/downloads/stock/status");
  const { data: settings } = useSettings();
  const stockDefaults = (settings?.settings?.stock ?? {}) as { source?: Provider };

  const [meta, setMeta] = useState<{ category: string; tags: string[] }>({ category: "", tags: [] });
  const [query, setQuery] = useState("");
  const [provider, setProvider] = useState<Provider>("pexels");
  const [results, setResults] = useState<StockCandidate[]>([]);
  const [searching, setSearching] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, "importing" | "done" | "error">>({});
  const [rowErr, setRowErr] = useState<Record<string, string>>({});

  useEffect(() => {
    if (stockDefaults.source) setProvider(stockDefaults.source);
  }, [stockDefaults.source]);

  const tagged = !!meta.category.trim();
  const importedKeys = new Set(library?.imported_keys ?? []);
  const onDone = useCallback(() => { refetch(); refetchFunnel(); refetchLibrary(); }, [refetch, refetchFunnel, refetchLibrary]);

  const search = useCallback(async () => {
    if (!tagged) return;
    setSearching(true); setErr(null);
    const params = new URLSearchParams({ category: meta.category, provider });
    meta.tags.forEach((t) => params.append("tags", t));
    if (query.trim()) params.set("query", query.trim());
    try {
      const r = await api.get<StockSearchResponse>(`/downloads/stock/search?${params.toString()}`);
      setResults(r.results ?? []);
      setBusy({}); setRowErr({});
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Stock search failed");
    } finally {
      setSearching(false);
    }
  }, [tagged, meta, provider, query]);

  const importClip = useCallback(async (c: StockCandidate) => {
    if (!tagged) return;
    setBusy((b) => ({ ...b, [c.id]: "importing" }));
    try {
      const r = await api.post<ImportResponse>("/downloads/stock/import", {
        id: c.id, provider: c.provider, category: meta.category, tags: meta.tags.length ? meta.tags : undefined,
      });
      const row = r.results?.[0];
      const ok = row?.ok || row?.duplicate;  // duplicate = already have it → treat as done
      setBusy((b) => ({ ...b, [c.id]: ok ? "done" : "error" }));
      if (!ok) setRowErr((e) => ({ ...e, [c.id]: row?.error ?? "failed" }));
      else onDone();
    } catch (e) {
      setBusy((b) => ({ ...b, [c.id]: "error" }));
      setRowErr((er) => ({ ...er, [c.id]: e instanceof Error ? e.message : "failed" }));
    }
  }, [meta, tagged, onDone]);

  if (loading) {
    return <p className="text-sm text-gray-600 py-4 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Checking stock provider connection…</p>;
  }
  if (!status?.configured) {
    return (
      <div className="p-4 rounded-xl text-sm space-y-2" style={{ background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.2)" }}>
        <div className="flex items-center gap-2 text-amber-400 font-medium"><AlertTriangle size={15} /> Stock footage not connected</div>
        <p className="text-xs text-gray-400 leading-relaxed">
          Set <code className="text-gray-300">PEXELS_API_KEY</code> and/or <code className="text-gray-300">PIXABAY_API_KEY</code> in
          the server <code className="text-gray-300">.env</code>, then enable <code className="text-gray-300">stock.enabled</code> in Settings.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {library && <LibrarySummary library={library} onDeleted={onDone} />}

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl px-3 py-2.5" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}>
        <CategoryTagsPicker
          category={meta.category}
          tags={meta.tags}
          onCategoryChange={(category) => setMeta((m) => ({ ...m, category }))}
          onTagsChange={(tags) => setMeta((m) => ({ ...m, tags }))}
          variant="compact"
        />
        <span className="text-[11px] text-gray-600">{tagged ? "Applied to imports" : "Set a category to search + import"}</span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 flex-1 min-w-[200px] rounded-lg px-3 py-2" style={SELECT_STYLE}>
          <Search size={14} className="text-gray-500" />
          <input
            value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void search(); }}
            placeholder="Query override (blank = auto by category)…"
            className="flex-1 bg-transparent text-xs text-gray-300 placeholder-gray-600 focus:outline-none"
          />
        </div>
        <select
          value={provider} onChange={(e) => setProvider(e.target.value as Provider)}
          className="rounded-lg px-2.5 py-2 text-xs text-gray-300 focus:outline-none cursor-pointer" style={SELECT_STYLE}
        >
          <option value="pexels">Pexels</option>
          <option value="pixabay">Pixabay</option>
          <option value="both">Both</option>
        </select>
        <button
          onClick={() => void search()}
          disabled={!tagged || searching}
          className="flex items-center gap-2 px-4 py-2 text-xs font-medium rounded-xl cursor-pointer transition-all disabled:opacity-40"
          style={{ background: "rgba(99,102,241,0.18)", border: "1px solid rgba(99,102,241,0.35)", color: "#c7d2fe" }}
        >
          {searching ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
          Search
        </button>
      </div>

      {err && (
        <div className="flex items-center gap-2 p-3 rounded-xl text-xs" style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#fca5a5" }}>
          <AlertTriangle size={13} /> {err}
        </div>
      )}

      {results.length === 0 ? (
        <p className="text-sm text-gray-600 py-4">{searching ? "Searching…" : "No results yet — run a search."}</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {results.map((c) => {
            const st = busy[c.id];
            const already = importedKeys.has(`${c.provider}:${c.id}`);
            const imported = already || st === "done";
            return (
              <div key={`${c.provider}:${c.id}`} className="flex items-center gap-2.5 rounded-xl p-2.5" style={{ background: "rgba(255,255,255,0.02)", border: `1px solid ${imported ? "rgba(16,185,129,0.25)" : "rgba(255,255,255,0.06)"}` }}>
                <div className="w-14 h-14 rounded-lg overflow-hidden shrink-0 flex items-center justify-center" style={{ background: "rgba(255,255,255,0.04)" }}>
                  {c.thumbnail_url ? <img src={c.thumbnail_url} alt="" className="w-full h-full object-cover" referrerPolicy="no-referrer" /> : <Clapperboard size={16} className="text-gray-600" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-gray-200 truncate capitalize">{c.provider}</span>
                    {imported && (
                      <span className="flex items-center gap-0.5 text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded" style={{ background: "rgba(16,185,129,0.15)", color: "#6ee7b7" }}>
                        <CheckCircle size={9} /> In library
                      </span>
                    )}
                  </div>
                  <div className="text-[10px] text-gray-600 font-mono">{c.width}×{c.height}{c.duration_s ? ` · ${fmtDur(c.duration_s)}` : ""}</div>
                  {st === "error" && <div className="text-[10px] text-red-400 truncate" title={rowErr[c.id]}>{rowErr[c.id]}</div>}
                </div>
                <button
                  onClick={() => void importClip(c)}
                  disabled={!tagged || imported || st === "importing"}
                  className="p-1.5 rounded-lg cursor-pointer transition-all disabled:opacity-40"
                  style={{ background: "rgba(99,102,241,0.15)", border: "1px solid rgba(99,102,241,0.3)", color: "#c7d2fe" }}
                  title={imported ? "Already in library" : tagged ? "Import to Library" : "Set a category first"}
                >
                  {st === "importing" ? <Loader2 size={13} className="animate-spin" /> : imported ? <CheckCircle size={13} className="text-emerald-400" /> : <DownloadIcon size={13} />}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
