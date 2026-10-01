import { useRef, useState, useEffect, useMemo } from "react";
import { useApi } from "@/hooks/useApi";
import { useRecentPicks } from "@/hooks/useRecentPicks";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Palette, ChevronDown, Search, Clock, Star } from "lucide-react";
import type { AssetItem, AssetListResponse } from "@/types/assets";

interface Lut {
  id: string;
  name: string;
  file: string;          // LUTS_DIR-relative path the pipeline expects ("warm.cube" | "cinematic/x.cube")
  tags: string[];
  categories: string[];
  favourite: boolean;
  dir: "legacy" | "cinematic";
}

interface RecentLut {
  id: string;    // = file, useRecentPicks dedupe key
  name: string;
  file: string;
}

// `filename` on an assets row is always a bare basename (e.g. "teal_orange.cube")
// — it never carries the "cinematic/" subfolder, so using it directly as `file`
// would silently break every curated cinematic LUT (the pipeline expects a
// LUTS_DIR-relative path, "cinematic/teal_orange.cube"). `local_path` is
// relative to ASSETS_DIR ("luts/cinematic/teal_orange.cube" | "luts/warm.cube")
// and does preserve the subfolder — strip the "luts/" prefix to recover it.
function lutRelPath(item: AssetItem): string {
  if (item.local_path) {
    const rel = item.local_path.replace(/^luts\//, "");
    if (rel) return rel;
  }
  return item.filename;
}

function toLut(item: AssetItem): Lut {
  const file = lutRelPath(item);
  return {
    id: item.id,
    name: item.name,
    file,
    tags: item.tags ?? [],
    categories: (item.meta?.categories as string[] | undefined) ?? [],
    favourite: item.favourite,
    dir: file.includes("/") ? "cinematic" : "legacy",
  };
}

interface Props {
  value: string;         // selected LUT `file`
  onChange: (file: string) => void;
}

export function LutPicker({ value, onChange }: Props) {
  const { data, loading, setData } = useApi<AssetListResponse>("/assets/all?type=lut");
  const luts = useMemo(() => (data?.assets ?? []).map(toLut), [data]);
  const { recent, pushRecent } = useRecentPicks<RecentLut>("lut_picker_recent");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const selectedLut = luts.find((l) => l.file === value);
  const q = query.trim().toLowerCase();

  // Filter chips derived from whatever tags/categories are actually present on
  // the currently-loaded list (assets-table tags, populated as admins tag
  // LUTs on the Assets page — no separate backend call per filter click).
  const allTags = useMemo(() => {
    const set = new Set<string>();
    luts.forEach((l) => { l.tags.forEach((t) => set.add(t)); l.categories.forEach((t) => set.add(t)); });
    return Array.from(set).sort();
  }, [luts]);

  const toggleTagFilter = (t: string) =>
    setTagFilter((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  // Text search (contains) AND tag/category chips (OR — a LUT shows if any of
  // its tags/categories is checked; untagged LUTs are hidden while a filter
  // is active).
  const filteredLuts = luts.filter((l) => {
    const matchText = !q ||
      `${l.name} ${l.tags.join(" ")} ${l.categories.join(" ")} ${l.dir}`
        .toLowerCase().includes(q);
    const matchTag = tagFilter.length === 0 || [...l.tags, ...l.categories].some((t) => tagFilter.includes(t));
    return matchText && matchTag;
  });

  const selectLut = (l: Lut) => {
    onChange(l.file);
    setOpen(false);
    pushRecent({ id: l.file, name: l.name, file: l.file });
  };

  const toggleFavourite = async (e: React.MouseEvent, l: Lut) => {
    e.stopPropagation();
    const next = !l.favourite;
    setData(data ? { assets: data.assets.map((a) => (a.id === l.id ? { ...a, favourite: next } : a)) } : data);
    try {
      await api.put(`/assets/all/${l.id}`, { favourite: next });
    } catch {
      setData(data ? { assets: data.assets.map((a) => (a.id === l.id ? { ...a, favourite: !next } : a)) } : data);
      toast.error("Failed to update favourite");
    }
  };

  if (loading) return <p className="text-xs text-gray-500">Loading LUTs…</p>;
  if (!luts.length) return <p className="text-xs text-gray-500">No LUTs in assets/luts/</p>;

  return (
    <div className="space-y-2">
      {/* Recent picks — quick re-select, last 7 */}
      {recent.length > 0 && (
        <div className="flex items-center gap-1 flex-wrap">
          <Clock size={10} className="shrink-0 text-gray-500" />
          {recent.map((r) => (
            <button
              key={r.id}
              type="button"
              title={r.name}
              onClick={() => { onChange(r.file); pushRecent(r); }}
              className={`max-w-[7rem] truncate text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                value === r.file
                  ? "bg-amber-600 border-amber-500 text-white"
                  : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500"
              }`}
            >
              {r.name}
            </button>
          ))}
        </div>
      )}

      <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 rounded bg-gray-800 border border-gray-700 text-xs text-left hover:border-gray-600 transition-colors"
      >
        <Palette size={11} className="shrink-0 text-gray-500" />
        <span className="flex-1 truncate text-gray-200">
          {selectedLut?.name ?? "No LUT selected"}
        </span>
        {selectedLut?.favourite && <Star size={10} fill="currentColor" className="shrink-0 text-amber-400" />}
        {selectedLut?.tags?.length ? (
          <span className="shrink-0 text-gray-500">· {selectedLut.tags.join(" ")}</span>
        ) : null}
        <ChevronDown
          size={11}
          className={`shrink-0 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-gray-800 border border-gray-700 rounded shadow-xl max-h-56 overflow-hidden flex flex-col">
          {/* Search + tag/category filter */}
          <div className="sticky top-0 bg-gray-800 border-b border-gray-700 p-1.5 space-y-1.5">
            <div className="relative">
              <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onMouseDown={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
                placeholder="Search LUTs…"
                className="w-full pl-7 pr-2 py-1 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:border-amber-500 focus:outline-none"
              />
            </div>
            {allTags.length > 0 && (
              <div className="flex flex-wrap gap-1">
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
          </div>
          <div className="overflow-y-auto">
          {filteredLuts.length === 0 ? (
            <p className="px-3 py-2 text-xs text-gray-500">No LUTs match "{query}"</p>
          ) : filteredLuts.map((l) => (
            <div
              key={l.file}
              className={`w-full flex items-center transition-colors ${
                value === l.file ? "bg-amber-600 text-white" : "hover:bg-gray-700 text-gray-300"
              }`}
            >
              <button
                type="button"
                onClick={() => selectLut(l)}
                title={l.tags.length ? `Tags: ${l.tags.join(", ")}` : undefined}
                className="flex-1 min-w-0 flex items-center gap-2 pl-3 pr-1 py-2 text-xs text-left"
              >
                <Palette size={11} className="shrink-0" />
                <span className="flex-1 truncate">{l.name}</span>
                {l.tags.length ? (
                  <span className={`shrink-0 ${value === l.file ? "text-amber-100/80" : "text-gray-500"}`}>
                    {l.tags.join(" ")}
                  </span>
                ) : null}
              </button>
              <button
                type="button"
                onClick={(e) => toggleFavourite(e, l)}
                title={l.favourite ? "Unfavourite" : "Favourite"}
                className={`shrink-0 p-0.5 mr-2 rounded hover:bg-black/20 ${l.favourite ? "text-amber-400" : "text-gray-500"}`}
              >
                <Star size={11} fill={l.favourite ? "currentColor" : "none"} />
              </button>
            </div>
          ))}
          </div>
        </div>
      )}
      </div>
    </div>
  );
}
