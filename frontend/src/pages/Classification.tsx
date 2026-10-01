import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, TooltipProps,
} from "recharts";
import { useApi } from "@/hooks/useApi";
import { CATEGORY_CHART_COLORS } from "@/constants/colors";
import { staggerContainer, fadeUp } from "@/lib/motion";

// ─── Types ─────────────────────────────────────────────────────────────────
interface ProgressBlock { classified?: number; scored?: number; remaining: number; pct: number; }
interface ClassificationOverview {
  total_media: number; video_media: number;
  groq: ProgressBlock; vision: ProgressBlock;
  by_category: Record<string, number>; by_status: Record<string, number>;
}
interface CategoryNode { category: string; total: number; groq_classified: number; vision_scored: number; }
type SortKey = "category" | "total" | "groq_classified" | "vision_scored";

// ─── Animated counter ──────────────────────────────────────────────────────
function useCountUp(target: number, duration = 900) {
  const [count, setCount] = useState(0);
  const raf = useRef<number>(0);
  useEffect(() => {
    if (target === 0) { setCount(0); return; }
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - start) / duration, 1);
      setCount(Math.round((1 - Math.pow(1 - p, 3)) * target));
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, duration]);
  return count;
}

// ─── Stat card ─────────────────────────────────────────────────────────────
const CARD_CFG = [
  { glow: "rgba(99,102,241,0.18)", border: "rgba(99,102,241,0.25)", text: "#a5b4fc", bg: "rgba(99,102,241,0.06)" },
  { glow: "rgba(124,58,237,0.18)", border: "rgba(124,58,237,0.25)", text: "#c4b5fd", bg: "rgba(124,58,237,0.06)" },
  { glow: "rgba(16,185,129,0.18)", border: "rgba(16,185,129,0.25)", text: "#6ee7b7", bg: "rgba(16,185,129,0.06)" },
  { glow: "rgba(245,158,11,0.18)", border: "rgba(245,158,11,0.25)", text: "#fcd34d", bg: "rgba(245,158,11,0.06)" },
];

function AnimatedStatCard({ label, value, sub, index }: { label: string; value: number; sub?: string; index: number }) {
  const count = useCountUp(value);
  const cfg = CARD_CFG[index] ?? CARD_CFG[0];
  return (
    <motion.div
      variants={fadeUp}
      className="relative rounded-2xl p-5 overflow-hidden"
      style={{
        background: `linear-gradient(135deg, ${cfg.bg} 0%, rgba(0,0,0,0) 100%)`,
        border: `1px solid ${cfg.border}`,
        boxShadow: `0 0 24px ${cfg.glow}, inset 0 1px 0 rgba(255,255,255,0.04)`,
      }}
    >
      <div className="absolute inset-0 opacity-30 pointer-events-none"
        style={{ background: `radial-gradient(ellipse at 80% 0%, ${cfg.glow} 0%, transparent 70%)` }} />
      <p className="text-xs font-medium tracking-widest uppercase text-gray-500">{label}</p>
      <p className="text-3xl font-bold mt-1.5 tabular-nums" style={{ color: cfg.text }}>{count.toLocaleString()}</p>
      {sub && <p className="text-[11px] text-gray-600 mt-1">{sub}</p>}
    </motion.div>
  );
}

// ─── Animated progress bar ─────────────────────────────────────────────────
function ProgressBar({ label, done, total, color }: { label: string; done: number; total: number; color: string }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div>
      <div className="flex justify-between text-sm mb-2">
        <span className="text-gray-300">{label}</span>
        <span className="text-gray-500 tabular-nums font-mono text-xs">{done.toLocaleString()} / {total.toLocaleString()} · {pct}%</span>
      </div>
      <div className="h-2 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.05)" }}>
        <motion.div
          className="h-full rounded-full"
          style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}60` }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 1, ease: [0.22, 1, 0.36, 1], delay: 0.2 }}
        />
      </div>
    </div>
  );
}

// ─── Compact per-row progress bar (table cells) ────────────────────────────
function MiniBar({ done, total, color }: { done: number; total: number; color: string }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="flex items-center gap-2 min-w-[96px]">
      <span className="tabular-nums font-mono text-xs w-8 text-right" style={{ color }}>{done}</span>
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.05)" }}>
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-[10px] text-gray-600 tabular-nums w-8">{pct}%</span>
    </div>
  );
}

// ─── Dark tooltip ──────────────────────────────────────────────────────────
function DarkTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl px-3.5 py-2.5 text-xs shadow-2xl"
      style={{ background: "rgba(8,8,16,0.92)", border: "1px solid rgba(255,255,255,0.08)", backdropFilter: "blur(12px)" }}>
      {label && <p className="text-gray-400 mb-1.5 font-medium">{label}</p>}
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
          <span className="text-gray-300">{p.dataKey}</span>
          <span className="font-bold text-white ml-auto pl-4">{p.value?.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Chart card ────────────────────────────────────────────────────────────
function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <motion.div variants={fadeUp} className="rounded-2xl p-5"
      style={{
        background: "linear-gradient(145deg, rgba(17,19,31,1) 0%, rgba(10,10,16,1) 100%)",
        border: "1px solid rgba(255,255,255,0.06)",
        boxShadow: "0 4px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)",
      }}>
      <h3 className="text-xs font-semibold tracking-widest uppercase text-gray-500 mb-5">{title}</h3>
      {children}
    </motion.div>
  );
}

const TICK = { fill: "#4b5563", fontSize: 11 };
const GRID_PROPS = { strokeDasharray: "2 4", stroke: "rgba(255,255,255,0.04)", vertical: false };

// ─── Page ──────────────────────────────────────────────────────────────────
export function ClassificationPage() {
  const { data: overview } = useApi<ClassificationOverview>("/classification/overview", true, { staleTime: Infinity });
  const { data: breakdown } = useApi<CategoryNode[]>("/classification/breakdown", true, { staleTime: Infinity });
  const { data: taxonomy } = useApi<{ categories: string[] }>("/taxonomy/categories", true, { staleTime: Infinity });

  const [categoryFilter, setCategoryFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("total");
  const [sortDesc, setSortDesc] = useState(true);

  const categoryChartData = overview
    ? Object.entries(overview.by_category)
        .map(([name, count]) => ({ name: name.replace("_", " "), count, fill: CATEGORY_CHART_COLORS[name] || "#6b7280" }))
        .sort((a, b) => b.count - a.count)
    : [];

  const categoryOptions = useMemo(
    () => taxonomy?.categories ?? Array.from(new Set((breakdown || []).map((r) => r.category))).sort(),
    [taxonomy, breakdown],
  );

  const visibleRows = useMemo(() => {
    let rows = breakdown || [];
    if (categoryFilter !== "all") rows = rows.filter((r) => r.category === categoryFilter);
    return [...rows].sort((a, b) => {
      const av = a[sortKey]; const bv = b[sortKey];
      if (typeof av === "string" && typeof bv === "string") return sortDesc ? bv.localeCompare(av) : av.localeCompare(bv);
      return sortDesc ? (bv as number) - (av as number) : (av as number) - (bv as number);
    });
  }, [breakdown, categoryFilter, sortKey, sortDesc]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDesc((d) => !d);
    else { setSortKey(key); setSortDesc(true); }
  };

  const total = overview?.total_media || 0;
  const videoTotal = overview?.video_media || 0;
  const groqDone = overview?.groq.classified || 0;
  const visionDone = overview?.vision.scored || 0;
  const remaining = (overview?.groq.remaining || 0) + (overview?.vision.remaining || 0);

  const headers: { key: SortKey; label: string }[] = [
    { key: "category", label: "Category" },
    { key: "total", label: "Total" }, { key: "groq_classified", label: "Groq" }, { key: "vision_scored", label: "Vision" },
  ];

  const selectCls = "bg-transparent border rounded-lg px-3 py-1.5 text-xs text-gray-300 focus:outline-none focus:border-gray-500 cursor-pointer transition-colors" +
    " border-gray-700 hover:border-gray-600";

  return (
    <div className="space-y-6 px-1">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-bold tracking-tight">Classification</h2>
        <span className="text-xs text-gray-600 font-medium tracking-widest uppercase mt-0.5">AI Scoring</span>
      </div>

      <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <AnimatedStatCard label="Total Media" value={total} sub={`${videoTotal} videos`} index={0} />
        <AnimatedStatCard label="Groq Classified" value={groqDone} sub={`${overview?.groq.pct ?? 0}% done`} index={1} />
        <AnimatedStatCard label="Vision Scored" value={visionDone} sub={`${overview?.vision.pct ?? 0}% of videos`} index={2} />
        <AnimatedStatCard label="Remaining" value={remaining} sub="groq + vision queue" index={3} />
      </motion.div>

      <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Classification Progress">
          <div className="space-y-6 mt-2">
            <ProgressBar label="Groq — category classification" done={groqDone} total={total} color="#7c3aed" />
            <ProgressBar label="Vision hook-score — videos only" done={visionDone} total={videoTotal} color="#10b981" />
          </div>
        </ChartCard>

        <ChartCard title="Media by Category">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={categoryChartData} barSize={26}>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis dataKey="name" tick={TICK} axisLine={false} tickLine={false} />
              <YAxis tick={TICK} axisLine={false} tickLine={false} width={28} />
              <Tooltip content={<DarkTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
              <Bar dataKey="count" radius={[5, 5, 0, 0]} animationDuration={1000} animationEasing="ease-out">
                {categoryChartData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </motion.div>

      {/* Filterable table */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.18, duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
        className="rounded-2xl overflow-hidden"
        style={{
          background: "linear-gradient(145deg, rgba(17,19,31,1) 0%, rgba(10,10,16,1) 100%)",
          border: "1px solid rgba(255,255,255,0.06)",
          boxShadow: "0 4px 32px rgba(0,0,0,0.4)",
        }}
      >
        <div className="flex flex-wrap items-center gap-3 px-5 py-4 border-b border-white/5">
          <h3 className="text-xs font-semibold tracking-widest uppercase text-gray-500 flex-1">By Category</h3>
          <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} className={selectCls}>
            <option value="all">All categories</option>
            {categoryOptions.map((c) => <option key={c} value={c}>{c.replace("_", " ")}</option>)}
          </select>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/5">
                {headers.map((h) => (
                  <th key={h.key} onClick={() => toggleSort(h.key)}
                    className="px-5 py-3 text-left text-[11px] font-semibold tracking-widest uppercase text-gray-600 cursor-pointer select-none hover:text-gray-400 transition-colors">
                    {h.label}{sortKey === h.key ? (sortDesc ? " ↓" : " ↑") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((r) => (
                <tr key={r.category} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                  <td className="px-5 py-2.5 text-gray-200 font-medium">{r.category.replace("_", " ")}</td>
                  <td className="px-5 py-2.5 tabular-nums text-gray-300 font-mono text-xs">{r.total}</td>
                  <td className="px-5 py-2.5"><MiniBar done={r.groq_classified} total={r.total} color="#a78bfa" /></td>
                  <td className="px-5 py-2.5"><MiniBar done={r.vision_scored} total={r.total} color="#34d399" /></td>
                </tr>
              ))}
              {visibleRows.length === 0 && (
                <tr><td colSpan={4} className="px-5 py-12 text-center text-gray-600 text-sm">No data</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </motion.div>
    </div>
  );
}
