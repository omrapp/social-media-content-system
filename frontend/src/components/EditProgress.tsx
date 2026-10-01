import { useEffect, useRef, useState } from "react";
import { onWsEvent } from "@/lib/ws";
import { CheckCircle2, Circle, Loader2, XCircle, ChevronDown, ChevronUp } from "lucide-react";

type EditStatus = "idle" | "running" | "done" | "error";

interface StageState {
  name: string;
  status: "queued" | "running" | "done";
}

const STAGE_LABELS: Record<string, string> = {
  music_swap:     "Music swap",
  color_grade:    "Color grade",
  resize:         "Resize",
  caption_refine: "Caption refine",
  reorder:        "Reorder",
  edit:           "Apply edits",
};

const STAGE_KEYWORDS: Record<string, string[]> = {
  music_swap:     ["music", "audio", "track", "swap"],
  color_grade:    ["lut", "color", "grade", "cube"],
  resize:         ["resize", "crop", "ffmpeg", "scale"],
  caption_refine: ["caption", "refine", "generate"],
  reorder:        ["reorder", "concat", "sequence"],
  edit:           ["edit", "enhance", "apply"],
};

interface Props {
  postId: string;
  onComplete?: () => void;
}

export function EditProgress({ postId, onComplete }: Props) {
  const [status, setStatus]   = useState<EditStatus>("idle");
  const [stages, setStages]   = useState<StageState[]>([]);
  const [logs, setLogs]       = useState<string[]>([]);
  const [errorMsg, setErrorMsg] = useState("");
  const [logsOpen, setLogsOpen] = useState(false);
  const logRef    = useRef<HTMLDivElement>(null);
  const statusRef = useRef<EditStatus>("idle");
  statusRef.current = status;

  useEffect(() => {
    const offDispatched = onWsEvent("edit_dispatched", (data) => {
      if (data.post_id !== postId) return;
      const stageNames = (data.stages as string[]) ?? [];
      setStages(stageNames.map((s, i) => ({
        name: s,
        status: i === 0 ? "running" : "queued",
      })));
      setLogs([]);
      setErrorMsg("");
      setStatus("running");
    });

    const offLog = onWsEvent("log_event", (data) => {
      if (statusRef.current !== "running") return;
      const msg = (data.message as string) ?? "";
      if (!msg) return;
      // Append capped log buffer — text only, never rendered as HTML
      setLogs((prev) => [...prev, msg].slice(-40));
      // Best-effort stage advancement: check if log hints at next stage starting
      setStages((prev) => {
        const runningIdx = prev.findIndex((s) => s.status === "running");
        if (runningIdx === -1) return prev;
        const nextIdx = runningIdx + 1;
        if (nextIdx >= prev.length) return prev;
        const nextKeywords = STAGE_KEYWORDS[prev[nextIdx].name] ?? [];
        if (nextKeywords.some((k) => msg.toLowerCase().includes(k))) {
          return prev.map((s, i) => {
            if (i === runningIdx) return { ...s, status: "done" as const };
            if (i === nextIdx)    return { ...s, status: "running" as const };
            return s;
          });
        }
        return prev;
      });
    });

    const offComplete = onWsEvent("edit_complete", (data) => {
      if (data.post_id !== postId) return;
      setStages((prev) => prev.map((s) => ({ ...s, status: "done" as const })));
      setStatus("done");
      onComplete?.();
    });

    const offFailed = onWsEvent("edit_failed", (data) => {
      if (data.post_id !== postId) return;
      setErrorMsg((data.error as string) ?? "Edit failed");
      setStatus("error");
    });

    return () => { offDispatched(); offLog(); offComplete(); offFailed(); };
  }, [postId, onComplete]);

  // Auto-scroll log to bottom
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  if (status === "idle") return null;

  return (
    <div className={`rounded-lg border p-3 space-y-3 ${
      status === "error" ? "border-red-800/60 bg-red-950/20" :
      status === "done"  ? "border-green-800/60 bg-green-950/15" :
                           "border-purple-800/40 bg-purple-950/10"
    }`}>
      {/* Overall bar */}
      <div className="h-1 rounded-full bg-gray-800 overflow-hidden">
        {status === "running" && (
          <div className="h-full w-3/4 rounded-full bg-purple-500 animate-pulse" />
        )}
        {status === "done"  && <div className="h-full w-full rounded-full bg-green-500 transition-all duration-700" />}
        {status === "error" && <div className="h-full w-full rounded-full bg-red-500" />}
      </div>

      {/* Status header */}
      <div className="flex items-center gap-2 text-xs">
        {status === "running" && <Loader2 size={12} className="animate-spin text-purple-400 shrink-0" />}
        {status === "done"    && <CheckCircle2 size={12} className="text-green-400 shrink-0" />}
        {status === "error"   && <XCircle size={12} className="text-red-400 shrink-0" />}
        <span className={
          status === "running" ? "text-purple-300" :
          status === "done"    ? "text-green-300"  : "text-red-300"
        }>
          {status === "running" ? "Edit in progress…" :
           status === "done"    ? "Edit complete — video updated" : "Edit failed"}
        </span>
        {status !== "running" && (
          <button
            onClick={() => setStatus("idle")}
            className="ml-auto text-gray-600 hover:text-gray-400 text-[10px]"
          >
            dismiss
          </button>
        )}
      </div>

      {/* Stage chips */}
      {stages.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {stages.map((s) => (
            <span
              key={s.name}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors ${
                s.status === "done"    ? "bg-green-900/40 text-green-300 border border-green-800/60" :
                s.status === "running" ? "bg-purple-900/50 text-purple-200 border border-purple-700/60" :
                                         "bg-gray-800 text-gray-500 border border-gray-700"
              }`}
            >
              {s.status === "running" ? <Loader2 size={9} className="animate-spin" /> :
               s.status === "done"    ? <CheckCircle2 size={9} /> :
                                         <Circle size={9} />}
              {STAGE_LABELS[s.name] ?? s.name}
            </span>
          ))}
        </div>
      )}

      {/* Error detail */}
      {status === "error" && errorMsg && (
        <p className="text-xs text-red-400 font-mono break-all">{errorMsg}</p>
      )}

      {/* Log stream */}
      {logs.length > 0 && (
        <div>
          <button
            onClick={() => setLogsOpen((o) => !o)}
            className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
          >
            {logsOpen ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            {logsOpen ? "Hide log" : `Show log (${logs.length} lines)`}
          </button>
          {logsOpen && (
            <div
              ref={logRef}
              className="mt-1.5 bg-black/60 rounded p-2 max-h-28 overflow-y-auto"
            >
              {logs.map((line, i) => (
                <p key={i} className="text-[10px] text-gray-400 font-mono leading-relaxed whitespace-pre-wrap break-all">
                  {line}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
