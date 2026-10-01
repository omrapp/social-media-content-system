import { AlertTriangle, ShieldAlert } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import type { TokenStatus } from "@/types/notifications";

export function TokenBanner() {
  const { data } = useApi<TokenStatus>("/notifications/token-status");

  if (!data || data.status === "ok" || data.status === "never_expires" || data.status === "not_configured") {
    return null;
  }

  const critical = data.status === "critical";

  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 text-sm ${
      critical
        ? "bg-red-950/60 border-b border-red-800 text-red-300"
        : "bg-amber-950/60 border-b border-amber-800 text-amber-300"
    }`}>
      {critical ? <ShieldAlert size={16} /> : <AlertTriangle size={16} />}
      <span>
        Instagram token expires in <strong>{data.days_left} day{data.days_left !== 1 ? "s" : ""}</strong>
        {data.expires_at && ` (${new Date(data.expires_at).toLocaleDateString()})`}.
        Refresh via Meta Developer Portal.
      </span>
    </div>
  );
}
