import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Music2, Type, Palette, Film, Clapperboard, Trash2, RefreshCw, Loader2,
  AlertTriangle, CheckCircle, X, CloudOff, Info, Search, Star,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { AssetUploadPanel } from "@/components/assets/AssetUploadPanel";
import { TrackCard } from "@/components/audio/TrackCard";
import type { AudioListResponse, RefreshPreview, Track } from "@/types/audio";
import type { AssetItem, AssetListResponse, AssetSyncPreview, AssetType } from "@/types/assets";

const MEDIA_ORIGIN = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/api\/?$/, "");
const assetSrc = (url: string | null | undefined) => (url ? (url.startsWith("http") ? url : `${MEDIA_ORIGIN}${url}`) : "");

const CARD_STYLE = {
  background: "linear-gradient(145deg, rgba(17,19,31,1) 0%, rgba(10,10,16,1) 100%)",
  border: "1px solid rgba(255,255,255,0.06)",
  boxShadow: "0 4px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)",
} as const;

const SELECT_STYLE = {
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
} as const;

const BTN_GHOST = "flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-xl cursor-pointer transition-all duration-200 disabled:opacity-40";

function fmtBytes(bytes: number | null): string {
  if (bytes == null) return "—";
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${(bytes / 1024).toFixed(0)} KB`;
}

interface TabDef {
  key: AssetType;
  label: string;
  icon: LucideIcon;
}

const ASSET_TABS: TabDef[] = [
  { key: "music", label: "Music", icon: Music2 },
  { key: "font", label: "Fonts", icon: Type },
  { key: "lut", label: "LUTs", icon: Palette },
  { key: "intro", label: "Intros", icon: Film },
  { key: "outro", label: "Outros", icon: Clapperboard },
];

// Upload targets that already exist on the backend (Phase 4). Fonts/LUTs have
// no upload route — those types are populated via Sync (reconcile) only,
// per the plan's "rows populated by reconcile, not solely admin-upload".
const UPLOAD_CONFIG: Partial<Record<AssetType, { endpoint: string; accept: string; acceptLabel: string; fileFilter: (f: File) => boolean }>> = {
  music: {
    endpoint: "/audio/upload",
    accept: "audio/*",
    acceptLabel: "mp3 · m4a · wav",
    fileFilter: (f) => f.type.startsWith("audio/") || /\.(mp3|m4a|wav|ogg|flac)$/i.test(f.name),
  },
  intro: {
    endpoint: "/assets/intros/upload",
    accept: "video/*,image/*",
    acceptLabel: "mp4 · mov · m4v · jpg · png (max 50 MB)",
    fileFilter: (f) => /\.(mp4|mov|m4v|jpe?g|png)$/i.test(f.name),
  },
  outro: {
    endpoint: "/assets/outros/upload",
    accept: "video/*,image/*",
    acceptLabel: "mp4 · mov · m4v · jpg · png (max 50 MB)",
    fileFilter: (f) => /\.(mp4|mov|m4v|jpe?g|png)$/i.test(f.name),
  },
};

// Shared toolbar sort options — each type's comparator picks whichever field
// makes sense for its own shape (see sortTracks/sortAssets below).
type ToolbarSort = "favourite" | "recent" | "usage" | "name" | "date";

const SORT_OPTIONS: { key: ToolbarSort; label: string }[] = [
  { key: "favourite", label: "Favourite first" },
  { key: "recent", label: "Recently used" },
  { key: "usage", label: "Most used" },
  { key: "name", label: "Name (A-Z)" },
  { key: "date", label: "Date added" },
];

function sortTracks(list: Track[], sort: ToolbarSort): Track[] {
  const arr = [...list];
  switch (sort) {
    case "favourite":
      arr.sort((a, b) => Number(b.favourite) - Number(a.favourite));
      break;
    case "recent":
      arr.sort((a, b) => new Date(b.last_used_at ?? 0).getTime() - new Date(a.last_used_at ?? 0).getTime());
      break;
    case "usage":
      arr.sort((a, b) => b.usage_count - a.usage_count);
      break;
    case "name":
    case "date":
      // Track has no created_at — "Date added" falls back to title sort.
      arr.sort((a, b) => a.title.localeCompare(b.title));
      break;
  }
  return arr;
}

function sortAssets(list: AssetItem[], sort: ToolbarSort): AssetItem[] {
  const arr = [...list];
  switch (sort) {
    case "favourite":
      arr.sort((a, b) => Number(b.favourite) - Number(a.favourite));
      break;
    case "recent":
      arr.sort((a, b) => new Date(b.last_used_at ?? 0).getTime() - new Date(a.last_used_at ?? 0).getTime());
      break;
    case "usage":
      arr.sort((a, b) => b.usage_count - a.usage_count);
      break;
    case "name":
      arr.sort((a, b) => a.name.localeCompare(b.name));
      break;
    case "date":
      arr.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      break;
  }
  return arr;
}

function AssetPreview({ asset }: { asset: AssetItem }) {
  const src = assetSrc(asset.url);

  if (asset.type === "font") {
    const family = `asset-font-${asset.id.replace(/[^a-zA-Z0-9_-]/g, "")}`;
    return (
      <div
        className="rounded-xl px-3 flex items-center justify-center overflow-hidden"
        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", height: 72 }}
      >
        {src && <style>{`@font-face { font-family: "${family}"; src: url("${src}"); font-display: swap; }`}</style>}
        <span
          style={{ fontFamily: src ? `"${family}", sans-serif` : undefined }}
          className="text-lg text-gray-100 text-center truncate w-full"
        >
          The quick brown fox
        </span>
      </div>
    );
  }

  if (asset.type === "lut") {
    return (
      <div
        className="rounded-xl flex items-center justify-center"
        style={{ height: 72, background: "linear-gradient(90deg, #f59e0b, #ec4899, #6366f1)", opacity: 0.85 }}
      >
        <Palette size={20} className="text-white/90" />
      </div>
    );
  }

  // intro / outro — video or still image, 9:16-ish preview tile.
  const isImage = /\.(jpe?g|png)$/i.test(asset.filename);
  return (
    <div className="rounded-xl overflow-hidden bg-black/40 flex items-center justify-center" style={{ maxHeight: 180, aspectRatio: "9 / 16" }}>
      {!src ? (
        <CloudOff size={20} className="text-gray-700" />
      ) : isImage ? (
        <img src={src} alt={asset.name} className="w-full h-full object-cover" />
      ) : (
        <video
          src={src}
          muted
          loop
          playsInline
          className="w-full h-full object-cover"
          onMouseEnter={(e) => { void e.currentTarget.play(); }}
          onMouseLeave={(e) => { e.currentTarget.pause(); e.currentTarget.currentTime = 0; }}
        />
      )}
    </div>
  );
}

function AssetMetaChips({ asset }: { asset: AssetItem }) {
  const chips: string[] = [];
  const meta = asset.meta ?? {};
  if (asset.type === "lut") {
    const tags = Array.isArray(meta.tags) ? (meta.tags as unknown[]).filter((t) => typeof t === "string") as string[] : [];
    const categories = Array.isArray(meta.categories) ? (meta.categories as unknown[]).filter((p) => typeof p === "string") as string[] : [];
    chips.push(...tags, ...categories.map((p) => p.replace("_", " ")));
    if (typeof meta.intensity === "number") chips.push(`intensity ${meta.intensity}`);
  }
  if ((asset.type === "intro" || asset.type === "outro") && typeof meta.category === "string") {
    chips.push(meta.category);
  }
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {chips.map((c, i) => (
        <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">{c}</span>
      ))}
    </div>
  );
}

function AssetCard({
  asset, onChanged,
}: {
  asset: AssetItem;
  onChanged: (updated: AssetItem | null, removedId?: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(asset.name);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [rowErr, setRowErr] = useState<string | null>(null);

  useEffect(() => setName(asset.name), [asset.name]);

  const saveName = async () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === asset.name) {
      setName(asset.name);
      setEditing(false);
      return;
    }
    setSaving(true);
    setRowErr(null);
    try {
      // PUT /assets/all/{id} wraps the row as {asset: AssetItem} (matches
      // GET /assets/all/{id}'s shape), unlike /audio/{id} which returns the
      // Track bare — unwrap here rather than changing the shared AssetItem type.
      const res = await api.put<{ asset: AssetItem }>(`/assets/all/${asset.id}`, { name: trimmed });
      onChanged(res.asset);
      setEditing(false);
    } catch (e) {
      setRowErr(e instanceof Error ? e.message : "Rename failed");
    } finally {
      setSaving(false);
    }
  };

  const del = async () => {
    if (!confirm(`Delete "${asset.name}"? This removes the Storage object and DB row (the local file, if any, is kept).`)) return;
    setDeleting(true);
    try {
      await api.delete(`/assets/all/${asset.id}`);
      onChanged(null, asset.id);
    } catch (e) {
      setRowErr(e instanceof Error ? e.message : "Delete failed");
      setDeleting(false);
    }
  };

  return (
    <div className="rounded-2xl p-4 flex flex-col gap-3" style={CARD_STYLE}>
      <AssetPreview asset={asset} />

      <div className="flex items-center gap-2 min-w-0">
        {editing ? (
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => void saveName()}
            onKeyDown={(e) => {
              if (e.key === "Enter") void saveName();
              if (e.key === "Escape") { setName(asset.name); setEditing(false); }
            }}
            className="flex-1 min-w-0 bg-transparent border-b border-indigo-500/50 text-sm font-semibold text-white outline-none"
          />
        ) : (
          <button
            onClick={() => setEditing(true)}
            title="Click to rename"
            className="min-w-0 flex-1 text-left text-sm font-semibold text-white truncate hover:text-indigo-300 transition-colors cursor-text"
          >
            {asset.name}
          </button>
        )}
        {saving && <Loader2 size={13} className="animate-spin text-gray-500 shrink-0" />}
      </div>

      <div className="flex items-center gap-2 text-[11px] text-gray-600 flex-wrap">
        <span className="truncate font-mono">{asset.filename}</span>
        <span>·</span>
        <span>{fmtBytes(asset.size_bytes)}</span>
        {!asset.local_exists && (
          <span className="flex items-center gap-1 text-amber-400" title="Not present on local disk — served from Storage public URL only">
            <CloudOff size={11} /> storage-only
          </span>
        )}
      </div>

      <AssetMetaChips asset={asset} />

      {asset.parent_asset_id && (
        <div className="text-[10px] text-gray-600 truncate" title={asset.parent_asset_id}>
          derived from <span className="font-mono">{asset.parent_asset_id}</span>
        </div>
      )}

      {rowErr && (
        <div className="flex items-center gap-1.5 text-[11px] text-red-400">
          <AlertTriangle size={11} className="shrink-0" /> <span className="truncate">{rowErr}</span>
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-1 border-t border-white/[0.05] mt-1">
        <button
          onClick={() => void del()}
          disabled={deleting}
          className="p-1.5 rounded-lg cursor-pointer transition-colors hover:bg-red-500/10 disabled:opacity-40"
          title="Delete"
        >
          {deleting ? <Loader2 size={13} className="animate-spin text-gray-500" /> : <Trash2 size={13} className="text-gray-600 hover:text-red-400" />}
        </button>
      </div>
    </div>
  );
}

export function AssetsPage() {
  // Deep-link support: /assets?type=intro lands directly on the Intros tab
  // (used by IntroSection.tsx's "Upload" link — falls back to Music otherwise).
  const [searchParams] = useSearchParams();
  const initialType = searchParams.get("type");
  const [activeTab, setActiveTab] = useState<AssetType>(
    ASSET_TABS.some((t) => t.key === initialType) ? (initialType as AssetType) : "music",
  );
  const [activeSubTab, setActiveSubTab] = useState<"library" | "upload">("library");

  // Reset the library/upload sub-tab whenever the asset type changes.
  useEffect(() => setActiveSubTab("library"), [activeTab]);

  const { data: categoriesResp } = useApi<{ categories: string[] }>("/taxonomy/categories");
  const categories = categoriesResp?.categories ?? [];

  // Music keeps using the richer /audio Track shape (favourite/categories/usage
  // stats) so TrackCard/CategoryEditor/WaveformTrimModal work unchanged. The
  // other four types are simple AssetItem rows from the new unified index.
  const musicQuery = useApi<AudioListResponse>(activeTab === "music" ? "/audio" : null);
  const genericQuery = useApi<AssetListResponse>(activeTab !== "music" ? `/assets/all?type=${activeTab}` : null);

  const tracks = musicQuery.data?.tracks ?? [];
  const assets = genericQuery.data?.assets ?? [];

  // --- Toolbar: search / sort / favourites-only / tag(+category) chips -----
  // All narrowing is client-side over the already-fetched list; no new query
  // params are sent to /audio or /assets/all.
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<ToolbarSort>("recent");
  const [favouritesOnly, setFavouritesOnly] = useState(false);
  const [chipFilter, setChipFilter] = useState<string[]>([]);

  // Chip selections don't necessarily carry meaning across tabs — clear them
  // (and the banner-adjacent sync state) whenever the asset type changes.
  useEffect(() => setChipFilter([]), [activeTab]);

  const toggleChip = (c: string) =>
    setChipFilter((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));

  const availableChips = useMemo(() => {
    const set = new Set<string>();
    if (activeTab === "music") {
      tracks.forEach((t) => (t.categories ?? []).forEach((p) => set.add(p)));
    } else {
      assets.forEach((a) => {
        (a.tags ?? []).forEach((t) => set.add(t));
      });
    }
    return Array.from(set).sort();
  }, [activeTab, tracks, assets]);

  const q = search.trim().toLowerCase();

  const filteredTracks = useMemo(() => {
    const filtered = tracks.filter((t) => {
      const matchSearch = !q || t.title.toLowerCase().includes(q) || (t.categories ?? []).some((p) => p.toLowerCase().includes(q));
      const matchFav = !favouritesOnly || t.favourite;
      const matchChips = chipFilter.length === 0 || (t.categories ?? []).some((p) => chipFilter.includes(p));
      return matchSearch && matchFav && matchChips;
    });
    return sortTracks(filtered, sort);
  }, [tracks, q, favouritesOnly, chipFilter, sort]);

  const filteredAssets = useMemo(() => {
    const filtered = assets.filter((a) => {
      const haystack = `${a.name} ${a.filename}`.toLowerCase();
      const matchSearch = !q || haystack.includes(q)
        || (a.tags ?? []).some((t) => t.toLowerCase().includes(q));
      const matchFav = !favouritesOnly || a.favourite;
      const matchChips = chipFilter.length === 0
        || (a.tags ?? []).some((t) => chipFilter.includes(t));
      return matchSearch && matchFav && matchChips;
    });
    return sortAssets(filtered, sort);
  }, [assets, q, favouritesOnly, chipFilter, sort]);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [playDuration, setPlayDuration] = useState(0);
  useEffect(() => () => { audioRef.current?.pause(); }, []);

  const onTogglePlay = useCallback((t: Track) => {
    if (playingId === t.id) {
      audioRef.current?.pause();
      setPlayingId(null);
      return;
    }
    if (!t.url) return;
    if (!audioRef.current) audioRef.current = new Audio();
    const audio = audioRef.current;
    audio.pause();
    audio.src = assetSrc(t.url);
    setCurrentTime(0);
    setPlayDuration(0);
    audio.ontimeupdate = () => setCurrentTime(audio.currentTime);
    audio.onloadedmetadata = () => setPlayDuration(audio.duration);
    audio.onended = () => setPlayingId(null);
    audio.play().then(() => setPlayingId(t.id)).catch(() => setPlayingId(null));
  }, [playingId]);

  const onTrackChanged = useCallback((updated: Track | null, removedId?: string) => {
    const data = musicQuery.data;
    musicQuery.setData(data ? {
      tracks: removedId
        ? data.tracks.filter((t) => t.id !== removedId)
        : data.tracks.map((t) => (t.id === updated!.id ? updated! : t)),
    } : data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [musicQuery.data]);

  const onAssetChanged = useCallback((updated: AssetItem | null, removedId?: string) => {
    const data = genericQuery.data;
    genericQuery.setData(data ? {
      assets: removedId
        ? data.assets.filter((a) => a.id !== removedId)
        : data.assets.map((a) => (a.id === updated!.id ? updated! : a)),
    } : data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genericQuery.data]);

  // Two-step sync (reconcile) — mirrors the old Audio.tsx's refresh preview/confirm
  // banner, generalized to whichever asset type tab is active. Indexes Storage
  // bucket + local disk contents into the `assets` table.
  const [syncing, setSyncing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [preview, setPreview] = useState<AssetSyncPreview | null>(null);
  const [syncErr, setSyncErr] = useState<string | null>(null);
  const [syncDone, setSyncDone] = useState<string | null>(null);

  // Preview state is per-asset-type; switching tabs clears any stale banner.
  useEffect(() => {
    setPreview(null);
    setSyncErr(null);
    setSyncDone(null);
  }, [activeTab]);

  const runPreview = useCallback(async () => {
    setSyncing(true);
    setSyncErr(null);
    setSyncDone(null);
    try {
      const res = await api.post<AssetSyncPreview>(`/assets/sync?type=${activeTab}&confirm=false`);
      setPreview(res);
    } catch (e) {
      setSyncErr(e instanceof Error ? e.message : "Sync scan failed");
    } finally {
      setSyncing(false);
    }
  }, [activeTab]);

  const confirmSync = useCallback(async () => {
    setConfirming(true);
    setSyncErr(null);
    try {
      await api.post<AssetSyncPreview>(`/assets/sync?type=${activeTab}&confirm=true`);
      setPreview(null);
      setSyncDone("Synced — new files indexed, stale rows pruned.");
      if (activeTab === "music") musicQuery.refetch();
      else genericQuery.refetch();
    } catch (e) {
      setSyncErr(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setConfirming(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  // Music-only "Refresh" — dedupes local files under assets/music/ and prunes
  // orphaned cache entries. Different from Sync above (which reconciles the
  // Storage bucket); both are useful for music so both are shown on that tab.
  const [refreshing, setRefreshing] = useState(false);
  const [refreshConfirming, setRefreshConfirming] = useState(false);
  const [refreshPreview, setRefreshPreview] = useState<RefreshPreview | null>(null);
  const [refreshErr, setRefreshErr] = useState<string | null>(null);
  const [refreshDone, setRefreshDone] = useState<string | null>(null);

  useEffect(() => {
    setRefreshPreview(null);
    setRefreshErr(null);
    setRefreshDone(null);
  }, [activeTab]);

  const runRefreshPreview = useCallback(async () => {
    setRefreshing(true);
    setRefreshErr(null);
    setRefreshDone(null);
    try {
      const res = await api.post<RefreshPreview>("/audio/refresh?confirm=false");
      setRefreshPreview(res);
    } catch (e) {
      setRefreshErr(e instanceof Error ? e.message : "Refresh scan failed");
    } finally {
      setRefreshing(false);
    }
  }, []);

  const confirmRefreshCleanup = useCallback(async () => {
    setRefreshConfirming(true);
    setRefreshErr(null);
    try {
      await api.post<RefreshPreview>("/audio/refresh?confirm=true");
      setRefreshPreview(null);
      setRefreshDone("Library refreshed — new files indexed, duplicates cleaned up.");
      musicQuery.refetch();
    } catch (e) {
      setRefreshErr(e instanceof Error ? e.message : "Cleanup failed");
    } finally {
      setRefreshConfirming(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const uploadConfig = UPLOAD_CONFIG[activeTab];
  const activeTabDef = useMemo(() => ASSET_TABS.find((t) => t.key === activeTab)!, [activeTab]);

  const loading = activeTab === "music" ? musicQuery.loading : genericQuery.loading;
  const error = activeTab === "music" ? musicQuery.error : genericQuery.error;
  const count = activeTab === "music" ? tracks.length : assets.length;

  const onUploaded = useCallback(() => {
    if (activeTab === "music") musicQuery.refetch();
    else genericQuery.refetch();
    setActiveSubTab("library");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  return (
    <div className="space-y-5 px-1">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold tracking-tight">Assets</h2>
          <span className="text-xs text-gray-600 font-medium tracking-widest uppercase mt-0.5">
            Music · Fonts · LUTs · Intros · Outros
          </span>
        </div>
        <div className="flex items-center gap-2">
          {activeTab === "music" && (
            <button
              onClick={() => void runRefreshPreview()}
              disabled={refreshing}
              className={BTN_GHOST}
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#9ca3af" }}
              title="Dedupe local files under assets/music/ and prune orphaned cache entries"
            >
              <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
              Refresh
            </button>
          )}
          <button
            onClick={() => void runPreview()}
            disabled={syncing}
            className={BTN_GHOST}
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#9ca3af" }}
            title="Reconcile the Storage bucket + local disk into the assets table"
          >
            <RefreshCw size={13} className={syncing ? "animate-spin" : ""} />
            Sync
          </button>
        </div>
      </div>

      {/* Sync preview → confirm banner */}
      <AnimatePresence>
        {preview && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="rounded-2xl p-4 space-y-2.5 text-sm"
            style={{ background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.2)" }}
          >
            <div className="flex items-center gap-2 text-amber-300 font-medium">
              <AlertTriangle size={14} /> Sync preview — nothing changed yet
            </div>
            <div className="text-xs text-gray-400 space-y-1">
              <p>{preview.added_count} new asset{preview.added_count === 1 ? "" : "s"} found (local disk and/or Storage bucket).</p>
              <p>{preview.updated_count} existing row{preview.updated_count === 1 ? "" : "s"} would be refreshed (size/checksum changed).</p>
              <p>{preview.removed_count} row{preview.removed_count === 1 ? "" : "s"} point to files gone from both local disk and Storage — would be pruned.</p>
            </div>
            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={() => void confirmSync()}
                disabled={confirming}
                className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg cursor-pointer transition-all disabled:opacity-40"
                style={{ background: "rgba(16,185,129,0.15)", border: "1px solid rgba(16,185,129,0.3)", color: "#6ee7b7" }}
              >
                {confirming ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
                Confirm sync
              </button>
              <button
                onClick={() => setPreview(null)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg cursor-pointer text-gray-400 hover:text-gray-200"
              >
                <X size={12} /> Dismiss
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {syncErr && (
        <div className="flex items-center gap-2 p-3 rounded-xl text-sm" style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#fca5a5" }}>
          <AlertTriangle size={14} /> {syncErr}
        </div>
      )}
      {syncDone && !preview && (
        <div className="flex items-center gap-2 p-3 rounded-xl text-sm" style={{ background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.2)", color: "#6ee7b7" }}>
          <CheckCircle size={14} /> {syncDone}
        </div>
      )}

      {/* Refresh (dedup/orphan-prune) preview → confirm banner — music only */}
      {activeTab === "music" && (
        <>
          <AnimatePresence>
            {refreshPreview && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                className="rounded-2xl p-4 space-y-2.5 text-sm"
                style={{ background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.2)" }}
              >
                <div className="flex items-center gap-2 text-amber-300 font-medium">
                  <AlertTriangle size={14} /> Refresh preview — nothing changed yet
                </div>
                <div className="text-xs text-gray-400 space-y-1">
                  <p>{refreshPreview.new_files.length} new file{refreshPreview.new_files.length === 1 ? "" : "s"} found in assets/music/.</p>
                  <p>{refreshPreview.dup_groups.length} duplicate group{refreshPreview.dup_groups.length === 1 ? "" : "s"} detected — {refreshPreview.would_delete_count} file{refreshPreview.would_delete_count === 1 ? "" : "s"} would be deleted.</p>
                  <p>{refreshPreview.orphaned_count} cached track{refreshPreview.orphaned_count === 1 ? "" : "s"} point to files no longer on disk — would be removed from the library.</p>
                </div>
                <div className="flex items-center gap-2 pt-1">
                  <button
                    onClick={() => void confirmRefreshCleanup()}
                    disabled={refreshConfirming}
                    className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg cursor-pointer transition-all disabled:opacity-40"
                    style={{ background: "rgba(16,185,129,0.15)", border: "1px solid rgba(16,185,129,0.3)", color: "#6ee7b7" }}
                  >
                    {refreshConfirming ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
                    Confirm cleanup
                  </button>
                  <button
                    onClick={() => setRefreshPreview(null)}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg cursor-pointer text-gray-400 hover:text-gray-200"
                  >
                    <X size={12} /> Dismiss
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {refreshErr && (
            <div className="flex items-center gap-2 p-3 rounded-xl text-sm" style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#fca5a5" }}>
              <AlertTriangle size={14} /> {refreshErr}
            </div>
          )}
          {refreshDone && !refreshPreview && (
            <div className="flex items-center gap-2 p-3 rounded-xl text-sm" style={{ background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.2)", color: "#6ee7b7" }}>
              <CheckCircle size={14} /> {refreshDone}
            </div>
          )}
        </>
      )}

      {/* Asset type tabs */}
      <div className="flex gap-1 flex-wrap">
        {ASSET_TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-semibold uppercase tracking-wider transition-colors cursor-pointer rounded-t-lg border-b-2 ${
              activeTab === key ? "text-white border-indigo-500 bg-white/[0.03]" : "text-gray-600 border-transparent hover:text-gray-400"
            }`}
          >
            <Icon size={13} /> {label}
          </button>
        ))}
      </div>

      {/* Library / Upload panel */}
      <div className="rounded-2xl overflow-hidden" style={CARD_STYLE}>
        <div className="flex border-b border-white/5">
          {(["library", "upload"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveSubTab(tab)}
              className={`px-5 py-3 text-xs font-semibold uppercase tracking-wider transition-colors cursor-pointer ${
                activeSubTab === tab ? "text-white border-b-2 border-indigo-500 bg-white/[0.03]" : "text-gray-600 hover:text-gray-400"
              }`}
            >
              {tab === "library" ? "Library" : "Upload"}
            </button>
          ))}
        </div>

        <div className="p-5">
          {activeSubTab === "library" && (
            <>
              {/* Search / sort / favourites / tag chips toolbar — shared across all tabs */}
              <div className="flex flex-col gap-2 mb-4">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="relative">
                    <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
                    <input
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="Search…"
                      className="pl-7 pr-2.5 py-2 rounded-lg text-xs text-gray-200 placeholder:text-gray-600 focus:outline-none w-40"
                      style={SELECT_STYLE}
                    />
                  </div>

                  <select
                    value={sort}
                    onChange={(e) => setSort(e.target.value as ToolbarSort)}
                    className="rounded-lg px-2.5 py-2 text-xs text-gray-300 focus:outline-none cursor-pointer"
                    style={SELECT_STYLE}
                  >
                    {SORT_OPTIONS.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
                  </select>

                  <button
                    onClick={() => setFavouritesOnly((v) => !v)}
                    className={`flex items-center gap-1.5 text-xs px-2.5 py-2 rounded-lg cursor-pointer transition-colors ${
                      favouritesOnly ? "text-amber-300" : "text-gray-400 hover:text-gray-200"
                    }`}
                    style={{
                      background: favouritesOnly ? "rgba(245,158,11,0.12)" : "rgba(255,255,255,0.04)",
                      border: favouritesOnly ? "1px solid rgba(245,158,11,0.3)" : "1px solid rgba(255,255,255,0.08)",
                    }}
                  >
                    <Star size={12} className={favouritesOnly ? "fill-amber-400" : ""} /> Favourites only
                  </button>

                  <span className="text-[11px] text-gray-600 ml-auto">
                    {count} <activeTabDef.icon size={11} className="inline -mt-0.5" /> {activeTabDef.label.toLowerCase()}
                  </span>
                </div>

                {availableChips.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {availableChips.map((c) => {
                      const on = chipFilter.includes(c);
                      return (
                        <button
                          key={c}
                          type="button"
                          onClick={() => toggleChip(c)}
                          className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                            on ? "bg-indigo-600 border-indigo-500 text-white" : "bg-gray-900 border-gray-700 text-gray-400 hover:border-gray-500"
                          }`}
                        >
                          {c.replace("_", " ")}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {loading && <p className="text-sm text-gray-600 py-4 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</p>}
              {error && (
                <div className="flex items-center gap-2 p-3 rounded-xl text-sm" style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#fca5a5" }}>
                  <AlertTriangle size={14} /> {error}
                </div>
              )}
              {!loading && !error && count === 0 && (
                <div className="flex flex-col items-center gap-2 py-10 text-gray-600">
                  <activeTabDef.icon size={22} />
                  <p className="text-sm">No {activeTabDef.label.toLowerCase()} indexed yet — try Sync above.</p>
                </div>
              )}

              {!loading && !error && count > 0 && activeTab === "music" && filteredTracks.length === 0 && (
                <div className="flex flex-col items-center gap-2 py-10 text-gray-600">
                  <Music2 size={22} />
                  <p className="text-sm">No tracks match your filters.</p>
                </div>
              )}
              {!loading && !error && count > 0 && activeTab !== "music" && filteredAssets.length === 0 && (
                <div className="flex flex-col items-center gap-2 py-10 text-gray-600">
                  <activeTabDef.icon size={22} />
                  <p className="text-sm">No {activeTabDef.label.toLowerCase()} match your filters.</p>
                </div>
              )}

              {!loading && activeTab === "music" && filteredTracks.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {filteredTracks.map((t) => (
                    <TrackCard
                      key={t.id}
                      track={t}
                      categories={categories}
                      playingId={playingId}
                      currentTime={currentTime}
                      duration={playDuration}
                      onTogglePlay={onTogglePlay}
                      onChanged={onTrackChanged}
                    />
                  ))}
                </div>
              )}

              {!loading && activeTab !== "music" && filteredAssets.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  {filteredAssets.map((a) => (
                    <AssetCard key={a.id} asset={a} onChanged={onAssetChanged} />
                  ))}
                </div>
              )}
            </>
          )}

          {activeSubTab === "upload" && (
            uploadConfig ? (
              <AssetUploadPanel
                endpoint={uploadConfig.endpoint}
                accept={uploadConfig.accept}
                acceptLabel={uploadConfig.acceptLabel}
                fileFilter={uploadConfig.fileFilter}
                onUploaded={onUploaded}
              />
            ) : (
              <div className="flex items-start gap-2.5 p-4 rounded-xl text-sm text-gray-400" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <Info size={15} className="shrink-0 mt-0.5 text-gray-500" />
                <span>
                  Uploading {activeTabDef.label.toLowerCase()} isn&apos;t wired up from this page yet — add files to the local
                  <code className="mx-1 px-1 py-0.5 rounded bg-black/30 text-[11px]">assets/{activeTab === "font" ? "fonts" : "luts"}/</code>
                  directory (or the Storage bucket), then use <span className="text-gray-300 font-medium">Sync</span> above to index them.
                </span>
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
}
