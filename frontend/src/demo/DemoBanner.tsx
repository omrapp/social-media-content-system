import { useState } from "react";
import { X } from "lucide-react";

export function DemoBanner() {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[100] flex items-center gap-3 rounded-full border border-amber-500/30 bg-gray-900/95 px-4 py-2 text-xs text-amber-200 shadow-lg backdrop-blur">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
      Live demo — sample data, actions are simulated
      <a
        href="https://github.com/omrapp/social-media-content-system"
        target="_blank"
        rel="noopener noreferrer"
        className="text-amber-400 underline-offset-2 hover:underline"
      >
        GitHub
      </a>
      <button onClick={() => setOpen(false)} aria-label="Dismiss" className="text-gray-400 hover:text-white">
        <X size={14} />
      </button>
    </div>
  );
}
