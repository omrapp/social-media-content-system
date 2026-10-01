/**
 * Right-hand inspector for the selected cut.
 *
 * Every control clamps to the same range editor_edl.py enforces, so the panel
 * cannot produce a doc the backend will reject on save. Reel-level look (grade,
 * LUT, eq, music) is a read-only summary here — the Colour and Audio tabs own
 * those controls.
 */

import {
  MAX_CUT_S, MAX_JOIN_S, MIN_CUT_S, MIN_JOIN_S, XFADE_TRANSITIONS,
  cutDuration, type Cut, type EDL, type Reel,
} from "@/types/editor";

export interface PropertyPanelProps {
  edl: EDL;
  cut: Cut | null;
  index: number;
  isLast: boolean;
  onUpdateCut: (id: string, patch: Partial<Cut>) => void;
  /** Reel-level patch — only `loop_friendly` is editable from this panel; the
   *  rest of the Reel section stays a read-only summary of the Colour/Audio
   *  tabs, which own those fields. */
  onUpdateReel: (patch: Partial<Reel>) => void;
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

export function PropertyPanel({
  edl, cut, index, isLast, onUpdateCut, onUpdateReel,
}: PropertyPanelProps) {
  return (
    <div className="space-y-4">
      <section>
        <h3 className="text-xs font-semibold text-gray-200 mb-1">
          {cut ? `Clip ${index + 1}` : "No clip selected"}
        </h3>
        {!cut && (
          <p className="text-[11px] text-gray-500">
            Pick a clip on the timeline to trim it, change its speed, or set the
            transition into the next one.
          </p>
        )}

        {cut && (
          <div className="divide-y divide-white/5">
            <Row label="Source">
              <span className="text-[11px] text-gray-400 truncate max-w-[9rem]" title={cut.src_media_id}>
                {cut.src_media_id}
              </span>
            </Row>
            <Row label="In (s)">
              <input
                type="number" step={0.05} min={0} value={cut.in_s.toFixed(2)}
                className={inputCls}
                onChange={(e) => {
                  const v = Math.max(0, Number(e.target.value) || 0);
                  onUpdateCut(cut.id, { in_s: Math.min(v, cut.out_s - MIN_CUT_S) });
                }}
              />
            </Row>
            <Row label="Out (s)">
              <input
                type="number" step={0.05} min={0} value={cut.out_s.toFixed(2)}
                className={inputCls}
                onChange={(e) => {
                  const v = Number(e.target.value) || 0;
                  const lo = cut.in_s + MIN_CUT_S;
                  onUpdateCut(cut.id, { out_s: Math.min(Math.max(v, lo), cut.in_s + MAX_CUT_S) });
                }}
              />
            </Row>
            <Row label="Length">
              <span className="text-[11px] text-gray-300">{cutDuration(cut).toFixed(2)}s</span>
            </Row>

            <Row label={`Speed · ${cut.speed.toFixed(2)}×`}>
              <input
                type="range" min={0.3} max={1} step={0.05} value={cut.speed}
                className="w-24 accent-indigo-400"
                // Speed-up is not offered: it shortens the segment while every
                // xfade offset is computed from the probed duration, so the
                // backend rejects >1.0 outright.
                onChange={(e) => onUpdateCut(cut.id, { speed: Number(e.target.value) })}
              />
            </Row>
            <Row label="Smooth slow-mo">
              <input
                type="checkbox" checked={cut.smooth_slowmo}
                className="accent-indigo-400"
                title="Motion-compensated interpolation — CPU-heavy at export"
                onChange={(e) => onUpdateCut(cut.id, { smooth_slowmo: e.target.checked })}
              />
            </Row>

            <Row label="Ken Burns">
              <input
                type="checkbox" checked={cut.ken_burns.enabled}
                className="accent-indigo-400"
                onChange={(e) =>
                  onUpdateCut(cut.id, { ken_burns: { ...cut.ken_burns, enabled: e.target.checked } })}
              />
            </Row>
            {cut.ken_burns.enabled && (
              <>
                <Row label="Direction">
                  <select
                    value={cut.ken_burns.direction} className={inputCls}
                    onChange={(e) => onUpdateCut(cut.id, {
                      ken_burns: { ...cut.ken_burns, direction: e.target.value as "in" | "out" },
                    })}
                  >
                    <option value="in">push in</option>
                    <option value="out">pull out</option>
                  </select>
                </Row>
                <Row label="Drift">
                  <select
                    value={cut.ken_burns.drift} className={inputCls}
                    onChange={(e) => onUpdateCut(cut.id, {
                      ken_burns: { ...cut.ken_burns, drift: Number(e.target.value) },
                    })}
                  >
                    <option value={0}>centred</option>
                    <option value={1}>pan right</option>
                    <option value={2}>centred (alt)</option>
                    <option value={3}>pan left</option>
                  </select>
                </Row>
              </>
            )}

            {!isLast && (
              <>
                <Row label="Transition">
                  <select
                    value={cut.transition.name} className={inputCls}
                    onChange={(e) => onUpdateCut(cut.id, {
                      transition: { ...cut.transition, name: e.target.value },
                    })}
                  >
                    {XFADE_TRANSITIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </Row>
                <Row label={`Duration · ${cut.transition.duration_s.toFixed(2)}s`}>
                  <input
                    type="range" min={MIN_JOIN_S} max={MAX_JOIN_S} step={0.02}
                    value={cut.transition.duration_s}
                    className="w-24 accent-indigo-400"
                    onChange={(e) => onUpdateCut(cut.id, {
                      transition: { ...cut.transition, duration_s: Number(e.target.value) },
                    })}
                  />
                </Row>
              </>
            )}
          </div>
        )}
      </section>

      <section>
        <h3 className="text-xs font-semibold text-gray-200 mb-1">Reel</h3>
        <div className="divide-y divide-white/5">
          <Row label="Canvas">
            <span className="text-[11px] text-gray-300">
              {edl.canvas.w}×{edl.canvas.h} · {edl.canvas.fps}fps
            </span>
          </Row>
          <Row label="Audio">
            <span className="text-[11px] text-gray-300">{edl.reel.audio_mode}</span>
          </Row>
          <Row label="Grade">
            <span className="text-[11px] text-gray-300">{edl.reel.grade.profile || "—"}</span>
          </Row>
          <Row label="LUT">
            <span className="text-[11px] text-gray-300 truncate max-w-[9rem]">
              {edl.reel.lut ?? "—"}
            </span>
          </Row>
          <Row label="Voiceover">
            <span className="text-[11px] text-gray-300">{edl.reel.voiceover ? "on" : "off"}</span>
          </Row>
          <Row label="Loop friendly">
            <input
              type="checkbox" checked={edl.reel.loop_friendly}
              className="accent-indigo-400"
              title="Echoes the opening cut as the last cut and skips the music fade-out, so the reel loops seamlessly on TikTok/IG"
              onChange={(e) => onUpdateReel({ loop_friendly: e.target.checked })}
            />
          </Row>
        </div>
        {edl.reel.loop_friendly && (
          <p className="text-[10px] text-gray-600 mt-2">
            The echoed opener is applied at render time, so it is not in the
            timeline or the preview — the exported reel runs slightly longer.
          </p>
        )}
        <p className="text-[10px] text-gray-600 mt-2">
          Edit the look in the Colour tab and the bed in the Audio tab.
        </p>
      </section>
    </div>
  );
}
