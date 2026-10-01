import { useState } from "react";
import { Link } from "react-router-dom";
import { Star } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { toast } from "sonner";
import type { AssetItem, AssetListResponse, AssetType } from "@/types/assets";

function stem(filename: string): string {
  return filename.replace(/\.[^.]+$/, "");
}

function findByFilename(assets: AssetItem[], filename: string | undefined | null): AssetItem | undefined {
  if (!filename) return undefined;
  return assets.find((a) => a.filename === filename || stem(a.filename) === stem(filename));
}

interface Props {
  /** Bare filename stored on the post/media row (e.g. media.licensed_music). */
  filename: string | null | undefined;
  type: Extract<AssetType, "music" | "lut">;
  icon: string;              // emoji shown before the resolved name
  /** Show the inline favourite-star + usage-count badge (music only, per spec). */
  showActions?: boolean;
}

/**
 * Resolves a post/media's stored asset filename against the assets library
 * (GET /api/assets/all?type=...) and renders "<icon> <name>" linking to the
 * Assets page, with an optional favourite toggle + usage-count badge.
 * Renders nothing when there's no match (no broken/placeholder row) — e.g. no
 * filename stored, or the asset was deleted/renamed since the reel was built.
 */
export function AssetResolvedChip({ filename, type, icon, showActions = false }: Props) {
  const { data, setData } = useApi<AssetListResponse>(filename ? `/assets/all?type=${type}` : null);
  const [pending, setPending] = useState(false);
  const asset = findByFilename(data?.assets ?? [], filename);

  if (!asset) return null;

  const toggleFavourite = async () => {
    const next = !asset.favourite;
    setPending(true);
    setData(data ? { assets: data.assets.map((a) => (a.id === asset.id ? { ...a, favourite: next } : a)) } : data);
    try {
      await api.put(`/assets/all/${asset.id}`, { favourite: next });
    } catch {
      setData(data ? { assets: data.assets.map((a) => (a.id === asset.id ? { ...a, favourite: !next } : a)) } : data);
      toast.error("Failed to update favourite");
    } finally {
      setPending(false);
    }
  };

  return (
    <span className="inline-flex items-center gap-1 min-w-0">
      <span className="shrink-0">{icon}</span>
      <Link
        to={`/assets?type=${type}`}
        className="truncate hover:text-gray-200 hover:underline"
        title={asset.name}
      >
        {asset.name}
      </Link>
      {showActions && (
        <>
          <button
            type="button"
            onClick={toggleFavourite}
            disabled={pending}
            title={asset.favourite ? "Unfavourite" : "Favourite"}
            className="shrink-0 text-gray-500 hover:text-amber-400 disabled:opacity-40"
          >
            <Star size={11} fill={asset.favourite ? "currentColor" : "none"} className={asset.favourite ? "text-amber-400" : ""} />
          </button>
          <span className="shrink-0 text-[10px] text-gray-600">used {asset.usage_count}×</span>
        </>
      )}
    </span>
  );
}
