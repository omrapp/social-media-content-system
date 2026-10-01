import { STATUS_COLORS } from "@/constants/colors";

export function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status] || "bg-gray-500";
  return (
    <span className={`${color} text-white text-xs font-medium px-2 py-0.5 rounded-full`}>
      {status}
    </span>
  );
}
