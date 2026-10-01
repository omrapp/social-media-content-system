/**
 * Image / sticker-layer inspector (Phase 5).
 *
 * Mirrors TextLayerPanel: a picker at the top, then the selected layer's
 * geometry. Positions are normalized 0–1 and stay that way into the render —
 * `editor_layers` multiplies by the canvas, so a sticker sits in the exported
 * reel exactly where the preview put it. x/y are the layer's CENTRE.
 *
 * Every control clamps to the range editor_edl.py enforces — x/y/opacity 0–1,
 * z 0–99, and w/h STRICTLY >0 (hence the sliders' 0.02 floor: pydantic declares
 * them `gt=0.0`, so a zero width would 400 the save) — meaning the panel cannot
 * build a doc the backend will reject.
 *
 * `assets/stickers/` ships EMPTY — there is no built-in set — so the empty state
 * points at the upload button instead of implying the fetch failed.
 */

import { useCallback, useRef, useState } from "react";
import { Image as ImageIcon, Loader2, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";

import { API_ORIGIN } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { useApi } from "@/hooks/useApi";
import type { ImageLayer, StickerAsset, StickerListResponse, StickerUploadResponse } from "@/types/editor";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

/** Backend cap; mirrored here only to reject the file before the round-trip. */
const MAX_UPLOAD_MB = 10;
const ACCEPT = ".png,.webp,image/png,image/webp";

export interface ImageLayerPanelProps {
  layers: ImageLayer[];
  selectedId: string | null;
  /** Reel length — the "until the end" hint comes from it. */
  totalDuration: number;
  maxLayers: number;
  onSelect: (id: string | null) => void;
  onAdd: (asset: string) => void;
  onUpdate: (id: string, patch: Partial<ImageLayer>) => void;
  onDelete: (id: string) => void;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-[11px] text-gray-400">{label}</span>
      {children}
    </div>
  );
}

const inputCls =
  "w-24 bg-gray-800 rounded px-2 py-1 text-xs text-gray-200 ring-1 ring-white/10 " +
  "focus:outline-none focus:ring-indigo-400/60";

const clamp01 = (v: number) => Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));

function stickerUrl(url: string): string {
  return url.startsWith("http") ? url : `${API_ORIGIN}${url}`;
}

/** Multipart POST with the Supabase bearer token.
 *
 *  The shared `api` wrapper always sets Content-Type: application/json, which
 *  would strip the multipart boundary, so uploads bypass it — same reason
 *  AssetUploadPanel hand-rolls its request. That panel uses XHR for progress
 *  events; a single 10 MB sticker doesn't need them, so this is plain fetch. */
async function uploadSticker(file: File): Promise<StickerAsset> {
  const { data: { session } } = await supabase.auth.getSession();
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${BASE}/assets/stickers/upload`, {
    method: "POST",
    body: fd,
    headers: session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {},
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  const json = (await res.json()) as StickerUploadResponse;
  return json.item;
}

export function ImageLayerPanel({
  layers, selectedId, totalDuration, maxLayers,
  onSelect, onAdd, onUpdate, onDelete,
}: ImageLayerPanelProps) {
  const { data, loading, refetch } = useApi<StickerListResponse>("/assets/stickers");
  const stickers = data?.stickers ?? [];

  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const layer = layers.find((l) => l.id === selectedId) ?? null;
  const atCap = layers.length >= maxLayers;

  const onFile = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // let the same file be re-picked after a failure
    if (!file) return;
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      toast.error(`${file.name} is over the ${MAX_UPLOAD_MB} MB limit`);
      return;
    }
    setUploading(true);
    try {
      const item = await uploadSticker(file);
      refetch();
      // Uploading is intent to use it: drop the layer in straight away unless
      // the doc is already at its cap.
      if (!atCap) onAdd(item.asset);
      else toast.success(`${item.name} uploaded — delete a layer to place it`);
    } catch (err) {
      toast.error(`Upload failed: ${(err as Error).message}`);
    } finally {
      setUploading(false);
    }
  }, [atCap, onAdd, refetch]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-200 flex items-center gap-1.5">
          <ImageIcon className="w-3.5 h-3.5" /> Images ({layers.length}/{maxLayers})
        </h3>
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          title={`Upload a PNG or WebP (max ${MAX_UPLOAD_MB} MB)`}
          className="px-2 py-1 rounded text-[11px] bg-white/5 hover:bg-white/10 ring-1
                     ring-white/10 text-gray-200 inline-flex items-center gap-1 disabled:opacity-40"
        >
          {uploading
            ? <Loader2 className="w-3 h-3 animate-spin" />
            : <Upload className="w-3 h-3" />}
          Upload
        </button>
        <input ref={fileRef} type="file" accept={ACCEPT} className="hidden"
               onChange={(e) => void onFile(e)} />
      </div>

      {/* ── picker ──────────────────────────────────────────────────────── */}
      {loading ? (
        <div className="flex items-center gap-2 text-[11px] text-gray-500">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading stickers…
        </div>
      ) : stickers.length === 0 ? (
        <p className="text-[11px] text-gray-500">
          No stickers yet — upload a PNG or WebP. Transparent PNGs composite
          cleanly; a JPEG would arrive as an opaque rectangle.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-1.5">
            {stickers.map((s) => (
              <button
                key={s.id}
                onClick={() => onAdd(s.asset)}
                disabled={atCap}
                title={atCap ? `Cap reached (editor.max_image_layers = ${maxLayers})` : `Add ${s.name}`}
                className="aspect-square rounded bg-white/[0.03] ring-1 ring-white/10
                           hover:ring-indigo-400/50 p-1 disabled:opacity-40
                           disabled:hover:ring-white/10"
              >
                <img
                  src={stickerUrl(s.url)} alt={s.name}
                  className="w-full h-full object-contain"
                  // Checkerboard so a white sticker isn't invisible on the dark panel.
                  style={{
                    backgroundImage:
                      "linear-gradient(45deg,#ffffff14 25%,transparent 25%,transparent 75%,#ffffff14 75%)," +
                      "linear-gradient(45deg,#ffffff14 25%,transparent 25%,transparent 75%,#ffffff14 75%)",
                    backgroundSize: "8px 8px",
                    backgroundPosition: "0 0, 4px 4px",
                  }}
                />
              </button>
            ))}
          </div>
          {atCap && (
            <p className="text-[10px] text-amber-300/80">
              Layer cap reached (<code>editor.max_image_layers</code> = {maxLayers}) —
              delete one to add another.
            </p>
          )}
        </>
      )}

      {/* ── layers on the doc ───────────────────────────────────────────── */}
      {layers.length > 0 && (
        <div className="space-y-1">
          {layers.map((l) => (
            <button
              key={l.id}
              onClick={() => onSelect(l.id === selectedId ? null : l.id)}
              className={`w-full text-left px-2 py-1 rounded text-[11px] truncate ring-1 ${
                l.id === selectedId
                  ? "bg-violet-500/20 text-violet-100 ring-violet-400/40"
                  : "bg-white/[0.03] text-gray-300 ring-white/5 hover:bg-white/[0.06]"
              }`}
            >
              z{l.z} · {l.asset.split("/").pop() ?? l.asset}
            </button>
          ))}
        </div>
      )}

      {layer && (
        <div className="divide-y divide-white/5 pt-1">
          <Row label={`X · ${(layer.x * 100).toFixed(0)}%`}>
            <input
              type="range" min={0} max={1} step={0.01} value={layer.x}
              className="w-24 accent-indigo-400"
              title="Horizontal centre of the sticker"
              onChange={(e) => onUpdate(layer.id, { x: clamp01(Number(e.target.value)) })}
            />
          </Row>
          <Row label={`Y · ${(layer.y * 100).toFixed(0)}%`}>
            <input
              type="range" min={0} max={1} step={0.01} value={layer.y}
              className="w-24 accent-indigo-400"
              title="Vertical centre of the sticker"
              onChange={(e) => onUpdate(layer.id, { y: clamp01(Number(e.target.value)) })}
            />
          </Row>

          {/* A null width is only "native" when the height is null too. With a
              height set, the render does scale=-1:h — width is derived from it,
              exactly as "auto" means on the height row. */}
          <Row
            label={
              layer.w !== null ? `Width · ${(layer.w * 100).toFixed(0)}%`
                : layer.h !== null ? "Width · auto"
                : "Width · native"
            }
          >
            <div className="flex items-center gap-2">
              <input
                type="range" min={0.02} max={1} step={0.01} value={layer.w ?? 0.3}
                className="w-16 accent-indigo-400"
                disabled={layer.w === null}
                onChange={(e) => onUpdate(layer.id, { w: clamp01(Number(e.target.value)) })}
              />
              <button
                // null on BOTH dimensions = native pixel size. Offered, but not
                // the default: a 2000px asset would overflow a 1080px canvas.
                onClick={() => onUpdate(layer.id, { w: layer.w === null ? 0.3 : null })}
                title="Use the file's own pixel size instead of a fraction of the frame"
                className={`text-[10px] px-1.5 py-0.5 rounded ring-1 ${
                  layer.w === null
                    ? "bg-indigo-500/20 text-indigo-200 ring-indigo-400/40"
                    : "bg-white/5 text-gray-400 ring-white/10 hover:bg-white/10"
                }`}
              >
                native
              </button>
            </div>
          </Row>
          <Row label={layer.h === null ? "Height · auto" : `Height · ${(layer.h * 100).toFixed(0)}%`}>
            <div className="flex items-center gap-2">
              <input
                type="range" min={0.02} max={1} step={0.01} value={layer.h ?? 0.3}
                className="w-16 accent-indigo-400"
                disabled={layer.h === null}
                onChange={(e) => onUpdate(layer.id, { h: clamp01(Number(e.target.value)) })}
              />
              <button
                // Default: height null = derived from width, preserving aspect.
                onClick={() => onUpdate(layer.id, { h: layer.h === null ? 0.3 : null })}
                title="Auto keeps the aspect ratio from the width"
                className={`text-[10px] px-1.5 py-0.5 rounded ring-1 ${
                  layer.h === null
                    ? "bg-indigo-500/20 text-indigo-200 ring-indigo-400/40"
                    : "bg-white/5 text-gray-400 ring-white/10 hover:bg-white/10"
                }`}
              >
                auto
              </button>
            </div>
          </Row>

          <Row label={`Opacity · ${(layer.opacity * 100).toFixed(0)}%`}>
            <input
              type="range" min={0} max={1} step={0.01} value={layer.opacity}
              className="w-24 accent-indigo-400"
              onChange={(e) => onUpdate(layer.id, { opacity: clamp01(Number(e.target.value)) })}
            />
          </Row>
          <Row label="Z order">
            <input
              type="number" min={0} max={99} step={1} value={layer.z} className={inputCls}
              title="Composite order, ascending — higher sits on top"
              onChange={(e) =>
                onUpdate(layer.id, { z: Math.max(0, Math.min(99, Math.round(Number(e.target.value) || 0))) })}
            />
          </Row>

          <Row label="Start (s)">
            <input
              type="number" step={0.1} min={0} value={layer.start_s.toFixed(1)} className={inputCls}
              onChange={(e) =>
                onUpdate(layer.id, { start_s: Math.max(0, Number(e.target.value) || 0) })}
            />
          </Row>
          <Row label="End (s)">
            <input
              type="number" step={0.1} min={0} value={layer.end_s.toFixed(1)} className={inputCls}
              title="0 = hold until the end of the reel"
              onChange={(e) =>
                onUpdate(layer.id, { end_s: Math.max(0, Number(e.target.value) || 0) })}
            />
          </Row>

          <div className="pt-2 flex items-center justify-between">
            <span className="text-[10px] text-gray-600">
              {layer.end_s > layer.start_s
                ? `${layer.start_s.toFixed(1)}–${layer.end_s.toFixed(1)}s`
                : `${layer.start_s.toFixed(1)}s → end (${totalDuration.toFixed(1)}s)`}
            </span>
            <button
              onClick={() => onDelete(layer.id)}
              className="px-2 py-1 rounded text-[11px] bg-rose-600/20 hover:bg-rose-600/40
                         text-rose-200 ring-1 ring-rose-400/30 inline-flex items-center gap-1"
            >
              <Trash2 className="w-3 h-3" /> Delete
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
