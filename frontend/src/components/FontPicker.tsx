import { useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Type, ChevronDown, Star } from "lucide-react";
import type { AssetItem, AssetListResponse } from "@/types/assets";

interface Props {
  value: string;                 // selected font filename ("" = default)
  onChange: (file: string) => void;
  defaultLabel?: string;          // e.g. "Default (PlayfairDisplay-SemiBold)"
}

/**
 * Font picker sourced from /api/assets/all?type=font (1.11.0 assets metadata
 * cutover), replacing the plain <select> that used to read /api/assets/fonts.
 * Kept compact (drop-in size parity with the old <select>) since it's reused
 * inside small per-element cards (Design → Intro/Cast screen text elements)
 * as well as the top-level Branding font field.
 */
export function FontPicker({ value, onChange, defaultLabel = "Default (PlayfairDisplay-SemiBold)" }: Props) {
  const { data, setData } = useApi<AssetListResponse>("/assets/all?type=font");
  const fonts = data?.assets ?? [];
  const [open, setOpen] = useState(false);
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Filter chips derived from whatever tags are present on the currently-loaded
  // list — client-side only, no extra backend call.
  const allTags = useMemo(() => {
    const set = new Set<string>();
    fonts.forEach((f) => { (f.tags ?? []).forEach((t) => set.add(t)); });
    return Array.from(set).sort();
  }, [fonts]);

  const toggleTagFilter = (t: string) =>
    setTagFilter((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  const filtered = fonts.filter((f) =>
    tagFilter.length === 0 || (f.tags ?? []).some((t) => tagFilter.includes(t))
  );

  const selected = fonts.find((f) => f.filename === value);

  const toggleFavourite = async (e: React.MouseEvent, item: AssetItem) => {
    e.stopPropagation();
    const next = !item.favourite;
    setData(data ? { assets: data.assets.map((a) => (a.id === item.id ? { ...a, favourite: next } : a)) } : data);
    try {
      await api.put(`/assets/all/${item.id}`, { favourite: next });
    } catch {
      setData(data ? { assets: data.assets.map((a) => (a.id === item.id ? { ...a, favourite: !next } : a)) } : data);
      toast.error("Failed to update favourite");
    }
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-800 border border-gray-700 text-sm text-left hover:border-gray-600 transition-colors focus:border-blue-500 outline-none"
      >
        <Type size={12} className="shrink-0 text-gray-500" />
        <span className="flex-1 truncate text-gray-200">{selected?.name ?? defaultLabel}</span>
        {selected?.favourite && <Star size={10} fill="currentColor" className="shrink-0 text-amber-400" />}
        <ChevronDown size={12} className={`shrink-0 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl max-h-56 overflow-hidden flex flex-col">
          {allTags.length > 0 && (
            <div className="sticky top-0 bg-gray-800 border-b border-gray-700 p-1.5 flex flex-wrap gap-1">
              {allTags.map((t) => {
                const on = tagFilter.includes(t);
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={(e) => { e.stopPropagation(); toggleTagFilter(t); }}
                    className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                      on
                        ? "bg-amber-600 border-amber-500 text-white"
                        : "bg-gray-900 border-gray-700 text-gray-400 hover:border-gray-500"
                    }`}
                  >
                    {t.replace("_", " ")}
                  </button>
                );
              })}
            </div>
          )}
          <div className="overflow-y-auto">
            <button
              type="button"
              onClick={() => { onChange(""); setOpen(false); }}
              className={`w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors ${
                value === "" ? "bg-blue-600 text-white" : "hover:bg-gray-700 text-gray-300"
              }`}
            >
              <span className="flex-1 truncate">{defaultLabel}</span>
            </button>
            {filtered.length === 0 ? (
              <p className="px-3 py-2 text-xs text-gray-500">No fonts in assets/fonts/</p>
            ) : filtered.map((f) => (
              <div
                key={f.id}
                className={`w-full flex items-center transition-colors ${
                  value === f.filename ? "bg-blue-600 text-white" : "hover:bg-gray-700 text-gray-300"
                }`}
              >
                <button
                  type="button"
                  onClick={() => { onChange(f.filename); setOpen(false); }}
                  className="flex-1 min-w-0 flex items-center gap-2 pl-3 pr-1 py-2 text-xs text-left"
                >
                  <Type size={11} className="shrink-0" />
                  <span className="flex-1 truncate">{f.name}</span>
                </button>
                <button
                  type="button"
                  onClick={(e) => toggleFavourite(e, f)}
                  title={f.favourite ? "Unfavourite" : "Favourite"}
                  className={`shrink-0 p-0.5 mr-2 rounded hover:bg-black/20 ${f.favourite ? "text-amber-400" : "text-gray-500"}`}
                >
                  <Star size={11} fill={f.favourite ? "currentColor" : "none"} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
