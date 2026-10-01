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

export const NOTIFICATION_TYPE_COLORS: Record<string, string> = {
  error: "text-red-400",
  success: "text-green-400",
  warning: "text-amber-400",
  info: "text-blue-400",
};
