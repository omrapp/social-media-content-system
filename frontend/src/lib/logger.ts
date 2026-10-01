import type { LogEntry, LogLevel, LogSource } from "@/types/logs";

type Listener = (entries: LogEntry[]) => void;

const MAX = 500;
const _entries: LogEntry[] = [];
const _listeners = new Set<Listener>();
let _seq = 0;

export function addLog(level: LogLevel, source: LogSource, message: string, data?: unknown): void {
  const entry: LogEntry = { id: String(++_seq), level, source, message, data, ts: Date.now() };
  _entries.push(entry);
  if (_entries.length > MAX) _entries.shift();
  _listeners.forEach((l) => l([..._entries]));
}

export function getLogs(): LogEntry[] {
  return [..._entries];
}

export function clearLogs(): void {
  _entries.length = 0;
  _listeners.forEach((l) => l([]));
}

export function subscribeLogs(listener: Listener): () => void {
  _listeners.add(listener);
  return () => _listeners.delete(listener);
}
