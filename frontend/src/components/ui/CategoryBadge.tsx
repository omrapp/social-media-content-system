import { CATEGORY_BADGE_COLORS } from "@/constants/colors";

export function CategoryBadge({ category }: { category: string }) {
  const color = CATEGORY_BADGE_COLORS[category] || "bg-gray-700 text-gray-100";
  return (
    <span className={`${color} text-xs font-medium px-2 py-0.5 rounded-full capitalize`}>
      {category.replace("_", " ")}
    </span>
  );
}
