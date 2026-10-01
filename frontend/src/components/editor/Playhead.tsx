/**
 * Timeline playhead — the vertical line + draggable head.
 *
 * Purely presentational: it knows where it is in seconds and how many pixels a
 * second is worth, and reports scrubs back up. Timeline.tsx owns the clock.
 */

import { useCallback, useEffect, useRef } from "react";

export interface PlayheadProps {
  timeS: number;
  pxPerSecond: number;
  /** Total timeline length in seconds — a scrub can't go past it. */
  durationS: number;
  onSeek: (timeS: number) => void;
  /** Left edge of the tracks area inside the scroll container, in px. */
  offsetPx?: number;
}

export function Playhead({ timeS, pxPerSecond, durationS, onSeek, offsetPx = 0 }: PlayheadProps) {
  const dragging = useRef(false);
  const railRef = useRef<HTMLDivElement | null>(null);

  const seekFromClientX = useCallback((clientX: number) => {
    const rail = railRef.current?.parentElement;
    if (!rail) return;
    const rect = rail.getBoundingClientRect();
    const x = clientX - rect.left - offsetPx;
    onSeek(Math.min(durationS, Math.max(0, x / pxPerSecond)));
  }, [durationS, offsetPx, onSeek, pxPerSecond]);

  useEffect(() => {
    // Listeners live on window, not the head: the pointer routinely leaves the
    // 12px-wide handle mid-drag and the scrub must keep tracking.
    const move = (e: PointerEvent) => { if (dragging.current) seekFromClientX(e.clientX); };
    const up = () => { dragging.current = false; };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [seekFromClientX]);

  const left = offsetPx + timeS * pxPerSecond;

  return (
    <div
      ref={railRef}
      className="absolute top-0 bottom-0 z-30 pointer-events-none"
      style={{ left }}
    >
      <div className="w-px h-full bg-rose-500/90 shadow-[0_0_6px_rgba(244,63,94,0.6)]" />
      <div
        role="slider"
        aria-label="Playhead"
        aria-valuemin={0}
        aria-valuemax={durationS}
        aria-valuenow={Number(timeS.toFixed(2))}
        tabIndex={0}
        onPointerDown={(e) => {
          e.preventDefault();
          dragging.current = true;
          seekFromClientX(e.clientX);
        }}
        className="pointer-events-auto absolute -top-0.5 -left-[7px] w-[15px] h-3 rounded-sm
                   bg-rose-500 cursor-ew-resize hover:bg-rose-400 focus:outline-none
                   focus:ring-2 focus:ring-rose-400/60"
      />
    </div>
  );
}
