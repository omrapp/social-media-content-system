import { useEffect } from "react";
import { onWsEvent } from "@/lib/ws";

export function useWs(event: string, handler: (data: Record<string, unknown>) => void) {
  useEffect(() => onWsEvent(event, handler), [event, handler]);
}
