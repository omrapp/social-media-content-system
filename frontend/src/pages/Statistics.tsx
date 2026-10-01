import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, PieChart, Pie, Legend,
  TooltipProps,
} from "recharts";
import { useApi } from "@/hooks/useApi";
import { CATEGORY_CHART_COLORS } from "@/constants/colors";
import { staggerContainer, fadeUp } from "@/lib/motion";

// ─── Types ─────────────────────────────────────────────────────────────────
interface StatOverview {
  total_media: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  funnel: { stage: string; count: number }[];
}
interface CategoryRow {
  category: string;
  total: number;
  posted: number;
  error: number;
  raw: number;
}
interface PostsStats {
  total: number;
  by_status: Record<string, number>;
  platforms: { instagram: number; youtube: number; tiktok: number };
}

// ─── Colors ────────────────────────────────────────────────────────────────
const STATUS_COLORS: Record<string, string> = {
  raw:       "#374151",
  resized:   "#3b82f6",
  edited:    "#8b5cf6",
  uploaded:  "#f59e0b",
  posted:    "#10b981",
  error:     "#ef4444",
};

const PLATFORM_CFG: Record<string, { color: string; glow: string }> = {
  instagram: { color: "#e1306c", glow: "rgba(225,48,108,0.2)" },
  youtube:   { color: "#ff4444", glow: "rgba(255,68,68,0.2)" },
  tiktok:    { color: "#69c9d0", glow: "rgba(105,201,208,0.2)" },
};

const CARD_CFG = [
  { glow: "rgba(99,102,241,0.18)", border: "rgba(99,102,241,0.25)", text: "#a5b4fc", bg: "rgba(99,102,241,0.06)" },
  { glow: "rgba(16,185,129,0.18)", border: "rgba(16,185,129,0.25)", text: "#6ee7b7", bg: "rgba(16,185,129,0.06)" },
  { glow: "rgba(139,92,246,0.18)", border: "rgba(139,92,246,0.25)", text: "#c4b5fd", bg: "rgba(139,92,246,0.06)" },
  { glow: "rgba(239,68,68,0.18)",  border: "rgba(239,68,68,0.25)",  text: "#fca5a5", bg: "rgba(239,68,68,0.06)" },
];

// ─── Animated counter ──────────────────────────────────────────────────────
function useCountUp(target: number, duration = 900) {
  const [count, setCount] = useState(0);
  const raf = useRef<number>(0);
  useEffect(() => {
    if (target === 0) { setCount(0); return; }
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - start) / duration, 1);
      const ease = 1 - Math.pow(1 - p, 3);
      setCount(Math.round(ease * target));
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, duration]);
  return count;
}

// ─── Shared chart axis props ───────────────────────────────────────────────
const TICK = { fill: "#4b5563", fontSize: 11 };
const GRID_PROPS = { strokeDasharray: "2 4", stroke: "rgba(255,255,255,0.04)", vertical: false };

// ─── Custom tooltip ────────────────────────────────────────────────────────
function DarkTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  return (
    <div
      className="rounded-xl px-3.5 py-2.5 text-xs shadow-2xl"
      style={{
        background: "rgba(8,8,16,0.92)",
        border: "1px solid rgba(255,255,255,0.08)",
        backdropFilter: "blur(12px)",
      }}
    >
      {label && <p className="text-gray-400 mb-1.5 font-medium">{label}</p>}
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
          <span className="text-gray-300 capitalize">{p.dataKey}</span>
          <span className="font-bold text-white ml-auto pl-4">{p.value?.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Stat card ─────────────────────────────────────────────────────────────
function AnimatedStatCard({
  label, value, sub, index,
}: { label: string; value: number; sub?: string; index: number }) {
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
      <div
        className="absolute inset-0 opacity-30 pointer-events-none"
        style={{ background: `radial-gradient(ellipse at 80% 0%, ${cfg.glow} 0%, transparent 70%)` }}
      />
      <p className="text-xs font-medium tracking-widest uppercase text-gray-500">{label}</p>
      <p className="text-3xl font-bold mt-1.5 tabular-nums" style={{ color: cfg.text }}>
        {count.toLocaleString()}
      </p>
      {sub && <p className="text-[11px] text-gray-600 mt-1">{sub}</p>}
    </motion.div>
  );
}

// ─── Chart card wrapper ────────────────────────────────────────────────────
function ChartCard({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <motion.div
      variants={fadeUp}
      className={`rounded-2xl p-5 ${className}`}
      style={{
        background: "linear-gradient(145deg, rgba(17,19,31,1) 0%, rgba(10,10,16,1) 100%)",
        border: "1px solid rgba(255,255,255,0.06)",
        boxShadow: "0 4px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)",
      }}
    >
      <h3 className="text-xs font-semibold tracking-widest uppercase text-gray-500 mb-5">{title}</h3>
      {children}
    </motion.div>
  );
}


// ─── Platform progress bar ─────────────────────────────────────────────────
function PlatformBar({ name, count, max }: { name: string; count: number; max: number }) {
  const cfg = PLATFORM_CFG[name.toLowerCase()] || { color: "#6b7280", glow: "transparent" };
  const pct = max > 0 ? (count / max) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-gray-400 w-20 capitalize shrink-0">{name}</span>
      <div className="flex-1 h-1.5 rounded-full bg-gray-800 overflow-hidden">
        <motion.div
          className="h-full rounded-full"
          style={{ backgroundColor: cfg.color, boxShadow: `0 0 6px ${cfg.glow}` }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1], delay: 0.2 }}
        />
      </div>
      <span className="text-xs font-bold tabular-nums text-gray-300 w-6 text-right">{count}</span>
    </div>
  );
}

// ─── Page ──────────────────────────────────────────────────────────────────
export function StatisticsPage() {
  const { data: overview } = useApi<StatOverview>("/statistics/overview", true, { staleTime: Infinity });
  const { data: categories } = useApi<CategoryRow[]>("/statistics/categories", true, { staleTime: Infinity });
  const { data: posts } = useApi<PostsStats>("/statistics/posts", true, { staleTime: Infinity });

  const categoryData = overview
    ? Object.entries(overview.by_category)
        .map(([name, count]) => ({ name: name.replace("_", " "), count, fill: CATEGORY_CHART_COLORS[name] || "#6b7280" }))
        .sort((a, b) => b.count - a.count)
    : [];

  const categoryChartData = (categories || []).slice(0, 15).map((c) => ({
    name: c.category,
    total: c.total,
    posted: c.posted,
    error: c.error,
  }));

  const platformData = posts
    ? Object.entries(posts.platforms).map(([name, count]) => ({
        name: name.charAt(0).toUpperCase() + name.slice(1),
        count,
      }))
    : [];

  const maxPlatform = Math.max(...platformData.map((p) => p.count), 1);

  const postStatusData = posts
    ? Object.entries(posts.by_status).map(([name, value]) => ({ name, value }))
    : [];

  const total = overview?.total_media || 0;
  const posted = overview?.by_status?.posted || 0;
  const errors = overview?.by_status?.error || 0;
  const inProgress =
    (overview?.by_status?.resized || 0) +
    (overview?.by_status?.edited || 0) +
    (overview?.by_status?.uploaded || 0);

  const postsTotal = posts?.total || 0;

  return (
    <div className="space-y-6 px-1">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-bold tracking-tight">Statistics</h2>
        <span className="text-xs text-gray-600 font-medium tracking-widest uppercase mt-0.5">Pipeline</span>
      </div>

      {/* Summary cards */}
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-2 md:grid-cols-4 gap-3"
      >
        <AnimatedStatCard label="Total Media" value={total} index={0} />
        <AnimatedStatCard
          label="Posted"
          value={posted}
          sub={total ? `${Math.round((posted / total) * 100)}% of total` : undefined}
          index={1}
        />
        <AnimatedStatCard label="In Pipeline" value={inProgress} sub="resized → uploaded" index={2} />
        <AnimatedStatCard
          label="Errors"
          value={errors}
          sub={errors > 0 ? "needs attention" : "all clear"}
          index={3}
        />
      </motion.div>

      {/* Funnel + Post status */}
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-1 lg:grid-cols-2 gap-4"
      >
        <ChartCard title="Pipeline Funnel">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={overview?.funnel || []} layout="vertical" barSize={18}>
              <defs>
                {(overview?.funnel || []).map((entry) => (
                  <linearGradient key={entry.stage} id={`funnel_${entry.stage}`} x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor={STATUS_COLORS[entry.stage] || "#6b7280"} stopOpacity={1} />
                    <stop offset="100%" stopColor={STATUS_COLORS[entry.stage] || "#6b7280"} stopOpacity={0.6} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid strokeDasharray="2 4" stroke="rgba(255,255,255,0.04)" horizontal={false} />
              <XAxis type="number" tick={TICK} axisLine={false} tickLine={false} />
              <YAxis dataKey="stage" type="category" tick={TICK} width={60} axisLine={false} tickLine={false} />
              <Tooltip content={<DarkTooltip />} cursor={{ fill: "rgba(255,255,255,0.02)" }} />
              <Bar dataKey="count" radius={[0, 5, 5, 0]} animationDuration={1000} animationEasing="ease-out">
                {(overview?.funnel || []).map((entry) => (
                  <Cell key={entry.stage} fill={`url(#funnel_${entry.stage})`} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Posts by Status">
          {posts && postsTotal > 0 ? (
            <div className="relative">
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie
                    data={postStatusData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="46%"
                    innerRadius={58}
                    outerRadius={88}
                    paddingAngle={2}
                    animationBegin={200}
                    animationDuration={1000}
                    labelLine={false}
                  >
                    {postStatusData.map((entry) => (
                      <Cell
                        key={entry.name}
                        fill={STATUS_COLORS[entry.name] || "#6b7280"}
                        stroke="rgba(0,0,0,0.4)"
                        strokeWidth={1}
                      />
                    ))}
                  </Pie>
                  <Tooltip content={<DarkTooltip />} />
                  <Legend
                    wrapperStyle={{ fontSize: 11, color: "#6b7280", paddingTop: 8 }}
                    iconType="circle"
                    iconSize={6}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none" style={{ paddingBottom: 36 }}>
                <div className="text-center">
                  <div className="text-2xl font-bold text-gray-100 tabular-nums">{postsTotal}</div>
                  <div className="text-[9px] text-gray-600 tracking-widest uppercase mt-0.5">posts</div>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-600 py-20 text-center">No posts yet</p>
          )}
        </ChartCard>
      </motion.div>

      {/* Platform + Category */}
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-1 lg:grid-cols-3 gap-4"
      >
        <ChartCard title="Published per Platform" className="lg:col-span-1">
          <div className="space-y-4 mt-2">
            {platformData.map(({ name, count }) => (
              <PlatformBar key={name} name={name} count={count} max={maxPlatform} />
            ))}
            {platformData.length === 0 && <p className="text-xs text-gray-600">No data</p>}
          </div>
        </ChartCard>

        <ChartCard title="Media by Category" className="lg:col-span-2">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={categoryData} barSize={26}>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis dataKey="name" tick={TICK} axisLine={false} tickLine={false} />
              <YAxis tick={TICK} axisLine={false} tickLine={false} width={28} />
              <Tooltip content={<DarkTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
              <Bar dataKey="count" radius={[5, 5, 0, 0]} animationDuration={1000} animationEasing="ease-out">
                {categoryData.map((entry, i) => (
                  <Cell key={i} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </motion.div>

      {/* Category breakdown */}
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.28, duration: 0.32, ease: [0.22, 1, 0.36, 1] }}>
        <ChartCard title="Top 15 Categories">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={categoryChartData} barSize={10}>
              <defs>
                <linearGradient id="totalGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3b82f6" stopOpacity={1} />
                  <stop offset="100%" stopColor="#1d4ed8" stopOpacity={0.7} />
                </linearGradient>
                <linearGradient id="postedGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity={1} />
                  <stop offset="100%" stopColor="#059669" stopOpacity={0.7} />
                </linearGradient>
                <linearGradient id="errorGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ef4444" stopOpacity={1} />
                  <stop offset="100%" stopColor="#b91c1c" stopOpacity={0.7} />
                </linearGradient>
              </defs>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis dataKey="name" tick={TICK} angle={-35} textAnchor="end" interval={0} height={60} axisLine={false} tickLine={false} />
              <YAxis tick={TICK} axisLine={false} tickLine={false} width={28} />
              <Tooltip content={<DarkTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
              <Bar dataKey="total" name="Total" fill="url(#totalGrad)" radius={[3, 3, 0, 0]} animationDuration={1000} animationEasing="ease-out" />
              <Bar dataKey="posted" name="Posted" fill="url(#postedGrad)" radius={[3, 3, 0, 0]} animationDuration={1100} animationEasing="ease-out" />
              <Bar dataKey="error" name="Error" fill="url(#errorGrad)" radius={[3, 3, 0, 0]} animationDuration={1200} animationEasing="ease-out" />
              <Legend wrapperStyle={{ color: "#6b7280", fontSize: 11 }} iconType="circle" iconSize={6} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </motion.div>
    </div>
  );
}
