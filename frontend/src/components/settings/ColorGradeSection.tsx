import { Info } from "lucide-react";
import { LutPicker } from "@/components/LutPicker";
import { FIELD_HINTS } from "./constants";
import { FieldHintText, Field } from "./Field";
import { BrandingButtonGroup, BrandingSlider } from "./BrandingSection";

const MODE_HELP: Record<string, string> = {
  category: "Pick a LUT from the clip's content category (food, nature…). Deterministic, free.",
  mood:   "Pick a LUT from the caption's mood (epic, calm…), falling back to category.",
  vision: "Let AI vision look at the frames and pick — adds a Groq call per edit.",
  fixed:  "Always apply one chosen LUT to every reel.",
};

export function ColorGradeSection({
  getValue,
  getOriginal,
  onChange,
}: {
  getValue: (key: string) => unknown;
  getOriginal: (key: string) => unknown;
  onChange: (key: string, val: unknown) => void;
}) {
  const mode      = String(getValue("lut_mode") || "category");
  const fixedLut  = String(getValue("fixed_lut") || "");
  const intensity = Number(getValue("intensity") ?? 1.0);

  return (
    <div className="space-y-4">
      <BrandingButtonGroup
        label="Selection mode"
        value={mode}
        options={[
          { value: "category", label: "Category" },
          { value: "mood", label: "Mood" },
          { value: "vision", label: "Vision" },
          { value: "fixed", label: "Fixed" },
        ]}
        hint={FIELD_HINTS["color.lut_mode"]}
        onChange={(v) => onChange("lut_mode", v)}
      />

      <div className="flex items-start gap-2 text-xs text-gray-400 bg-gray-800/40 border border-gray-700/60 rounded-lg px-3 py-2">
        <Info size={13} className="mt-0.5 shrink-0" />
        <span>{MODE_HELP[mode]}</span>
      </div>

      {/* AI-vision override toggle (ignored in fixed mode) */}
      <Field
        group="color"
        label="use_vision"
        value={Boolean(getValue("use_vision"))}
        original={getOriginal("use_vision")}
        onChange={(v) => onChange("use_vision", v)}
      />

      {/* Fixed LUT picker — only relevant when mode = fixed */}
      {mode === "fixed" && (
        <div className="py-1">
          <label className="block text-sm text-gray-300 mb-1.5">Fixed LUT</label>
          <LutPicker value={fixedLut} onChange={(file) => onChange("fixed_lut", file)} />
          <FieldHintText hint={FIELD_HINTS["color.fixed_lut"]} />
        </div>
      )}

      <div className="border-t border-gray-800" />

      <BrandingSlider
        label="Intensity (advisory)"
        value={intensity}
        min={0}
        max={1}
        step={0.05}
        format={(v) => `${Math.round(v * 100)}%`}
        hint={FIELD_HINTS["color.intensity"]}
        onChange={(v) => onChange("intensity", v)}
      />
    </div>
  );
}
