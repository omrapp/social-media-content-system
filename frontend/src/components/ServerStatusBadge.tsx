import { useEffect, useRef, useState } from "react";

interface HealthResponse {
  status: string;
  scheduler: boolean;
  telegram: string;
}

type ServerStatus = "up" | "degraded" | "down";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

const DOT: Record<ServerStatus, string> = {
  up: "bg-green-500",
  degraded: "bg-amber-400",
  down: "bg-red-500",
};

const LABEL: Record<ServerStatus, string> = {
  up: "Server up",
  degraded: "Scheduler down",
  down: "Server unreachable",
};

export function ServerStatusBadge() {
  const [status, setStatus] = useState<ServerStatus>("up");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [lastCheck, setLastCheck] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function check() {
    try {
      const res = await fetch(`${BASE}/health`);
      if (!res.ok) {
        setStatus("degraded");
        setLastCheck(new Date());
        return;
      }
      const data: HealthResponse = await res.json();
      setHealth(data);
      setLastCheck(new Date());
      setStatus(data.scheduler ? "up" : "degraded");
    } catch {
      setStatus("down");
      setLastCheck(new Date());
    }
  }

  useEffect(() => {
    check();
    intervalRef.current = setInterval(check, 30_000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []);

  // Retry faster when down
  useEffect(() => {
    if (status === "down") {
      if (intervalRef.current) clearInterval(intervalRef.current);
      intervalRef.current = setInterval(check, 10_000);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
      intervalRef.current = setInterval(check, 30_000);
    }
  }, [status]);

  const tooltip = [
    LABEL[status],
    health ? `scheduler: ${health.scheduler ? "running" : "stopped"}` : null,
    health ? `telegram: ${health.telegram}` : null,
    lastCheck ? `checked ${lastCheck.toLocaleTimeString()}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg" title={tooltip}>
      <span className={`w-2 h-2 rounded-full ${DOT[status]} ${status === "down" ? "animate-pulse" : ""}`} />
      <span className="text-xs text-gray-500 hidden sm:block">{LABEL[status]}</span>
    </div>
  );
}
