/**
 * A non-video timeline lane (music, text, image).
 *
 * Phase 2 renders these read-only — the geometry and the placement rules land
 * now so Phase 3 (text) and Phase 4 (audio) only have to add drag handlers, not
 * re-litigate the timeline layout.
 */

import type { ElementType } from "react";

export interface LayerItem {
  id: string;
  label: string;
  start_s: number;
  end_s: number;
}

export interface LayerRowProps {
  icon: ElementType;
  name: string;
  items: LayerItem[];
  pxPerSecond: number;
  /** Timeline width in px — a full-length lane (music) spans it. */
  widthPx: number;
  accent: string;
  /** Shown greyed when the lane exists but carries nothing yet. */
  emptyHint?: string;
  /** Optional selection — lanes whose items are editable (text, image). Omitted
   *  for music, whose single item is owned by the Audio tab, not the lane. */
  selectedId?: string | null;
  onSelectItem?: (id: string) => void;
}

export function LayerRow({
  icon: Icon, name, items, pxPerSecond, widthPx, accent, emptyHint,
  selectedId, onSelectItem,
}: LayerRowProps) {
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 shrink-0 flex items-center gap-1.5 text-[11px] text-gray-400">
        <Icon className="w-3.5 h-3.5" />
        {name}
      </div>
      <div className="relative h-7 flex-1" style={{ minWidth: widthPx }}>
        <div className="absolute inset-0 rounded bg-white/[0.02] ring-1 ring-white/5" />
        {items.length === 0 && emptyHint && (
          <div className="absolute inset-0 flex items-center pl-2 text-[10px] text-gray-600">
            {emptyHint}
          </div>
        )}
        {items.map((item) => (
          <div
            key={item.id}
            title={`${item.label} · ${item.start_s.toFixed(1)}–${item.end_s.toFixed(1)}s`}
            onClick={onSelectItem ? () => onSelectItem(item.id) : undefined}
            style={{
              left: item.start_s * pxPerSecond,
              width: Math.max(12, (item.end_s - item.start_s) * pxPerSecond),
            }}
            className={`absolute top-1 bottom-1 rounded px-1.5 text-[10px] leading-5
                        truncate ring-1 ${accent}
                        ${onSelectItem ? "cursor-pointer" : ""}
                        ${selectedId === item.id ? "ring-2 ring-white/60" : ""}`}
          >
            {item.label}
          </div>
        ))}
      </div>
    </div>
  );
}
