import { useState, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Grid3X3, List, RefreshCw, Eye, Loader2, Scissors } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { MergeClipsPanel } from "@/components/preview/MergeClipsPanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { CategoryBadge } from "@/components/ui/CategoryBadge";
import type { Media } from "@/types/media";
import { MEDIA_STATUSES } from "@/constants/media";
import { staggerContainer, fadeUp } from "@/lib/motion";

const SORT_OPTIONS = [
  { value: "taken_at_desc", label: "Newest first" },
  { value: "taken_at_asc",  label: "Oldest first" },
];

function SkeletonCard() {
  return (
    <div
      className="rounded-2xl overflow-hidden animate-pulse"
      style={{ background: "rgba(17,19,31,0.8)", border: "1px solid rgba(255,255,255,0.05)" }}
    >
      <div className="aspect-[9/16]" style={{ background: "rgba(255,255,255,0.04)" }} />
      <div className="p-3 space-y-2">
        <div className="h-3 rounded-md w-3/4" style={{ background: "rgba(255,255,255,0.06)" }} />
        <div className="h-2.5 rounded-md w-1/2" style={{ background: "rgba(255,255,255,0.04)" }} />
      </div>
    </div>
  );
}

export function LibraryPage() {
  const navigate = useNavigate();
  const [view, setView] = useState<"grid" | "list">("grid");
  const [statusFilter, setStatusFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [tagsFilter, setTagsFilter] = useState("");
  const [sort, setSort] = useState("taken_at_desc");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [mergeOpen, setMergeOpen] = useState(false);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;

  const tagsList = tagsFilter.split(",").map((t) => t.trim()).filter(Boolean);

  useEffect(() => { setPage(1); }, [statusFilter, categoryFilter, tagsFilter, sort]);

  const { data: categoriesResp } = useApi<{ categories: string[] }>("/taxonomy/categories");
  const categories = categoriesResp?.categories;

  const params = new URLSearchParams();
  if (statusFilter !== "all") params.set("status", statusFilter);
  if (categoryFilter !== "all") params.set("category", categoryFilter);
  tagsList.forEach((t) => params.append("tags", t));
  params.set("sort", sort);
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String((page - 1) * PAGE_SIZE));

  const { data: media, loading, refetch } = useApi<Media[]>(`/media?${params}`);

  const q = search.toLowerCase();
  const filtered = (media || []).filter(
    (m) => !q || m.caption?.toLowerCase().includes(q) || (m.tags ?? []).join(", ").toLowerCase().includes(q)
  );

  const hasNextPage = (media || []).length === PAGE_SIZE;
  const hasPrevPage = page > 1;

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const [batchBusy, setBatchBusy] = useState(false);

  const runBatch = useCallback(async (fn: () => Promise<void>, successMsg: string) => {
    if (batchBusy) return;
    setBatchBusy(true);
    try {
      await fn();
      setSelected(new Set());
      refetch();
      toast.success(successMsg);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Batch operation failed");
    } finally {
      setBatchBusy(false);
    }
  }, [batchBusy, refetch]);

  const batchReprocess = useCallback(() =>
    runBatch(
      () => Promise.all([...selected].map((id) => api.post(`/media/${id}/reprocess`, { target_status: "raw" }))).then(() => {}),
      `${selected.size} item(s) reset to raw`
    ),
  [selected, runBatch]);

  const batchResetResized = useCallback(() =>
    runBatch(
      () => Promise.all([...selected].map((id) => api.post(`/media/${id}/reprocess`, { target_status: "resized" }))).then(() => {}),
      `${selected.size} item(s) reset to resized`
    ),
  [selected, runBatch]);

  const batchDelete = useCallback(() =>
    runBatch(
      () => Promise.all([...selected].map((id) => api.delete(`/media/${id}`))).then(() => {}),
      `${selected.size} item(s) deleted`
    ),
  [selected, runBatch]);

  const batchTag = useCallback((category: string) => {
    if (!category) return;
    void runBatch(
      () => Promise.all([...selected].map((id) => api.put(`/media/${id}`, { category }))).then(() => {}),
      `Tagged ${selected.size} item(s) as ${category}`
    );
  }, [selected, runBatch]);

  const showSkeleton = loading && !media;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold tracking-tight">Library</h2>
          <span className="text-xs text-gray-600 font-medium tracking-widest uppercase mt-0.5">Content</span>
        </div>
        <div className="flex items-center gap-2">
          <AnimatePresence>
            {selected.size > 0 && (
              <motion.div
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 10 }}
                transition={{ duration: 0.18 }}
                className="flex items-center gap-1.5"
              >
                <span className="text-xs text-gray-500 mr-1 flex items-center gap-1">
                  {batchBusy && <Loader2 size={11} className="animate-spin" />}
                  {selected.size} selected
                </span>
                <button onClick={batchReprocess} disabled={batchBusy} title="Reset to raw" className="px-2.5 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded-lg cursor-pointer transition-colors">Raw</button>
                <button onClick={batchResetResized} disabled={batchBusy} title="Reset to resized" className="px-2.5 py-1.5 text-xs bg-blue-700 hover:bg-blue-600 disabled:opacity-40 rounded-lg cursor-pointer transition-colors">Resized</button>
                {selected.size >= 2 && (
                  <button onClick={() => setMergeOpen(true)} disabled={batchBusy} title="Merge selected clips into one reel" className="px-2.5 py-1.5 text-xs bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40 rounded-lg cursor-pointer transition-colors flex items-center gap-1"><Scissors size={11} />Merge</button>
                )}
                <select
                  defaultValue=""
                  disabled={batchBusy}
                  onChange={(e) => { batchTag(e.target.value); e.target.value = ""; }}
                  className="px-2 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded-lg border-0 focus:outline-none cursor-pointer"
                >
                  <option value="" disabled>Set category…</option>
                  {(categories ?? []).map((c) => (
                    <option key={c} value={c}>{c.replace("_", " ")}</option>
                  ))}
                </select>
                <button onClick={batchDelete} disabled={batchBusy} title="Delete selected" className="px-2.5 py-1.5 text-xs bg-red-700 hover:bg-red-600 disabled:opacity-40 rounded-lg cursor-pointer transition-colors">Delete</button>
              </motion.div>
            )}
          </AnimatePresence>
          <button onClick={() => { setSelected(new Set()); setMergeOpen(true); }} title="Merge clips into one reel" className="p-2 hover:bg-gray-800 rounded-lg cursor-pointer transition-colors">
            <Scissors size={16} />
          </button>
          <button onClick={refetch} className="p-2 hover:bg-gray-800 rounded-lg cursor-pointer transition-colors">
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </button>
          <button onClick={() => setView("grid")} className={`p-2 rounded-lg cursor-pointer transition-colors ${view === "grid" ? "bg-gray-800" : "hover:bg-gray-800"}`}>
            <Grid3X3 size={16} />
          </button>
          <button onClick={() => setView("list")} className={`p-2 rounded-lg cursor-pointer transition-colors ${view === "list" ? "bg-gray-800" : "hover:bg-gray-800"}`}>
            <List size={16} />
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search captions, tags…"
            className="w-full pl-9 pr-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-gray-500 transition-colors"
          />
        </div>

        {[
          { value: statusFilter, onChange: setStatusFilter, options: [{ value: "all", label: "All statuses" }, { value: "uploaded,posted", label: "Created + Posted" }, ...MEDIA_STATUSES.filter((s) => s !== "all").map((s) => ({ value: s, label: s }))] },
          { value: categoryFilter, onChange: setCategoryFilter, options: [{ value: "all", label: "All categories" }, ...(categories || []).map((c) => ({ value: c, label: c.replace("_", " ") }))] },
          { value: sort, onChange: setSort, options: SORT_OPTIONS.map((o) => ({ value: o.value, label: o.label })) },
        ].map((sel, i) => (
          <select key={i} value={sel.value} onChange={(e) => sel.onChange(e.target.value)}
            className="rounded-xl px-3 py-2 text-xs text-gray-300 focus:outline-none cursor-pointer transition-colors"
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}>
            {sel.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        ))}

        <input
          value={tagsFilter}
          onChange={(e) => setTagsFilter(e.target.value)}
          placeholder="Filter tags (comma-separated)"
          className="rounded-xl px-3 py-2 text-xs text-gray-300 focus:outline-none transition-colors min-w-[180px]"
          style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
        />
      </div>

      {view === "grid" ? (
        showSkeleton ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {Array.from({ length: 10 }).map((_, i) => <SkeletonCard key={i} />)}
          </div>
        ) : (
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4"
          >
            {filtered.map((m) => (
              <motion.div
                key={m.id}
                variants={fadeUp}
                onClick={() => toggleSelect(m.id)}
                className={`rounded-2xl overflow-hidden cursor-pointer group transition-all duration-200 ${
                  selected.has(m.id) ? "" : ""
                }`}
          style={selected.has(m.id)
            ? { background: "rgba(17,19,31,1)", border: "1px solid rgba(99,102,241,0.5)", boxShadow: "0 0 20px rgba(99,102,241,0.12)" }
            : { background: "rgba(17,19,31,1)", border: "1px solid rgba(255,255,255,0.06)" }}
                whileHover={{ y: -2, transition: { duration: 0.18 } }}
              >
                <div className="aspect-[9/16] bg-gray-800 relative overflow-hidden">
                  {m.thumbnail_url
                    ? <img src={m.thumbnail_url} alt="" className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-300" onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                    : <div className="w-full h-full flex items-center justify-center text-gray-600 text-xs">No thumb</div>
                  }
                  <div className="absolute top-2 left-2"><StatusBadge status={m.status} /></div>
                  {m.episode_number && (
                    <div className="absolute top-2 right-2 bg-black/70 text-xs text-white px-1.5 py-0.5 rounded">
                      {m.episode_number}/{m.episode_total}
                    </div>
                  )}
                  <button
                    onClick={(e) => { e.stopPropagation(); navigate(`/preview/${m.id}`); }}
                    className="absolute bottom-2 right-2 p-1.5 bg-black/70 hover:bg-black rounded-lg opacity-0 group-hover:opacity-100 transition-all duration-200 cursor-pointer"
                    title="Preview"
                  >
                    <Eye size={14} className="text-white" />
                  </button>
                </div>
                <div className="p-3 space-y-1">
                  <p className="text-sm truncate text-gray-200">{m.caption || m.id}</p>
                  <div className="flex items-center gap-2 flex-wrap">
                    {m.category && <CategoryBadge category={m.category} />}
                    {m.tags && m.tags.length > 0 && <span className="text-xs text-gray-500">{m.tags.join(", ")}</span>}
                    {m.series_arc_position && (
                      <span className="text-xs text-purple-400/70">{m.series_arc_position}</span>
                    )}
                  </div>
                </div>
              </motion.div>
            ))}
          </motion.div>
        )
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-800">
              <th className="pb-2 font-medium">ID</th>
              <th className="pb-2 font-medium">Caption</th>
              <th className="pb-2 font-medium">Status</th>
              <th className="pb-2 font-medium">Category</th>
              <th className="pb-2 font-medium">Tags</th>
              <th className="pb-2 font-medium">Episode</th>
              <th className="pb-2 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((m) => (
              <tr key={m.id} onClick={() => toggleSelect(m.id)} className={`border-b border-gray-800/50 cursor-pointer transition-colors ${selected.has(m.id) ? "bg-indigo-950/30" : "hover:bg-gray-900"}`}>
                <td className="py-2 font-mono text-xs text-gray-400">{m.id.slice(0, 8)}</td>
                <td className="py-2 max-w-xs truncate">{m.caption || "—"}</td>
                <td className="py-2"><StatusBadge status={m.status} /></td>
                <td className="py-2">{m.category && <CategoryBadge category={m.category} />}</td>
                <td className="py-2 text-gray-400">{m.tags && m.tags.length > 0 ? m.tags.join(", ") : "—"}</td>
                <td className="py-2 text-gray-400 text-xs">
                  {m.episode_number ? `${m.episode_number}/${m.episode_total} · ${m.series_arc_position}` : "—"}
                </td>
                <td className="py-2">
                  <button
                    onClick={(e) => { e.stopPropagation(); navigate(`/preview/${m.id}`); }}
                    className="p-1.5 hover:bg-gray-800 rounded text-gray-500 hover:text-white cursor-pointer transition-colors"
                    title="Preview"
                  >
                    <Eye size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!loading && filtered.length === 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex flex-col items-center justify-center py-20"
        >
          <p className="text-gray-500 text-sm">No media found</p>
          <p className="text-gray-700 text-xs mt-1">Try adjusting your filters</p>
        </motion.div>
      )}

      {mergeOpen && (
        <MergeClipsPanel
          initialIds={[...selected]}
          onClose={() => setMergeOpen(false)}
          onSubmitted={() => setSelected(new Set())}
        />
      )}

      {(hasPrevPage || hasNextPage) && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            onClick={() => setPage((p) => p - 1)}
            disabled={!hasPrevPage || loading}
            className="px-3 py-1.5 text-sm bg-gray-800 hover:bg-gray-700 disabled:opacity-40 rounded-lg cursor-pointer transition-colors"
          >
            ← Prev
          </button>
          <span className="text-sm text-gray-400">Page {page}</span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={!hasNextPage || loading}
            className="px-3 py-1.5 text-sm bg-gray-800 hover:bg-gray-700 disabled:opacity-40 rounded-lg cursor-pointer transition-colors"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
