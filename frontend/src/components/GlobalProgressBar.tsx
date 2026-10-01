import { useIsFetching, useIsMutating } from "@tanstack/react-query";

/**
 * Thin indeterminate progress bar fixed to the top of the viewport.
 * Visible whenever any TanStack Query fetch or mutation is in flight.
 * Mounts inside AppLayout — floats above all protected pages.
 */
export function GlobalProgressBar() {
  const fetching = useIsFetching();
  const mutating = useIsMutating();
  const active = fetching + mutating > 0;

  if (!active) return null;

  return (
    <div
      role="progressbar"
      aria-label="Loading"
      className="fixed top-0 inset-x-0 z-50 h-0.5 overflow-hidden"
    >
      <div
        className="h-full w-full origin-left"
        style={{
          background: "linear-gradient(90deg, #6366f1, #8b5cf6, #ec4899)",
          animation: "progress-slide 1.4s ease-in-out infinite",
        }}
      />
      <style>{`
        @keyframes progress-slide {
          0%   { transform: translateX(-100%) scaleX(0.3); }
          40%  { transform: translateX(-10%)  scaleX(0.6); }
          100% { transform: translateX(100%)  scaleX(0.3); }
        }
      `}</style>
    </div>
  );
}
