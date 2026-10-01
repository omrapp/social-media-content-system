/**
 * Reel-level colour: film grade, LUT, and the FFmpeg `eq` adjust.
 *
 * Split of ownership at export (see plan §4): the GRADE is baked by
 * merge_clips.render(), while the LUT and `eq` are composited downstream by
 * video_edit in the same encode as text/branding. That is also why picking a
 * grade profile disables the LUT — a graded merge makes video_edit skip lut3d,
 * so offering both would promise a look the export cannot produce.
 *
 * Every control clamps to the range editor_edl.py enforces, so the panel cannot
 * build a doc that fails on save.
 */

import { useState } from "react";

import { LutPicker } from "@/components/LutPicker";
import { GRADE_PROFILES, type EqSpec, type GradeSpec, type Reel } from "@/types/editor";

export interface ColorPanelProps {
  reel: Reel;
  onUpdate: (patch: Partial<Reel>) => void;
  /** `editor.preview_lut` — surfaced so the panel can say why nothing changed. */
  previewLut: boolean;
}

const IDENTITY: EqSpec = { brightness: 0, contrast: 1, saturation: 1 };

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-[11px] text-gray-400">{label}</span>
      {children}
    </div>
  );
}

const inputCls =
  "w-28 bg-gray-800 rounded px-2 py-1 text-xs text-gray-200 ring-1 ring-white/10 " +
  "focus:outline-none focus:ring-indigo-400/60";

function Slider({ value, min, max, step, onChange }: {
  value: number; min: number; max: number; step: number; onChange: (v: number) => void;
}) {
  return (
    <input
      type="range" min={min} max={max} step={step} value={value}
      className="w-28 accent-indigo-400"
      onChange={(e) => onChange(Number(e.target.value))}
    />
  );
}

export function ColorPanel({ reel, onUpdate, previewLut }: ColorPanelProps) {
  const [lutOpen, setLutOpen] = useState(false);
  const grade: GradeSpec = reel.grade;
  const eq = reel.eq;
  const gradeOn = Boolean(grade.profile);
  const eqDirty = eq.brightness !== 0 || eq.contrast !== 1 || eq.saturation !== 1;

  const setGrade = (patch: Partial<GradeSpec>) => onUpdate({ grade: { ...grade, ...patch } });
  const setEq = (patch: Partial<EqSpec>) => onUpdate({ eq: { ...eq, ...patch } });

  return (
    <div className="space-y-4">
      <section>
        <h3 className="text-xs font-semibold text-gray-200 mb-1">Film grade</h3>
        <div className="divide-y divide-white/5">
          <Row label="Profile">
            <select
              value={grade.profile} className={inputCls}
              onChange={(e) => {
                const profile = e.target.value;
                // Selecting a grade clears the LUT rather than leaving a dead
                // value in the doc the export would silently ignore.
                onUpdate({
                  grade: { ...grade, profile },
                  ...(profile ? { lut: null } : {}),
                });
              }}
            >
              <option value="">none</option>
              {GRADE_PROFILES.map((p) => (
                <option key={p} value={p}>{p.replace(/_/g, " ")}</option>
              ))}
            </select>
          </Row>
          <Row label="Deband">
            <input type="checkbox" checked={grade.deband} className="accent-indigo-400"
                   title="Kills sky/gradient banding after the grade"
                   onChange={(e) => setGrade({ deband: e.target.checked })} />
          </Row>
          <Row label="Grain">
            <input type="checkbox" checked={grade.grain} className="accent-indigo-400"
                   onChange={(e) => setGrade({ grain: e.target.checked })} />
          </Row>
          <Row label="Vignette">
            <input type="checkbox" checked={grade.vignette} className="accent-indigo-400"
                   onChange={(e) => setGrade({ vignette: e.target.checked })} />
          </Row>
        </div>
        <p className="text-[10px] text-gray-600 mt-2">
          The grade is baked at merge time and is <em>not</em> shown in the
          player — export to see it.
        </p>
      </section>

      <section>
        <h3 className="text-xs font-semibold text-gray-200 mb-1">LUT</h3>
        {gradeOn ? (
          <p className="text-[11px] text-gray-500">
            Disabled: a film grade is applied, so the export skips the LUT to keep
            one coherent look. Set the profile to “none” to grade with a LUT instead.
          </p>
        ) : (
          <>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-gray-300 truncate" title={reel.lut ?? ""}>
                {reel.lut ?? "none"}
              </span>
              <div className="flex items-center gap-2 shrink-0">
                {reel.lut && (
                  <button
                    className="text-[11px] text-gray-400 hover:text-gray-200"
                    onClick={() => onUpdate({ lut: null })}
                  >
                    clear
                  </button>
                )}
                <button
                  className="text-[11px] text-indigo-300 hover:text-indigo-200"
                  onClick={() => setLutOpen((v) => !v)}
                >
                  {lutOpen ? "close" : "change"}
                </button>
              </div>
            </div>
            {lutOpen && (
              <div className="mt-2">
                <LutPicker
                  value={reel.lut ?? ""}
                  onChange={(file) => onUpdate({ lut: file || null })}
                />
              </div>
            )}
            {!previewLut && (
              <p className="text-[10px] text-gray-600 mt-2">
                LUT preview is off (<code>editor.preview_lut</code>) — the export
                still applies it.
              </p>
            )}
          </>
        )}
      </section>

      <section>
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-xs font-semibold text-gray-200">Adjust</h3>
          {eqDirty && (
            <button
              className="text-[11px] text-gray-400 hover:text-gray-200"
              onClick={() => onUpdate({ eq: { ...IDENTITY } })}
            >
              reset
            </button>
          )}
        </div>
        <div className="divide-y divide-white/5">
          <Row label={`Brightness · ${eq.brightness >= 0 ? "+" : ""}${eq.brightness.toFixed(2)}`}>
            {/* FFmpeg `eq=brightness` is ADDITIVE in [-1,1] — 0 is untouched,
                not 1 as CSS brightness() would have it. */}
            <Slider value={eq.brightness} min={-1} max={1} step={0.02}
                    onChange={(v) => setEq({ brightness: v })} />
          </Row>
          <Row label={`Contrast · ${eq.contrast.toFixed(2)}×`}>
            <Slider value={eq.contrast} min={0} max={3} step={0.02}
                    onChange={(v) => setEq({ contrast: v })} />
          </Row>
          <Row label={`Saturation · ${eq.saturation.toFixed(2)}×`}>
            <Slider value={eq.saturation} min={0} max={3} step={0.02}
                    onChange={(v) => setEq({ saturation: v })} />
          </Row>
        </div>
      </section>
    </div>
  );
}
