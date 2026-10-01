import { useEffect, useState } from "react";
import { Clock } from "lucide-react";

interface Props {
  publishAfter: string;
  onExpired?: () => void;
}

function secondsUntil(iso: string): number {
  return Math.max(0, Math.floor((new Date(iso).getTime() - Date.now()) / 1000));
}

function fmt(secs: number): string {
  if (secs <= 0) return "now";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function CountdownTimer({ publishAfter, onExpired }: Props) {
  const [secs, setSecs] = useState(() => secondsUntil(publishAfter));

  useEffect(() => {
    setSecs(secondsUntil(publishAfter));
    const id = setInterval(() => {
      const remaining = secondsUntil(publishAfter);
      setSecs(remaining);
      if (remaining === 0) {
        clearInterval(id);
        onExpired?.();
      }
    }, 1000);
    return () => clearInterval(id);
  }, [publishAfter, onExpired]);

  const urgent = secs > 0 && secs < 300;

  return (
    <span className={`flex items-center gap-1 text-xs ${urgent ? "text-red-400 animate-pulse" : "text-amber-400"}`}>
      <Clock size={12} />
      Auto-post in {fmt(secs)}
    </span>
  );
}
