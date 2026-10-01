import { useId, useState } from "react";
import { X, Layers, Hash } from "lucide-react";
import { useApi } from "@/hooks/useApi";

const COMPACT_STYLE = {
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
} as const;

interface CategoryTagsPickerProps {
  category: string;
  tags: string[];
  onCategoryChange: (category: string) => void;
  onTagsChange: (tags: string[]) => void;
  categoryLabel?: string;
  categoryPlaceholder?: string;
  tagsPlaceholder?: string;
  disabled?: boolean;
  /** "wizard" = full labeled block (Create.tsx step layout); "compact" = inline
   *  toolbar row (Google/Stock/Upload panels + the merge modal). */
  variant?: "wizard" | "compact";
  className?: string;
}

/** Category `<select>` (from /taxonomy/categories) + freeform tags chip input
 * (autocompleted from /taxonomy/tags, typing a new value adds it). Replaces the
 * old country → city → pillar cascade everywhere it appeared. */
export function CategoryTagsPicker({
  category, tags, onCategoryChange, onTagsChange,
  categoryLabel = "Category", categoryPlaceholder, tagsPlaceholder = "Add a tag…",
  disabled, variant = "compact", className,
}: CategoryTagsPickerProps) {
  const { data: categoriesResp, loading: categoriesLoading } = useApi<{ categories: string[] }>("/taxonomy/categories");
  const { data: tagsResp } = useApi<{ tags: string[] }>("/taxonomy/tags");
  const categories = categoriesResp?.categories ?? [];
  const knownTags = tagsResp?.tags ?? [];
  const [tagInput, setTagInput] = useState("");
  const datalistId = useId();

  const addTag = (raw: string) => {
    const v = raw.trim();
    if (!v || tags.includes(v)) { setTagInput(""); return; }
    onTagsChange([...tags, v]);
    setTagInput("");
  };
  const removeTag = (v: string) => onTagsChange(tags.filter((t) => t !== v));

  const handleTagKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(tagInput);
    } else if (e.key === "Backspace" && !tagInput && tags.length > 0) {
      removeTag(tags[tags.length - 1]);
    }
  };

  const tagOptions = knownTags.filter((t) => !tags.includes(t));

  if (variant === "wizard") {
    return (
      <div className={`space-y-4 ${className ?? ""}`}>
        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wide">{categoryLabel}</label>
          <div className="relative">
            <Layers size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
            <select
              value={category}
              onChange={(e) => onCategoryChange(e.target.value)}
              disabled={disabled || categoriesLoading}
              className="w-full pl-9 pr-3 py-2.5 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 appearance-none cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed focus:border-blue-500 focus:outline-none transition-colors"
            >
              <option value="">{categoriesLoading ? "Loading…" : categoryPlaceholder ?? "Select category"}</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1.5 uppercase tracking-wide">Tags (optional)</label>
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-1.5">
              {tags.map((t) => (
                <span key={t} className="flex items-center gap-1 bg-gray-800 border border-gray-700 rounded-full px-2 py-0.5 text-xs text-gray-300">
                  {t}
                  <button type="button" onClick={() => removeTag(t)} disabled={disabled} className="text-gray-500 hover:text-white">
                    <X size={10} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="relative">
            <Hash size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
            <input
              list={datalistId}
              value={tagInput}
              disabled={disabled}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={handleTagKeyDown}
              onBlur={() => tagInput.trim() && addTag(tagInput)}
              placeholder={tagsPlaceholder}
              className="w-full pl-9 pr-3 py-2.5 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 disabled:opacity-40 focus:border-blue-500 focus:outline-none transition-colors"
            />
            <datalist id={datalistId}>
              {tagOptions.map((t) => <option key={t} value={t} />)}
            </datalist>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className ?? ""}`}>
      <select
        value={category}
        disabled={disabled || categoriesLoading}
        onChange={(e) => onCategoryChange(e.target.value)}
        className="rounded-lg px-2.5 py-2 text-xs text-gray-300 focus:outline-none cursor-pointer disabled:opacity-40"
        style={COMPACT_STYLE}
      >
        <option value="">{categoryPlaceholder ?? `${categoryLabel}…`}</option>
        {categories.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>

      {tags.map((t) => (
        <span key={t} className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-gray-300" style={COMPACT_STYLE}>
          {t}
          <button type="button" onClick={() => removeTag(t)} disabled={disabled} className="text-gray-500 hover:text-white">
            <X size={10} />
          </button>
        </span>
      ))}
      <input
        list={datalistId}
        value={tagInput}
        disabled={disabled}
        onChange={(e) => setTagInput(e.target.value)}
        onKeyDown={handleTagKeyDown}
        onBlur={() => tagInput.trim() && addTag(tagInput)}
        placeholder={tagsPlaceholder}
        className="w-28 rounded-lg px-2.5 py-2 text-xs text-gray-300 placeholder-gray-600 focus:outline-none disabled:opacity-40"
        style={COMPACT_STYLE}
      />
      <datalist id={datalistId}>
        {tagOptions.map((t) => <option key={t} value={t} />)}
      </datalist>
    </div>
  );
}
