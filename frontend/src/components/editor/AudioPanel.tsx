/**
 * Reel audio lane: bed source, track, level, fades, entry point, narration.
 *
 * The bed is muxed by merge_clips.render() (it owns time), so volume/fade/entry
 * ride the PLAN. Narration is composited downstream by video_edit, which is why
 * the duck level lands in EditOverrides instead.
 *
 * `audio_mode: "original"` keeps the longest clip's own audio and drops the bed
 * entirely — the whole music block is hidden rather than left dead.
 */

import { useState } from "react";

import { MusicPicker } from "@/components/MusicPicker";
import type { MusicSpec, Reel } from "@/types/editor";

export interface AudioPanelProps {
  reel: Reel;
  onUpdate: (patch: Partial<Reel>) => void;
  /** Parent reel metadata — only used to bias the track search. */
  category?: string;
  tags?: string[];
  /** Global `voiceover.music_duck_volume`, shown as the "auto" value. */
  defaultDuck?: number;
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

export function AudioPanel({ reel, onUpdate, category, tags, defaultDuck = 0.08 }: AudioPanelProps) {
  // MusicPicker highlights by track id, which the EDL does not persist (it
  // stores the path). Local state is enough — it only drives the highlight.
  const [trackId, setTrackId] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const music: MusicSpec = reel.music;
  const isMusic = reel.audio_mode === "music";

  const setMusic = (patch: Partial<MusicSpec>) => onUpdate({ music: { ...music, ...patch } });

  return (
    <div className="space-y-4">
      <section>
        <h3 className="text-xs font-semibold text-gray-200 mb-1">Source</h3>
        <div className="flex gap-2">
          {(["music", "original"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => onUpdate({ audio_mode: mode })}
              className={`flex-1 rounded px-2 py-1.5 text-[11px] ring-1 transition ${
                reel.audio_mode === mode
                  ? "bg-indigo-500/20 text-indigo-200 ring-indigo-400/40"
                  : "bg-gray-800/60 text-gray-400 ring-white/10 hover:text-gray-200"
              }`}
            >
              {mode === "music" ? "Music bed" : "Clip audio"}
            </button>
          ))}
        </div>
        {!isMusic && (
          <p className="text-[10px] text-gray-600 mt-2">
            The longest cut's own audio is kept and no bed is mixed in.
          </p>
        )}
      </section>

      {isMusic && (
        <section>
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-xs font-semibold text-gray-200">Track</h3>
            <button
              className="text-[11px] text-indigo-300 hover:text-indigo-200"
              onClick={() => setPickerOpen((v) => !v)}
            >
              {pickerOpen ? "close" : "change"}
            </button>
          </div>
          <p className="text-[11px] text-gray-300 truncate" title={music.path ?? ""}>
            {music.path ? music.path.split("/").pop() : "auto (mood-matched at export)"}
          </p>
          {pickerOpen && (
            <div className="mt-2">
              <MusicPicker
                value={trackId}
                onChange={(id, url) => { setTrackId(id); setMusic({ path: url }); }}
                category={category}
                tags={tags}
              />
            </div>
          )}
          {music.path && (
            <button
              className="text-[11px] text-gray-400 hover:text-gray-200 mt-1"
              onClick={() => { setTrackId(""); setMusic({ path: null, start_offset_s: null }); }}
            >
              use auto pick
            </button>
          )}

          <div className="divide-y divide-white/5 mt-2">
            <Row label={`Volume · ${Math.round(music.volume * 100)}%`}>
              <input
                type="range" min={0} max={2} step={0.05} value={music.volume}
                className="w-24 accent-indigo-400"
                onChange={(e) => setMusic({ volume: Number(e.target.value) })}
              />
            </Row>
            <Row label={`Fade · ${music.fade_s.toFixed(2)}s`}>
              <input
                type="range" min={0} max={5} step={0.1} value={music.fade_s}
                className="w-24 accent-indigo-400"
                title="Applied to both the fade-in and the fade-out"
                onChange={(e) => setMusic({ fade_s: Number(e.target.value) })}
              />
            </Row>
            <Row label="Start at">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox" checked={music.start_offset_s === null}
                  className="accent-indigo-400"
                  title="Auto = enter the track at its first strong onset (the drop)"
                  onChange={(e) => setMusic({ start_offset_s: e.target.checked ? null : 0 })}
                />
                <span className="text-[10px] text-gray-500">auto</span>
                {music.start_offset_s !== null && (
                  <input
                    type="number" step={0.1} min={0} value={music.start_offset_s.toFixed(1)}
                    className={inputCls}
                    onChange={(e) =>
                      setMusic({ start_offset_s: Math.max(0, Number(e.target.value) || 0) })}
                  />
                )}
              </div>
            </Row>
          </div>
        </section>
      )}

      <section>
        <h3 className="text-xs font-semibold text-gray-200 mb-1">Narration</h3>
        <div className="divide-y divide-white/5">
          <Row label="Voiceover">
            <input
              type="checkbox" checked={reel.voiceover} className="accent-indigo-400"
              title="Uses the narration already synthesized for this reel; the global voiceover setting still gates it"
              onChange={(e) => onUpdate({ voiceover: e.target.checked })}
            />
          </Row>
          {reel.voiceover && (
            <Row label="Duck bed to">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox" checked={music.duck_volume === null}
                  className="accent-indigo-400"
                  onChange={(e) =>
                    setMusic({ duck_volume: e.target.checked ? null : defaultDuck })}
                />
                <span className="text-[10px] text-gray-500">auto</span>
                {music.duck_volume !== null ? (
                  <input
                    type="range" min={0} max={1} step={0.01} value={music.duck_volume}
                    className="w-20 accent-indigo-400"
                    onChange={(e) => setMusic({ duck_volume: Number(e.target.value) })}
                  />
                ) : (
                  <span className="text-[10px] text-gray-500">
                    {Math.round(defaultDuck * 100)}%
                  </span>
                )}
              </div>
            </Row>
          )}
        </div>
        {reel.voiceover && music.duck_volume !== null && (
          <p className="text-[10px] text-gray-600 mt-2">
            Bed drops to {Math.round(music.duck_volume * 100)}% while narration plays.
          </p>
        )}
      </section>

      <p className="text-[10px] text-gray-600">
        The player mixes the bed at its set volume but without the export's
        fades — treat level, not shape, as accurate.
      </p>
    </div>
  );
}
