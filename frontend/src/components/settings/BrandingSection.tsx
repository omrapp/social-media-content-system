import { AlertCircle } from "lucide-react";
import { FontPicker } from "@/components/FontPicker";
import { FIELD_HINTS } from "./constants";
import type { FieldHint } from "./types";
import { FieldHintText, Field } from "./Field";

export function hexToRgba(hex: string, alpha: number): string {
  if (!hex.startsWith("#") || hex.length !== 7) return hex;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

export function BrandingColorField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="py-1">
      <label className="block text-xs text-gray-400 mb-1.5">{label}</label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-8 h-8 rounded cursor-pointer border border-gray-600 bg-transparent p-0.5"
        />
        <span className="text-xs font-mono text-gray-300">{value.toUpperCase()}</span>
      </div>
    </div>
  );
}

export function BrandingSlider({
  label,
  value,
  min,
  max,
  step,
  format,
  hint,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  hint?: FieldHint;
  onChange: (v: number) => void;
}) {
  return (
    <div className="py-1">
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-sm text-gray-300">{label}</label>
        <span className="text-xs font-mono text-gray-400 tabular-nums">{format(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-blue-500"
      />
      <FieldHintText hint={hint} />
    </div>
  );
}

export function BrandingButtonGroup({
  label,
  value,
  options,
  hint,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  hint?: FieldHint;
  onChange: (v: string) => void;
}) {
  return (
    <div className="py-1">
      <label className="block text-sm text-gray-300 mb-1.5">{label}</label>
      <div className="flex gap-1">
        {options.map((opt) => (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={`flex-1 px-3 py-1.5 text-xs rounded-lg border transition-colors font-medium ${
              value === opt.value
                ? "bg-blue-600 border-blue-500 text-white"
                : "bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-600"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <FieldHintText hint={hint} />
    </div>
  );
}

export function BrandingSection({
  getValue,
  getOriginal,
  onChange,
}: {
  getValue: (key: string) => unknown;
  getOriginal: (key: string) => unknown;
  onChange: (key: string, val: unknown) => void;
}) {
  const enabled       = Boolean(getValue("overlay_enabled"));
  const handle        = String(getValue("ig_handle") || "");
  const customText    = String(getValue("custom_text") || "");
  const font          = String(getValue("font") || "");
  const fontSize      = Number(getValue("font_size") || 0);
  const barH          = Number(getValue("bar_height") || 45);
  const showOnThumb   = Boolean(getValue("show_on_thumbnail") ?? true);
  const bgColor       = String(getValue("bar_bg_color") || "#ffffff");
  const textColor     = String(getValue("text_color") || "#000000");
  const opacity       = Number(getValue("bar_opacity") ?? 1.0);
  const position      = String(getValue("bar_position") || "bottom");
  const locationSide  = String(getValue("location_side") || "left");
  const handleSide    = String(getValue("handle_side") || "right");

  const sidesOverlap = handle && locationSide === handleSide;

  return (
    <div className="space-y-4">
      {/* Master controls */}
      <Field
        group="branding"
        label="overlay_enabled"
        value={enabled}
        original={getOriginal("overlay_enabled")}
        onChange={(v) => onChange("overlay_enabled", v)}
      />
      <div className="py-1">
        <label className="block text-sm text-gray-300 capitalize mb-1.5">ig handle</label>
        <input
          type="text"
          value={handle}
          onChange={(e) => onChange("ig_handle", e.target.value)}
          placeholder="@myaccount (optional)"
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 transition-colors focus:border-blue-500 outline-none"
        />
        <FieldHintText hint={FIELD_HINTS["branding.ig_handle"]} />
      </div>
      <Field
        group="branding"
        label="show_on_thumbnail"
        value={showOnThumb}
        original={getOriginal("show_on_thumbnail")}
        onChange={(v) => onChange("show_on_thumbnail", v)}
      />

      {/* Custom text */}
      <div className="py-1">
        <label className="block text-sm text-gray-300 mb-1.5">Custom text (below location)</label>
        <input
          type="text"
          value={customText}
          onChange={(e) => onChange("custom_text", e.target.value)}
          placeholder="e.g. travel.example.com (optional)"
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 transition-colors focus:border-blue-500 outline-none"
        />
        <FieldHintText hint={FIELD_HINTS["branding.custom_text"]} />
      </div>

      {/* Divider */}
      <div className="border-t border-gray-800" />

      {/* Font */}
      <div className="py-1">
        <label className="block text-sm text-gray-300 mb-1.5">Font</label>
        <FontPicker value={font} onChange={(file) => onChange("font", file)} />
        <FieldHintText hint={FIELD_HINTS["branding.font"]} />
      </div>

      {/* Font size */}
      <BrandingSlider
        label="Font size"
        value={fontSize}
        min={0}
        max={72}
        step={1}
        format={(v) => v === 0 ? "Auto" : `${v}px`}
        hint={FIELD_HINTS["branding.font_size"]}
        onChange={(v) => onChange("font_size", v)}
      />

      {/* Colors */}
      <div className="grid grid-cols-2 gap-4">
        <BrandingColorField
          label="Bar background"
          value={bgColor}
          onChange={(v) => onChange("bar_bg_color", v)}
        />
        <BrandingColorField
          label="Text color"
          value={textColor}
          onChange={(v) => onChange("text_color", v)}
        />
      </div>

      {/* Opacity */}
      <BrandingSlider
        label="Bar opacity"
        value={opacity}
        min={0}
        max={1}
        step={0.05}
        format={(v) => `${Math.round(v * 100)}%`}
        hint={FIELD_HINTS["branding.bar_opacity"]}
        onChange={(v) => onChange("bar_opacity", v)}
      />

      {/* Height */}
      <Field
        group="branding"
        label="bar_height"
        value={barH}
        original={getOriginal("bar_height")}
        onChange={(v) => onChange("bar_height", v)}
      />

      {/* Position */}
      <BrandingButtonGroup
        label="Bar position"
        value={position}
        options={[
          { value: "bottom", label: "Bottom" },
          { value: "top", label: "Top" },
        ]}
        hint={FIELD_HINTS["branding.bar_position"]}
        onChange={(v) => onChange("bar_position", v)}
      />

      {/* Layout sides */}
      <div className="grid grid-cols-2 gap-4">
        <BrandingButtonGroup
          label="Location side"
          value={locationSide}
          options={[
            { value: "left", label: "Left" },
            { value: "right", label: "Right" },
          ]}
          hint={FIELD_HINTS["branding.location_side"]}
          onChange={(v) => onChange("location_side", v)}
        />
        <BrandingButtonGroup
          label="Handle side"
          value={handleSide}
          options={[
            { value: "left", label: "Left" },
            { value: "right", label: "Right" },
          ]}
          hint={FIELD_HINTS["branding.handle_side"]}
          onChange={(v) => onChange("handle_side", v)}
        />
      </div>

      {sidesOverlap && (
        <div className="flex items-center gap-2 text-xs text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded-lg px-3 py-2">
          <AlertCircle size={13} />
          Location and handle are on the same side — they will overlap in the rendered bar.
        </div>
      )}
    </div>
  );
}
