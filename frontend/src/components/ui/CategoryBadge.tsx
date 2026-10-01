import { categoryBadgeColor } from "@/constants/colors";

export function CategoryBadge({ category }: { category: string }) {
  const color = categoryBadgeColor(category);
  return (
    <span className={`${color} text-xs font-medium px-2 py-0.5 rounded-full capitalize`}>
      {category.replace("_", " ")}
    </span>
  );
}
