export type LogLevel = "success" | "error" | "debug" | "log";
export type LogSource = "api" | "ws" | "backend" | "system" | string;

export interface LogEntry {
  id: string;
  level: LogLevel;
  source: LogSource;
  message: string;
  data?: unknown;
  ts: number;
}
