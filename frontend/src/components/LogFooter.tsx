import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { Terminal, ChevronUp, Trash2, Copy, ChevronsUp } from "lucide-react";
import { getLogs, clearLogs, subscribeLogs } from "@/lib/logger";
import type { LogEntry } from "@/types/logs";

// ── styling maps ────────────────────────────────────────────────────────────

const LEVEL_DOT: Record<string, string> = {
  success: "text-emerald-400",
  error: "text-red-400",
  debug: "text-gray-600",
  log: "text-sky-400",
};

const LEVEL_ROW_BG: Record<string, string> = {
  error: "bg-red-950/20",
  success: "",
  debug: "",
  log: "",
};

const LEVEL_MSG: Record<string, string> = {
  success: "text-emerald-300",
  error: "text-red-300",
  debug: "text-gray-500",
  log: "text-gray-300",
};

const LEVEL_FILTER: Record<string, string> = {
  all: "bg-gray-700 text-white",
  success: "bg-emerald-900 text-emerald-300",
  log: "bg-sky-900 text-sky-300",
  debug: "bg-gray-700 text-gray-300",
  error: "bg-red-900 text-red-300",
};

const SOURCE_STYLE: Record<string, string> = {
  api: "bg-blue-950 text-blue-400",
  ws: "bg-purple-950 text-purple-400",
  backend: "bg-orange-950 text-orange-400",
  system: "bg-gray-800 text-gray-400",
};

const LEVEL_SYMBOL: Record<string, string> = {
  success: "✓",
  error: "✗",
  debug: "·",
  log: "◉",
};

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtTime(ts: number): string {
  const d = new Date(ts);
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  const s = String(d.getSeconds()).padStart(2, "0");
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${h}:${m}:${s}.${ms}`;
}

function JsonVal({ v, depth = 0 }: { v: unknown; depth?: number }): React.ReactElement {
  if (v === null || v === undefined) return <span className="text-gray-500">null</span>;
  if (typeof v === "boolean") return <span className="text-amber-400">{String(v)}</span>;
  if (typeof v === "number") return <span className="text-sky-400">{v}</span>;
  if (typeof v === "string") {
    const s = v.length > 50 ? v.slice(0, 48) + "…" : v;
    return <span className="text-emerald-400">"{s}"</span>;
  }
  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="text-gray-500">[]</span>;
    if (depth >= 1) return <span className="text-gray-500">[{v.length}]</span>;
    return (
      <span>
        <span className="text-gray-500">[</span>
        {v.slice(0, 3).map((item, i) => (
          <span key={i}>
            {i > 0 && <span className="text-gray-600">, </span>}
            <JsonVal v={item} depth={depth + 1} />
          </span>
        ))}
        {v.length > 3 && <span className="text-gray-600">…+{v.length - 3}</span>}
        <span className="text-gray-500">]</span>
      </span>
    );
  }
  if (typeof v === "object") {
    const entries = Object.entries(v as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-gray-500">{"{}"}</span>;
    if (depth >= 2) return <span className="text-gray-500">{"{ … }"}</span>;
    const shown = entries.slice(0, 5);
    return (
      <span>
        <span className="text-gray-500">{"{ "}</span>
        {shown.map(([k, val], i) => (
          <span key={k}>
            {i > 0 && <span className="text-gray-600">, </span>}
            <span className="text-cyan-400">{k}</span>
            <span className="text-gray-600">: </span>
            <JsonVal v={val} depth={depth + 1} />
          </span>
        ))}
        {entries.length > 5 && <span className="text-gray-600"> …+{entries.length - 5}</span>}
        <span className="text-gray-500">{" }"}</span>
      </span>
    );
  }
  return <span className="text-gray-300">{String(v)}</span>;
}

// ── LogRow ───────────────────────────────────────────────────────────────────

function LogRow({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const srcStyle = SOURCE_STYLE[entry.source] ?? "bg-gray-800 text-gray-400";

  return (
    <div
      className={`border-b border-gray-800/30 ${LEVEL_ROW_BG[entry.level] ?? ""} hover:bg-white/[0.03]`}
    >
      <div className="flex items-baseline gap-2 px-3 py-[3px] text-xs font-mono leading-5">
        <span className="text-gray-600 w-[88px] shrink-0 tabular-nums select-none">{fmtTime(entry.ts)}</span>
        <span className={`shrink-0 rounded px-1.5 text-[10px] font-medium leading-4 select-none ${srcStyle}`}>
          {entry.source.slice(0, 8)}
        </span>
        <span className={`shrink-0 w-3 text-center select-none ${LEVEL_DOT[entry.level]}`}>
          {LEVEL_SYMBOL[entry.level] ?? "·"}
        </span>
        <span className={`flex-1 min-w-0 ${LEVEL_MSG[entry.level]}`}>
          {entry.message}
          {entry.data !== undefined && !expanded && (
            <span className="ml-2 opacity-50 cursor-pointer" onClick={() => setExpanded(true)}>
              <JsonVal v={entry.data} />
            </span>
          )}
        </span>
        {entry.data !== undefined && (
          <button
            onClick={() => setExpanded((e) => !e)}
            className="shrink-0 text-[9px] text-gray-600 hover:text-gray-400 px-1 select-none"
          >
            {expanded ? "▲" : "▼"}
          </button>
        )}
      </div>
      {expanded && entry.data !== undefined && (
        <pre className="px-3 pb-2 pt-0 text-[11px] font-mono text-gray-400 bg-gray-900/60 overflow-x-auto whitespace-pre-wrap break-all">
          {JSON.stringify(entry.data, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ── LogFooter ────────────────────────────────────────────────────────────────

const LEVELS = ["all", "success", "log", "debug", "error"] as const;
type FilterLevel = (typeof LEVELS)[number];
const HEIGHTS = [180, 320, 520] as const;

export function LogFooter() {
  const [logs, setLogs] = useState<LogEntry[]>(() => getLogs());
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<FilterLevel>("all");
  const [autoScroll, setAutoScroll] = useState(true);
  const [heightIdx, setHeightIdx] = useState(0);
  const [copied, setCopied] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => subscribeLogs(setLogs), []);

  useEffect(() => {
    if (autoScroll && open && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [logs, autoScroll, open]);

  const filtered = useMemo(
    () => (filter === "all" ? logs : logs.filter((l) => l.level === filter)),
    [logs, filter],
  );

  const errorCount = useMemo(() => logs.filter((l) => l.level === "error").length, [logs]);

  const copyAll = useCallback(() => {
    const text = filtered
      .map((e) => `[${new Date(e.ts).toISOString()}] [${e.level.toUpperCase()}] [${e.source}] ${e.message}${e.data !== undefined ? " " + JSON.stringify(e.data) : ""}`)
      .join("\n");
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [filtered]);

  const cycleHeight = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setHeightIdx((i) => (i + 1) % HEIGHTS.length);
  }, []);

  return (
    <div className="shrink-0 border-t border-gray-800 bg-gray-950">
      {/* ── header bar ── */}
      <div
        className="h-8 flex items-center px-3 gap-3 cursor-pointer hover:bg-gray-900/40 transition-colors select-none"
        onClick={() => setOpen((v) => !v)}
      >
        <Terminal size={12} className="text-gray-500 shrink-0" />
        <span className="text-xs font-medium text-gray-400">Logs</span>

        {errorCount > 0 && (
          <span className="bg-red-900/50 text-red-400 text-[10px] font-medium px-1.5 rounded">
            {errorCount} error{errorCount > 1 ? "s" : ""}
          </span>
        )}

        <span className="text-xs text-gray-600">{logs.length} entries</span>

        <div className="ml-auto flex items-center gap-2">
          <ChevronUp
            size={12}
            className={`text-gray-500 transition-transform duration-150 ${open ? "" : "rotate-180"}`}
          />
        </div>
      </div>

      {/* ── panel ── */}
      {open && (
        <div className="border-t border-gray-800 flex flex-col" style={{ height: HEIGHTS[heightIdx] }}>
          {/* toolbar */}
          <div
            className="flex items-center gap-1 px-3 py-1.5 border-b border-gray-800/60 shrink-0 select-none"
            onClick={(e) => e.stopPropagation()}
          >
            {LEVELS.map((lvl) => (
              <button
                key={lvl}
                onClick={() => setFilter(lvl)}
                className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                  filter === lvl
                    ? LEVEL_FILTER[lvl]
                    : "text-gray-600 hover:text-gray-300 hover:bg-gray-800/50"
                }`}
              >
                {lvl}
                {lvl !== "all" && (
                  <span className="ml-1 opacity-60">
                    {logs.filter((l) => l.level === lvl).length}
                  </span>
                )}
              </button>
            ))}

            <div className="ml-auto flex items-center gap-1">
              <button
                onClick={() => setAutoScroll((v) => !v)}
                className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
                  autoScroll ? "text-sky-400 bg-sky-950/50" : "text-gray-600 hover:text-gray-300"
                }`}
              >
                auto-scroll
              </button>
              <button
                onClick={copyAll}
                className={`p-1 rounded transition-colors ${copied ? "text-green-400" : "text-gray-600 hover:text-gray-300 hover:bg-gray-800/50"}`}
                title="Copy all logs"
              >
                <Copy size={11} />
              </button>
              <button
                onClick={cycleHeight}
                className="p-1 rounded text-gray-600 hover:text-gray-300 hover:bg-gray-800/50 transition-colors"
                title="Expand / collapse panel"
              >
                <ChevronsUp size={11} className={heightIdx === HEIGHTS.length - 1 ? "rotate-180" : ""} />
              </button>
              <button
                onClick={() => clearLogs()}
                className="p-1 rounded text-gray-600 hover:text-gray-300 hover:bg-gray-800/50 transition-colors"
                title="Clear logs"
              >
                <Trash2 size={11} />
              </button>
            </div>
          </div>

          {/* entries — selectable */}
          <div ref={listRef} className="flex-1 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="flex items-center justify-center h-full text-xs text-gray-700 font-mono select-none">
                no entries
              </div>
            ) : (
              filtered.map((entry) => <LogRow key={entry.id} entry={entry} />)
            )}
          </div>
        </div>
      )}
    </div>
  );
}
