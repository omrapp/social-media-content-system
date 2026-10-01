/**
 * Text-layer inspector (Phase 3).
 *
 * Positions are normalized 0–1 and stay that way all the way into the render:
 * `editor_layers._position_exprs` multiplies by the canvas, so a layer sits in
 * the exported reel exactly where the preview showed it.
 */

import { Plus, Trash2, Type } from "lucide-react";

import { FontPicker } from "@/components/FontPicker";
import { MAX_TEXT_CHARS, type TextLayer } from "@/types/editor";

export interface TextLayerPanelProps {
  layers: TextLayer[];
  selectedId: string | null;
  /** Reel length — the "until the end" hint and the end-time cap come from it. */
  totalDuration: number;
  maxLayers: number;
  onSelect: (id: string | null) => void;
  onAdd: () => void;
  onUpdate: (id: string, patch: Partial<TextLayer>) => void;
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

export function TextLayerPanel({
  layers, selectedId, totalDuration, maxLayers,
  onSelect, onAdd, onUpdate, onDelete,
}: TextLayerPanelProps) {
  const layer = layers.find((l) => l.id === selectedId) ?? null;
  const atCap = layers.length >= maxLayers;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-200 flex items-center gap-1.5">
          <Type className="w-3.5 h-3.5" /> Text ({layers.length}/{maxLayers})
        </h3>
        <button
          onClick={onAdd}
          disabled={atCap}
          title={atCap ? `Cap reached (editor.max_text_layers = ${maxLayers})` : "Add a text layer"}
          className="px-2 py-1 rounded text-[11px] bg-white/5 hover:bg-white/10 ring-1
                     ring-white/10 text-gray-200 inline-flex items-center gap-1 disabled:opacity-40"
        >
          <Plus className="w-3 h-3" /> Add
        </button>
      </div>

      {layers.length === 0 && (
        <p className="text-[11px] text-gray-500">
          No text yet. Layers render on top of everything else — the grade, the
          branding bar and the intro/cast screens.
        </p>
      )}

      {layers.length > 0 && (
        <div className="space-y-1">
          {layers.map((l) => (
            <button
              key={l.id}
              onClick={() => onSelect(l.id === selectedId ? null : l.id)}
              className={`w-full text-left px-2 py-1 rounded text-[11px] truncate ring-1 ${
                l.id === selectedId
                  ? "bg-indigo-500/20 text-indigo-100 ring-indigo-400/40"
                  : "bg-white/[0.03] text-gray-300 ring-white/5 hover:bg-white/[0.06]"
              }`}
            >
              {l.content || "(empty)"}
            </button>
          ))}
        </div>
      )}

      {layer && (
        <div className="divide-y divide-white/5 pt-1">
          <div className="py-1.5">
            <textarea
              value={layer.content}
              maxLength={MAX_TEXT_CHARS}
              rows={3}
              onChange={(e) => onUpdate(layer.id, { content: e.target.value })}
              placeholder="Text to burn in"
              className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs text-gray-200
                         ring-1 ring-white/10 focus:outline-none focus:ring-indigo-400/60"
            />
            <div className="text-[10px] text-gray-600 text-right">
              {layer.content.length}/{MAX_TEXT_CHARS}
            </div>
          </div>

          <Row label="Font">
            <div className="w-40">
              <FontPicker
                value={layer.font}
                onChange={(file) => onUpdate(layer.id, { font: file })}
              />
            </div>
          </Row>
          <Row label="Size">
            <input
              type="number" min={8} max={400} value={layer.size} className={inputCls}
              onChange={(e) =>
                onUpdate(layer.id, { size: Math.max(8, Math.min(400, Number(e.target.value) || 64)) })}
            />
          </Row>
          <Row label="Colour">
            <input
              type="color" value={layer.color}
              className="w-24 h-7 bg-gray-800 rounded ring-1 ring-white/10"
              onChange={(e) => onUpdate(layer.id, { color: e.target.value })}
            />
          </Row>
          <Row label="Anchor">
            <select
              value={layer.anchor} className={inputCls}
              onChange={(e) =>
                onUpdate(layer.id, { anchor: e.target.value as TextLayer["anchor"] })}
            >
              <option value="left">left</option>
              <option value="center">center</option>
              <option value="right">right</option>
            </select>
          </Row>
          <Row label={`X · ${(layer.x * 100).toFixed(0)}%`}>
            <input
              type="range" min={0} max={1} step={0.01} value={layer.x}
              className="w-24 accent-indigo-400"
              onChange={(e) => onUpdate(layer.id, { x: Number(e.target.value) })}
            />
          </Row>
          <Row label={`Y · ${(layer.y * 100).toFixed(0)}%`}>
            <input
              type="range" min={0} max={1} step={0.01} value={layer.y}
              className="w-24 accent-indigo-400"
              onChange={(e) => onUpdate(layer.id, { y: Number(e.target.value) })}
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
          <Row label="Animation">
            <select
              value={layer.animation} className={inputCls}
              onChange={(e) =>
                onUpdate(layer.id, { animation: e.target.value as TextLayer["animation"] })}
            >
              <option value="fade">fade</option>
              <option value="none">none</option>
            </select>
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
