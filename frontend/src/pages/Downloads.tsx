import { useState, useCallback } from "react";
import { Download, RefreshCw, CheckCircle, AlertTriangle, Pause, Play, Globe, Upload, Clapperboard } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useApi } from "@/hooks/useApi";
import { useWs } from "@/hooks/useWs";
import { api } from "@/lib/api";
import { UploadPanel } from "@/components/UploadPanel";
import { GoogleImportPanel } from "@/components/GoogleImportPanel";
import { StockImportPanel } from "@/components/StockImportPanel";
import type { DownloadStatus, NewCheck, CategoryFunnel, StockLibrary } from "@/types/downloads";

const FUNNEL_STAGES = ["raw", "resized", "edited", "uploaded", "posted"] as const;
const FUNNEL_COLORS: Record<string, string> = {
  raw: "#374151", resized: "#3b82f6", edited: "#8b5cf6",
  uploaded: "#f59e0b", posted: "#10b981", error: "#ef4444",
};

const CARD_STYLE = {
  background: "linear-gradient(145deg, rgba(17,19,31,1) 0%, rgba(10,10,16,1) 100%)",
  border: "1px solid rgba(255,255,255,0.06)",
  boxShadow: "0 4px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)",
};

function StatusIcon({ synced, hasNew }: { synced: boolean; hasNew: boolean }) {
  if (hasNew) return <AlertTriangle size={14} className="text-amber-400" />;
  if (synced) return <CheckCircle size={14} className="text-emerald-500" />;
  return <Pause size={14} className="text-gray-600" />;
}

function FunnelBar({ row }: { row: CategoryFunnel }) {
  const total = row.total || 1;
  return (
    <div className="flex h-2 w-full rounded-full overflow-hidden gap-px">
      {FUNNEL_STAGES.map((s) => {
        const count = row[s] ?? 0;
        const pct = (count / total) * 100;
        if (pct === 0) return null;
        return <div key={s} title={`${s}: ${count}`} style={{ width: `${pct}%`, backgroundColor: FUNNEL_COLORS[s] }} className="shrink-0" />;
      })}
      {row.error > 0 && <div title={`error: ${row.error}`} style={{ width: `${(row.error / total) * 100}%`, backgroundColor: FUNNEL_COLORS.error }} className="shrink-0" />}
    </div>
  );
}

function CategoryFunnelTable({ data }: { data: CategoryFunnel[] }) {
  const [filter, setFilter] = useState("");
  const rows = data.filter((r) => !filter || r.category.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="space-y-4">
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter categories…"
        className="w-full max-w-xs rounded-xl px-3 py-2 text-sm text-gray-300 placeholder-gray-600 focus:outline-none transition-colors"
        style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/5">
              <th className="pb-3 text-left text-[11px] font-semibold tracking-widest uppercase text-gray-600">Category</th>
              <th className="pb-3 text-right text-[11px] font-semibold tracking-widest uppercase text-gray-600">Total</th>
              <th className="pb-3 text-right text-[11px] font-semibold tracking-widest uppercase text-gray-600">Posted</th>
              <th className="pb-3 text-right text-[11px] font-semibold tracking-widest uppercase text-gray-600">Errors</th>
              <th className="pb-3 text-[11px] font-semibold tracking-widest uppercase text-gray-600 w-40">Pipeline</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.category} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                <td className="py-2.5 font-medium text-gray-200">{r.category}</td>
                <td className="py-2.5 text-gray-500 text-right tabular-nums font-mono text-xs">{r.total}</td>
                <td className="py-2.5 text-emerald-500 text-right tabular-nums font-mono text-xs">{r.posted}</td>
                <td className="py-2.5 text-red-500 text-right tabular-nums font-mono text-xs">{r.error || 0}</td>
                <td className="py-2.5 pl-4 w-40"><FunnelBar row={r} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OrganizedList({ data }: { data: NonNullable<DownloadStatus["organized"]> }) {
  return (
    <div className="space-y-0.5">
      {data.map((c) => (
        <div key={c.category} className="w-full flex items-center gap-2 px-2 py-2 rounded-xl hover:bg-white/[0.03] transition-colors">
          <Globe size={13} className="text-blue-500 shrink-0" />
          <span className="flex-1 text-sm text-gray-300 font-medium">{c.category}</span>
          <span className="text-xs text-gray-600 tabular-nums font-mono">{c.video}v / {c.image}i</span>
          <span className="text-xs text-gray-700 ml-2 font-mono">{c.total_size_mb} MB</span>
        </div>
      ))}
    </div>
  );
}

/** Compact per-category imported-stock strip shown under the archive list in By Category. */
function StockByCategory({ library }: { library: StockLibrary | null }) {
  if (!library || library.total_clips === 0) return null;
  const fmt = (mb: number) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`);
  return (
    <div className="mt-6 pt-4 border-t border-white/[0.06]">
      <div className="flex items-center gap-2 mb-3">
        <Clapperboard size={13} className="text-indigo-400" />
        <span className="text-[11px] font-semibold tracking-widest uppercase text-gray-500">Stock footage</span>
        <span className="text-[11px] text-gray-700 tabular-nums font-mono ml-1">
          {library.total_clips} clip{library.total_clips === 1 ? "" : "s"} · {fmt(library.total_size_mb)}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {library.categories.map((g) => (
          <div
            key={g.category}
            className="flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs"
            style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}
          >
            <Globe size={12} className="text-blue-500 shrink-0" />
            <span className="text-gray-300 font-medium">{g.category}</span>
            <span className="text-gray-600 tabular-nums font-mono">{g.count}v</span>
            <span className="text-gray-700 tabular-nums font-mono">{fmt(g.total_size_mb)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const BTN_GHOST = "flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-xl cursor-pointer transition-all duration-200 disabled:opacity-40";

export function DownloadsPage() {
  const { data: status, refetch } = useApi<DownloadStatus>("/downloads/status");
  const { data: funnel, refetch: refetchFunnel } = useApi<CategoryFunnel[]>("/downloads/categories");
  const { data: stockLib, refetch: refetchStock } = useApi<StockLibrary>("/downloads/stock/library");
  const [newCheck, setNewCheck] = useState<NewCheck | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [checkingNew, setCheckingNew] = useState(false);
  const [activeTab, setActiveTab] = useState<"overview" | "funnel" | "organized" | "upload" | "google" | "stock">("overview");

  useWs("download_complete", useCallback(() => {
    setDownloading(null); refetch(); refetchFunnel(); refetchStock();
  }, [refetch, refetchFunnel, refetchStock]));

  const checkNew = useCallback(async () => {
    setCheckingNew(true);
    const result = await api.get<NewCheck>("/downloads/check-new");
    setNewCheck(result); setCheckingNew(false);
  }, []);

  const downloadPosts = useCallback(async () => {
    setDownloading("posts"); await api.post("/downloads/posts");
    setDownloading(null); refetch();
  }, [refetch]);

  const downloadHighlights = useCallback(async () => {
    setDownloading("highlights"); await api.post("/downloads/highlights", {});
    setDownloading(null); refetch();
  }, [refetch]);

  const resumeDownload = useCallback(async () => {
    setDownloading("resume"); await api.post("/downloads/resume");
    setDownloading(null); refetch(); refetchFunnel();
  }, [refetch, refetchFunnel]);

  const postsStats = status?.posts.files;
  const hlStats = status?.highlights.files;

  const statRow = (label: string, value: string | number, accent?: string) => (
    <div className="flex justify-between items-center py-2 border-b border-white/[0.04]">
      <span className="text-xs text-gray-500">{label}</span>
      <span className={`text-sm font-medium tabular-nums font-mono ${accent || "text-gray-300"}`}>{value}</span>
    </div>
  );

  return (
    <div className="space-y-5 px-1">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold tracking-tight">Downloads</h2>
          <span className="text-xs text-gray-600 font-medium tracking-widest uppercase mt-0.5">Instagram Sync</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={checkNew} disabled={checkingNew}
            className={BTN_GHOST}
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#9ca3af" }}>
            <RefreshCw size={13} className={checkingNew ? "animate-spin" : ""} />
            Check New
          </button>
          <button onClick={resumeDownload} disabled={!!downloading}
            className={BTN_GHOST}
            style={{ background: "rgba(59,130,246,0.15)", border: "1px solid rgba(59,130,246,0.3)", color: "#93c5fd" }}>
            {downloading === "resume" ? <RefreshCw size={13} className="animate-spin" /> : <Play size={13} />}
            Resume
          </button>
        </div>
      </div>

      {/* Download banner */}
      <AnimatePresence>
        {downloading && downloading !== "resume" && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="flex items-center gap-3 p-4 rounded-2xl text-sm"
            style={{ background: "rgba(59,130,246,0.08)", border: "1px solid rgba(59,130,246,0.2)" }}
          >
            <RefreshCw size={14} className="animate-spin text-blue-400 shrink-0" />
            <span className="text-blue-300">Downloading {downloading}…</span>
            <div className="flex-1 h-1 rounded-full ml-2 overflow-hidden" style={{ background: "rgba(255,255,255,0.05)" }}>
              <motion.div className="h-full bg-blue-500 rounded-full" animate={{ x: ["-100%", "100%"] }} transition={{ repeat: Infinity, duration: 1.4, ease: "linear" }} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {newCheck && (
        <div
          className="p-4 rounded-2xl text-sm"
          style={newCheck.new_posts > 0
            ? { background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.2)", color: "#fcd34d" }
            : { background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.2)", color: "#6ee7b7" }}
        >
          {newCheck.error
            ? `Error: ${newCheck.error}`
            : newCheck.new_posts > 0
            ? `${newCheck.new_posts} new posts on Instagram (${newCheck.total_on_ig} total)`
            : "All posts synced"}
        </div>
      )}

      {/* Posts + Highlights cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {[
          { key: "posts", label: "Posts", icon: <StatusIcon synced={!newCheck?.new_posts} hasNew={!!newCheck && newCheck.new_posts > 0} />, stats: { Downloaded: status?.posts.downloaded || 0, Videos: postsStats?.video || 0, Images: postsStats?.image || 0, "Size (MB)": postsStats?.total_size_mb || 0 }, onDownload: downloadPosts },
          { key: "highlights", label: "Highlights", icon: <CheckCircle size={14} className="text-emerald-500" />, stats: { Downloaded: status?.highlights.downloaded || 0, Videos: hlStats?.video || 0, Images: hlStats?.image || 0, "Size (MB)": hlStats?.total_size_mb || 0 }, onDownload: downloadHighlights },
        ].map(({ key, label, icon, stats, onDownload }) => (
          <div key={key} className="rounded-2xl p-5" style={CARD_STYLE}>
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2.5">
                {icon}
                <span className="text-sm font-semibold text-white">{label}</span>
              </div>
              <button onClick={onDownload} disabled={!!downloading}
                className={BTN_GHOST + " text-xs"}
                style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#9ca3af" }}>
                {downloading === key ? <RefreshCw size={12} className="animate-spin" /> : <Download size={12} />}
                Download
              </button>
            </div>
            <div>
              {Object.entries(stats).map(([k, v]) => statRow(k, v))}
            </div>
          </div>
        ))}
      </div>

      {/* Uploads stat */}
      {status?.uploads && (status.uploads.video > 0 || status.uploads.total_size_mb > 0) && (
        <div className="rounded-2xl px-5 py-3 flex items-center gap-4 text-sm" style={CARD_STYLE}>
          <span className="flex items-center gap-2 text-gray-300 font-medium">
            <Upload size={14} className="text-indigo-400" /> Uploads
          </span>
          <span className="text-gray-500 tabular-nums font-mono text-xs">{status.uploads.video} videos</span>
          <span className="text-gray-700 tabular-nums font-mono text-xs">{status.uploads.total_size_mb} MB</span>
        </div>
      )}

      {/* Tabs panel */}
      <div className="rounded-2xl overflow-hidden" style={CARD_STYLE}>
        <div className="flex border-b border-white/5">
          {(["overview", "funnel", "organized", "upload", "google", "stock"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-5 py-3 text-xs font-semibold uppercase tracking-wider transition-colors cursor-pointer ${
                activeTab === tab ? "text-white border-b-2 border-indigo-500 bg-white/[0.03]" : "text-gray-600 hover:text-gray-400"
              }`}
            >
              {tab === "funnel" ? "Pipeline" : tab === "organized" ? "By Category" : tab === "upload" ? "Upload" : tab === "google" ? "Google" : tab === "stock" ? "Stock" : "Highlights"}
            </button>
          ))}
        </div>

        <div className="p-5">
          {activeTab === "overview" && (
            <>
              {(status?.highlights.breakdown || []).length > 0 ? (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/5">
                      <th className="pb-3 text-left text-[11px] font-semibold tracking-widest uppercase text-gray-600">Name</th>
                      <th className="pb-3 text-left text-[11px] font-semibold tracking-widest uppercase text-gray-600">Items</th>
                      <th className="pb-3 text-left text-[11px] font-semibold tracking-widest uppercase text-gray-600">Last Downloaded</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status!.highlights.breakdown.map((hl) => (
                      <tr key={hl.name} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                        <td className="py-2.5 text-gray-200 font-medium">{hl.name}</td>
                        <td className="py-2.5 text-gray-500 tabular-nums font-mono text-xs">{hl.count}</td>
                        <td className="py-2.5 text-gray-600 text-xs">
                          {hl.last_downloaded ? new Date(hl.last_downloaded).toLocaleString() : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-sm text-gray-600 py-4">No highlights downloaded yet.</p>
              )}
            </>
          )}

          {activeTab === "funnel" && (
            <>
              <div className="flex flex-wrap gap-3 mb-5">
                {FUNNEL_STAGES.map((s) => (
                  <div key={s} className="flex items-center gap-1.5 text-xs text-gray-500">
                    <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: FUNNEL_COLORS[s] }} />
                    {s}
                  </div>
                ))}
                <div className="flex items-center gap-1.5 text-xs text-gray-500">
                  <span className="w-2 h-2 rounded-sm bg-red-500" />
                  error
                </div>
              </div>
              {funnel && funnel.length > 0
                ? <CategoryFunnelTable data={funnel} />
                : <p className="text-sm text-gray-600">No data yet.</p>}
            </>
          )}

          {activeTab === "organized" && (
            <>
              {(status?.organized || []).length > 0
                ? <OrganizedList data={status!.organized} />
                : <p className="text-sm text-gray-600">No organized content on disk.</p>}
              <StockByCategory library={stockLib} />
            </>
          )}

          {activeTab === "upload" && (
            <UploadPanel refetch={refetch} refetchFunnel={refetchFunnel} />
          )}

          {activeTab === "google" && (
            <GoogleImportPanel refetch={refetch} refetchFunnel={refetchFunnel} />
          )}

          {activeTab === "stock" && (
            <StockImportPanel refetch={refetch} refetchFunnel={refetchFunnel} library={stockLib} refetchLibrary={refetchStock} />
          )}
        </div>
      </div>
    </div>
  );
}
