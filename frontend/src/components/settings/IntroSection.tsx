import { FontPicker } from "@/components/FontPicker";
import { BrandingColorField, BrandingSlider, BrandingButtonGroup } from "./BrandingSection";
import { ChevronDown, ChevronUp, GripVertical, Upload } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { DndContext, closestCenter, type DragEndEvent } from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
  arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { PreviewElementDef } from "./ScreenPreview";

interface ElementDef extends PreviewElementDef {
  label: string;
  textPlaceholder?: string;
  fontKey: string;
}

export const INTRO_ELEMENTS: ElementDef[] = [
  {
    id: "header", label: "Header",
    enabledKey: "header_enabled", textKey: "header_text", textPlaceholder: "Custom text (empty = @handle)",
    colorKey: "header_color", fontKey: "header_font", fontSizeKey: "header_font_size",
    orderKey: "header_order", defaultFontSize: 52,
    bottomPaddingKey: "header_bottom_padding",
  },
  {
    id: "subheader", label: "Sub-header",
    enabledKey: "subheader_enabled", textKey: "subheader_text", textPlaceholder: "Custom sub-header text",
    colorKey: "subheader_color", fontKey: "subheader_font", fontSizeKey: "subheader_font_size",
    orderKey: "subheader_order", defaultFontSize: 36, bottomPaddingKey: "subheader_bottom_padding",
  },
  {
    id: "tags", label: "Tags",
    enabledKey: "show_tags",
    colorKey: "tags_color", fontKey: "tags_font", fontSizeKey: "tags_font_size",
    orderKey: "tags_order", defaultFontSize: 40,
    bottomPaddingKey: "tags_bottom_padding",
  },
  {
    id: "category", label: "Category",
    enabledKey: "show_category",
    colorKey: "category_color", fontKey: "category_font", fontSizeKey: "category_font_size",
    orderKey: "category_order", defaultFontSize: 30,
    bottomPaddingKey: "category_bottom_padding",
  },
  {
    id: "handle", label: "Handle (@)",
    enabledKey: "show_handle",
    colorKey: "handle_color", fontKey: "handle_font", fontSizeKey: "handle_font_size",
    orderKey: "handle_order", defaultFontSize: 28,
    bottomPaddingKey: "handle_bottom_padding",
  },
];

export const PREVIEW_LABELS: Record<string, string> = {
  header: "@handle", subheader: "Sub-header", tags: "Nature, Coastal",
  category: "Culture", handle: "@handle",
};

export function IntroSection({
  getValue,
  onChange,
}: {
  getValue: (key: string) => unknown;
  getOriginal?: (key: string) => unknown;
  onChange: (key: string, val: unknown) => void;
}) {
  const enabled    = Boolean(getValue("enabled"));
  const mode       = String(getValue("mode") || "generated");
  const assetFile  = String(getValue("asset_file") || "");
  const animation  = String(getValue("animation") || "fade");
  const bgColor    = String(getValue("bg_color") || "#000000");
  const bgOpacity  = Number(getValue("bg_opacity") ?? 0.20);
  const textPad    = Number(getValue("text_padding_h") ?? 40);

  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const toggleCollapse = (id: string) =>
    setCollapsed((p) => ({ ...p, [id]: !p[id] }));

  // Sort elements by current order values
  const sortedElements = [...INTRO_ELEMENTS].sort(
    (a, b) =>
      Number(getValue(a.orderKey) ?? INTRO_ELEMENTS.indexOf(a)) -
      Number(getValue(b.orderKey) ?? INTRO_ELEMENTS.indexOf(b))
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = sortedElements.findIndex((e) => e.id === active.id);
    const newIndex = sortedElements.findIndex((e) => e.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    const reordered = arrayMove(sortedElements, oldIndex, newIndex);
    reordered.forEach((el, idx) => {
      onChange(el.orderKey, idx);
    });
  }

  return (
    <div className="space-y-4">
      {/* Master toggle — standalone */}
      <div className="flex items-center justify-between py-1">
        <div>
          <p className="text-sm text-gray-300 font-medium">Enabled</p>
          <p className="text-xs text-gray-500 mt-0.5">Prepend splash screen to every reel</p>
        </div>
        <button
          onClick={() => onChange("enabled", !enabled)}
          className={`relative w-10 h-5 rounded-full transition-colors ${enabled ? "bg-indigo-600" : "bg-gray-700"}`}
        >
          <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${enabled ? "translate-x-5" : "translate-x-0.5"}`} />
        </button>
      </div>

      {enabled && (
        <>
          {/* Mode */}
          <BrandingButtonGroup
            label="Mode"
            value={mode}
            options={[
              { value: "generated", label: "Generated" },
              { value: "asset", label: "Asset" },
            ]}
            onChange={(v) => onChange("mode", v)}
          />

          {/* Asset file */}
          {mode === "asset" && (
            <div className="py-1">
              <label className="block text-sm text-gray-300 mb-1.5">Asset file</label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={assetFile}
                  onChange={(e) => onChange("asset_file", e.target.value)}
                  placeholder="intro.mp4"
                  className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-indigo-500 outline-none"
                />
                <Link
                  to="/assets?type=intro"
                  title="Upload intro assets from the Assets library page"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-gray-800 border border-gray-700 text-gray-300 hover:border-indigo-500 hover:text-white transition-colors"
                >
                  <Upload size={12} /> Upload
                </Link>
              </div>
              <p className="text-xs text-gray-500 mt-1.5">
                Uploads happen on the <span className="text-gray-300">Assets</span> page (Intros tab) — paste the resulting filename here.
              </p>
            </div>
          )}

          {/* Duration */}
          <div className="py-1">
            <label className="block text-sm text-gray-300 mb-1.5">Duration (seconds)</label>
            <input
              type="number"
              min={0.5}
              max={10}
              step={0.5}
              value={Number(getValue("duration_s") ?? 1.5)}
              onChange={(e) => onChange("duration_s", parseFloat(e.target.value) || 1.5)}
              className="w-28 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:border-indigo-500 outline-none"
            />
          </div>

          {/* Animation */}
          <div className="py-1">
            <label className="block text-sm text-gray-300 mb-1.5">Animation</label>
            <select
              value={animation}
              onChange={(e) => onChange("animation", e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:border-indigo-500 outline-none"
            >
              <option value="none">None</option>
              <option value="fade">Fade</option>
              <option value="zoom">Zoom</option>
              <option value="slide">Slide (from bottom)</option>
              <option value="blur">Blur dissolve</option>
              <option value="wipe">Wipe (left → right)</option>
              <option value="ken_burns">Ken Burns</option>
              <option value="random">Random (per reel)</option>
            </select>
          </div>

          {/* Background */}
          <div className="space-y-3">
            <p className="text-sm font-medium text-gray-300">Background</p>
            <div className="grid grid-cols-2 gap-4">
              <BrandingColorField
                label="Color"
                value={bgColor}
                onChange={(v) => onChange("bg_color", v)}
              />
              <div>
                <label className="block text-xs text-gray-400 mb-1">Opacity</label>
                <BrandingSlider
                  label=""
                  value={Math.round(bgOpacity * 100)}
                  min={0}
                  max={100}
                  step={5}
                  format={(v) => `${v}%`}
                  onChange={(v) => onChange("bg_opacity", v / 100)}
                />
              </div>
            </div>
          </div>

          {/* Text padding */}
          <div className="py-1">
            <label className="block text-sm text-gray-300 mb-1.5">Text padding (px, left & right)</label>
            <input
              type="number"
              min={0}
              max={200}
              step={4}
              value={textPad}
              onChange={(e) => onChange("text_padding_h", parseInt(e.target.value) || 0)}
              className="w-28 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:border-indigo-500 outline-none"
            />
          </div>

          {/* Text elements with drag-and-drop */}
          <div className="space-y-2">
            <p className="text-sm font-medium text-gray-300">Text elements</p>
            <p className="text-xs text-gray-500">Drag to reorder. Each element renders at its position in the 9:16 frame.</p>
            <DndContext collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
              <SortableContext
                items={sortedElements.map((e) => e.id)}
                strategy={verticalListSortingStrategy}
              >
                {sortedElements.map((el) => (
                  <ElementCard
                    key={el.id}
                    el={el}
                    getValue={getValue}
                    onChange={onChange}
                    collapsed={collapsed[el.id] ?? false}
                    onToggleCollapse={() => toggleCollapse(el.id)}
                  />
                ))}
              </SortableContext>
            </DndContext>
          </div>
        </>
      )}
    </div>
  );
}

function ElementCard({
  el, getValue, onChange, collapsed, onToggleCollapse,
}: {
  el: ElementDef;
  getValue: (key: string) => unknown;
  onChange: (key: string, val: unknown) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: el.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const enabled  = Boolean(getValue(el.enabledKey) ?? true);
  const color    = String(getValue(el.colorKey) || "#ffffff");
  const font     = String(getValue(el.fontKey) || "");
  const fontSize = Number(getValue(el.fontSizeKey) || el.defaultFontSize);

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="bg-gray-800/60 border border-gray-700 rounded-xl overflow-hidden"
    >
      {/* Card header */}
      <div className="flex items-center gap-2 px-3 py-2.5">
        {/* Drag handle */}
        <button
          {...attributes}
          {...listeners}
          className="p-0.5 rounded text-gray-500 hover:text-gray-300 cursor-grab active:cursor-grabbing transition-colors touch-none"
          aria-label="Drag to reorder"
        >
          <GripVertical size={14} />
        </button>

        {/* Enable toggle */}
        <button
          onClick={() => onChange(el.enabledKey, !enabled)}
          className={`w-8 h-4 rounded-full transition-colors shrink-0 relative ${enabled ? "bg-indigo-600" : "bg-gray-600"}`}
        >
          <span className={`absolute top-0.5 w-3 h-3 bg-white rounded-full shadow transition-transform ${enabled ? "translate-x-4" : "translate-x-0.5"}`} />
        </button>

        {/* Label + color dot */}
        <span
          className="w-2.5 h-2.5 rounded-full border border-gray-600 shrink-0"
          style={{ backgroundColor: color }}
        />
        <span className={`text-sm font-medium flex-1 ${enabled ? "text-gray-200" : "text-gray-500"}`}>
          {el.label}
        </span>
        <span className="text-xs text-gray-500 mr-1">{fontSize}px</span>

        <button onClick={onToggleCollapse} className="text-gray-500 hover:text-gray-300 p-0.5">
          {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>
      </div>

      {!collapsed && enabled && (
        <div className="border-t border-gray-700/60 px-3 py-3 space-y-3">
          {/* Custom text (only for elements with textKey) */}
          {el.textKey && (
            <div>
              <label className="block text-xs text-gray-400 mb-1">Text</label>
              <textarea
                rows={2}
                value={String(getValue(el.textKey) || "")}
                onChange={(e) => onChange(el.textKey!, e.target.value)}
                placeholder={el.textPlaceholder}
                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-indigo-500 outline-none resize-none"
              />
              <p className="text-xs text-gray-600 mt-1">Use Enter for multiple lines</p>
            </div>
          )}

          {/* Color + font size */}
          <div className="grid grid-cols-2 gap-3">
            <BrandingColorField
              label="Color"
              value={color}
              onChange={(v) => onChange(el.colorKey, v)}
            />
            <div>
              <label className="block text-xs text-gray-400 mb-1">Font size (px)</label>
              <input
                type="number"
                min={8}
                max={200}
                step={2}
                value={fontSize}
                onChange={(e) => onChange(el.fontSizeKey, parseInt(e.target.value) || el.defaultFontSize)}
                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:border-indigo-500 outline-none"
              />
            </div>
          </div>

          {/* Font */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">Font</label>
            <FontPicker
              value={font}
              onChange={(file) => onChange(el.fontKey, file)}
              defaultLabel="Default (PlayfairDisplay)"
            />
          </div>

          {/* Bottom padding */}
          {el.bottomPaddingKey && (
            <div>
              <label className="block text-xs text-gray-400 mb-1">Bottom padding (px)</label>
              <input
                type="number"
                min={0}
                max={200}
                step={4}
                value={Number(getValue(el.bottomPaddingKey) ?? 0)}
                onChange={(e) => onChange(el.bottomPaddingKey!, parseInt(e.target.value) || 0)}
                className="w-28 bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:border-indigo-500 outline-none"
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
