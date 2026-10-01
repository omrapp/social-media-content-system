import { addLog } from "@/lib/logger";
import { IS_DEMO } from "@/demo";
import type { LogLevel } from "@/types/logs";

type Handler = (data: Record<string, unknown>) => void;

let socket: WebSocket | null = null;
let _token: string | null = null;
const listeners: Map<string, Set<Handler>> = new Map();

function wsUrl(): string {
  const apiBase: string = import.meta.env.VITE_API_BASE_URL ?? "";
  if (apiBase) {
    // Cross-origin prod: derive WS URL from VITE_API_BASE_URL
    // e.g. https://social-media-cms.domain.com/api → wss://social-media-cms.domain.com/ws/pipeline
    const url = new URL(apiBase.replace(/\/api$/, "/ws/pipeline"));
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
  }
  // Dev: same origin, Vite proxy handles it
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/pipeline`;
}

export function connectWs(token?: string) {
  if (IS_DEMO) return; // no backend to stream events from
  if (token) _token = token;
  if (socket?.readyState === WebSocket.OPEN) return;
  socket = new WebSocket(wsUrl());

  socket.onopen = () => {
    // Send token as first message — keeps JWT out of URL and server access logs
    socket!.send(JSON.stringify(_token ? { token: _token } : {}));
    addLog("debug", "system", "WebSocket connected");
  };

  socket.onmessage = (ev) => {
    const msg = JSON.parse(ev.data) as Record<string, unknown>;
    const event = msg.event as string;

    if (event === "log_event") {
      addLog(
        (msg.level as LogLevel) ?? "log",
        (msg.source as string) ?? "backend",
        (msg.message as string) ?? event,
        msg.data,
      );
    } else {
      const { event: _e, ...rest } = msg;
      addLog("log", "ws", event, Object.keys(rest).length > 0 ? rest : undefined);
    }

    const handlers = listeners.get(event);
    if (handlers) handlers.forEach((h) => h(msg));
  };

  socket.onclose = () => {
    addLog("debug", "system", "WebSocket disconnected — reconnecting in 3s");
    setTimeout(() => connectWs(), 3000);
  };
}

/** Demo mode only: deliver a synthetic event to local listeners (no socket). */
export function emitLocalWsEvent(msg: Record<string, unknown>) {
  listeners.get(msg.event as string)?.forEach((h) => h(msg));
}

export function onWsEvent(event: string, handler: Handler) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event)!.add(handler);
  return () => {
    listeners.get(event)?.delete(handler);
  };
}
