import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useApi } from "@/hooks/useApi";
import {
  BarChart, Bar, AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, Legend,
  TooltipProps,
} from "recharts";
import type { AnalyticsOverview, TimeseriesItem, CategoryStat } from "@/types/analytics";
import { CATEGORY_CHART_COLORS } from "@/constants/colors";
import { staggerContainer, fadeUp } from "@/lib/motion";

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

// ─── Card config ───────────────────────────────────────────────────────────
const CARD_CFG = [
  { glow: "rgba(99,102,241,0.18)", border: "rgba(99,102,241,0.25)", text: "#a5b4fc", bg: "rgba(99,102,241,0.06)" },
  { glow: "rgba(16,185,129,0.18)", border: "rgba(16,185,129,0.25)", text: "#6ee7b7", bg: "rgba(16,185,129,0.06)" },
  { glow: "rgba(245,158,11,0.18)", border: "rgba(245,158,11,0.25)", text: "#fcd34d", bg: "rgba(245,158,11,0.06)" },
  { glow: "rgba(239,68,68,0.18)",  border: "rgba(239,68,68,0.25)",  text: "#fca5a5", bg: "rgba(239,68,68,0.06)" },
];

// ─── Stat card ─────────────────────────────────────────────────────────────
function AnimatedStatCard({
  label, value, index,
}: { label: string; value: number; index: number }) {
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
        style={{
          background: `radial-gradient(ellipse at 80% 0%, ${cfg.glow} 0%, transparent 70%)`,
        }}
      />
      <p className="text-xs font-medium tracking-widest uppercase text-gray-500">{label}</p>
      <p className="text-3xl font-bold mt-1.5 tabular-nums" style={{ color: cfg.text }}>
        {count.toLocaleString()}
      </p>
    </motion.div>
  );
}

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

// ─── Chart card wrapper ────────────────────────────────────────────────────
function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <motion.div
      variants={fadeUp}
      className="rounded-2xl p-5"
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

// ─── Axis / grid shared props ──────────────────────────────────────────────
const TICK = { fill: "#4b5563", fontSize: 11 };
const GRID_PROPS = { strokeDasharray: "2 4", stroke: "rgba(255,255,255,0.04)", vertical: false };

// ─── Page ──────────────────────────────────────────────────────────────────
export function AnalyticsPage() {
  const { data: overview } = useApi<AnalyticsOverview>("/analytics/overview", true, { staleTime: Infinity });
  const { data: timeseries } = useApi<TimeseriesItem[]>("/analytics/timeseries?days=30", true, { staleTime: Infinity });
  const { data: categories } = useApi<Record<string, CategoryStat>>("/analytics/categories", true, { staleTime: Infinity });

  const statusData = overview
    ? Object.entries(overview.by_status).map(([name, value]) => ({ name, value }))
    : [];

  const categoryData = categories
    ? Object.entries(categories).map(([name, data]) => ({
        name: name.replace("_", " "),
        count: data.count,
        fill: CATEGORY_CHART_COLORS[name] || "#6b7280",
      }))
    : [];

  const tsData = (timeseries || []).map((t) => ({
    date: new Date(t.fetched_at).toLocaleDateString("en", { month: "short", day: "numeric" }),
    reach: t.reach,
    likes: t.likes,
    saves: t.saves,
  }));

  const stats = [
    { label: "Total Media",  value: overview?.total_media || 0 },
    { label: "Posted",       value: overview?.by_status?.posted || 0 },
    { label: "Scheduled",    value: overview?.by_status?.scheduled || 0 },
    { label: "Errors",       value: overview?.by_status?.error || 0 },
  ];

  return (
    <div className="space-y-6 px-1">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-bold tracking-tight">Analytics</h2>
        <span className="text-xs text-gray-600 font-medium tracking-widest uppercase mt-0.5">Overview</span>
      </div>

      {/* Stat cards */}
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-2 md:grid-cols-4 gap-3"
      >
        {stats.map(({ label, value }, i) => (
          <AnimatedStatCard key={label} label={label} value={value} index={i} />
        ))}
      </motion.div>

      {/* Bar charts row */}
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-1 lg:grid-cols-2 gap-4"
      >
        <ChartCard title="Media by Status">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={statusData} barSize={28}>
              <defs>
                <linearGradient id="statusGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6366f1" stopOpacity={1} />
                  <stop offset="100%" stopColor="#4338ca" stopOpacity={0.7} />
                </linearGradient>
              </defs>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis dataKey="name" tick={TICK} axisLine={false} tickLine={false} />
              <YAxis tick={TICK} axisLine={false} tickLine={false} width={28} />
              <Tooltip content={<DarkTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
              <Bar
                dataKey="value"
                fill="url(#statusGrad)"
                radius={[5, 5, 0, 0]}
                animationDuration={1000}
                animationEasing="ease-out"
              />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="By Category">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={categoryData} barSize={28}>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis dataKey="name" tick={TICK} axisLine={false} tickLine={false} />
              <YAxis tick={TICK} axisLine={false} tickLine={false} width={28} />
              <Tooltip content={<DarkTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
              <Bar
                dataKey="count"
                radius={[5, 5, 0, 0]}
                animationDuration={1100}
                animationEasing="ease-out"
              >
                {categoryData.map((entry, i) => (
                  <Cell key={i} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </motion.div>

      {/* Engagement area chart */}
      {tsData.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.22, duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
        >
          <ChartCard title="Engagement Over Time — 30 Days">
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={tsData}>
                <defs>
                  <linearGradient id="reachGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="likesGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="savesGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="2 4" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="date" tick={TICK} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={TICK} axisLine={false} tickLine={false} width={32} />
                <Tooltip
                  content={<DarkTooltip />}
                  cursor={{ stroke: "rgba(255,255,255,0.06)", strokeWidth: 1 }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 11, color: "#6b7280", paddingTop: 16 }}
                  iconType="circle"
                  iconSize={6}
                />
                <Area
                  type="monotone"
                  dataKey="reach"
                  stroke="#6366f1"
                  strokeWidth={2}
                  fill="url(#reachGrad)"
                  dot={false}
                  activeDot={{ r: 4, fill: "#6366f1", stroke: "#0a0a10", strokeWidth: 2 }}
                  animationDuration={1200}
                  animationEasing="ease-out"
                />
                <Area
                  type="monotone"
                  dataKey="likes"
                  stroke="#ef4444"
                  strokeWidth={2}
                  fill="url(#likesGrad)"
                  dot={false}
                  activeDot={{ r: 4, fill: "#ef4444", stroke: "#0a0a10", strokeWidth: 2 }}
                  animationDuration={1300}
                  animationEasing="ease-out"
                />
                <Area
                  type="monotone"
                  dataKey="saves"
                  stroke="#10b981"
                  strokeWidth={2}
                  fill="url(#savesGrad)"
                  dot={false}
                  activeDot={{ r: 4, fill: "#10b981", stroke: "#0a0a10", strokeWidth: 2 }}
                  animationDuration={1400}
                  animationEasing="ease-out"
                />
              </AreaChart>
            </ResponsiveContainer>
          </ChartCard>
        </motion.div>
      )}
    </div>
  );
}
