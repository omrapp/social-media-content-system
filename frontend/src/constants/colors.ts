export const STATUS_COLORS: Record<string, string> = {
  raw: "bg-gray-600",
  resized: "bg-blue-600",
  enhanced: "bg-violet-600",
  edited: "bg-indigo-600",
  uploaded: "bg-cyan-600",
  scheduled: "bg-yellow-600",
  preview: "bg-amber-500",
  publishing: "bg-green-700 animate-pulse",
  posted: "bg-green-600",
  error: "bg-red-600",
  deleted: "bg-gray-800",
};

/** Tailwind classes — used in CategoryBadge */
export const CATEGORY_BADGE_COLORS: Record<string, string> = {
  hidden_gem: "bg-teal-700 text-teal-100",
  budget: "bg-amber-700 text-amber-100",
  culture: "bg-purple-700 text-purple-100",
};

/** Hex values — used in recharts */
export const CATEGORY_CHART_COLORS: Record<string, string> = {
  hidden_gem: "#0d9488",
  budget: "#d97706",
  culture: "#7c3aed",
};

// Categories are user-defined, so anything not pinned above gets a stable
// colour from these palettes (same name → same colour on every page).
const CHART_PALETTE = ["#0d9488", "#d97706", "#7c3aed", "#2563eb", "#db2777", "#16a34a", "#ea580c", "#0891b2"];
const BADGE_PALETTE = [
  "bg-teal-700 text-teal-100", "bg-amber-700 text-amber-100", "bg-purple-700 text-purple-100",
  "bg-blue-700 text-blue-100", "bg-pink-700 text-pink-100", "bg-green-700 text-green-100",
  "bg-orange-700 text-orange-100", "bg-cyan-700 text-cyan-100",
];

function paletteIndex(name: string, size: number): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return h % size;
}

export function categoryChartColor(name: string): string {
  if (!name) return "#6b7280";
  return CATEGORY_CHART_COLORS[name] ?? CHART_PALETTE[paletteIndex(name, CHART_PALETTE.length)];
}

export function categoryBadgeColor(name: string): string {
  if (!name) return "bg-gray-700 text-gray-100";
  return CATEGORY_BADGE_COLORS[name] ?? BADGE_PALETTE[paletteIndex(name, BADGE_PALETTE.length)];
}

export const NOTIFICATION_TYPE_COLORS: Record<string, string> = {
  error: "text-red-400",
  success: "text-green-400",
  warning: "text-amber-400",
  info: "text-blue-400",
};
