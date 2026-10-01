import { useState, useCallback, useEffect, useRef } from "react";
import { Play, RefreshCw, CheckCircle, XCircle, Loader2, Workflow, ChevronRight } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useApi } from "@/hooks/useApi";
import { useWs } from "@/hooks/useWs";
import { api } from "@/lib/api";
import { toast } from "sonner";
import type { PipelineRun, OrchestrateResult } from "@/types/pipeline";
import { PIPELINE_STAGES } from "@/constants/pipeline";

const SESSION_KEY = "pipeline_state";

function loadSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

const CARD_STYLE = {
  background: "linear-gradient(145deg, rgba(17,19,31,1) 0%, rgba(10,10,16,1) 100%)",
  border: "1px solid rgba(255,255,255,0.06)",
  boxShadow: "0 4px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)",
};

export function PipelinePage() {
  const { data: runs, refetch } = useApi<PipelineRun[]>("/pipeline/runs?limit=20");

  const saved = loadSession();
  const [runningStages, setRunningStages] = useState<Record<string, boolean>>(saved?.runningStages ?? {});
  const runningStage = Object.keys(runningStages).find((k) => runningStages[k]) ?? null;
  const [runningFull, setRunningFull] = useState<boolean>(saved?.runningFull ?? false);
  const [runningOrch, setRunningOrch] = useState<boolean>(saved?.runningOrch ?? false);
  const [activeOrchStage, setActiveOrchStage] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>(saved?.logs ?? []);
  const [stageResults, setStageResults] = useState<Record<string, { processed: number; failed: number }>>({});
  const logsEndRef = useRef<HTMLDivElement>(null);

  const logsRef = useRef(logs);
  logsRef.current = logs;
  useEffect(() => {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ runningStages, runningFull, runningOrch, logs: logsRef.current.slice(-100) }));
  }, [runningStages, runningFull, runningOrch, logs]);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  useEffect(() => {
    if (!runs || runs.length === 0) return;
    const latest = runs[0];
    if ((runningOrch || runningFull || runningStage) && (latest.status === "completed" || latest.status === "failed")) {
      setRunningOrch(false); setRunningFull(false); setRunningStages({});
    }
  }, [runs]);

  useWs("pipeline_start", useCallback((data: Record<string, unknown>) => {
    setLogs((prev) => [...prev, `▶ ${data.stage}`]);
  }, []));

  useWs("pipeline_stage_start", useCallback((data: Record<string, unknown>) => {
    const stage = String(data.stage ?? "");
    setActiveOrchStage(stage);
    setLogs((prev) => [...prev, `  → ${stage}`]);
  }, []));

  useWs("pipeline_stage_complete", useCallback((data: Record<string, unknown>) => {
    const stage = String(data.stage ?? "");
    const result = data.result as Record<string, unknown> | undefined;
    const processed = Number(result?.processed ?? result?.uploaded ?? result?.edited ?? result?.downloaded ?? result?.rendered ?? 0);
    const failed = Number(result?.failed ?? result?.errors ?? 0);
    if (stage) setStageResults((prev) => ({ ...prev, [stage]: { processed, failed } }));
    setActiveOrchStage(null);
    setLogs((prev) => [...prev, `  ✓ ${stage}: ${processed} ok${failed ? `, ${failed} fail` : ""}`]);
  }, []));

  useWs("pipeline_complete", useCallback((data: Record<string, unknown>) => {
    const result = data.result as Record<string, unknown> | undefined;
    const processed = Number(result?.processed ?? result?.uploaded ?? result?.edited ?? result?.downloaded ?? 0);
    const failed = Number(result?.failed ?? result?.errors ?? 0);
    const stage = String(data.stage ?? "");
    if (stage) setStageResults((prev) => ({ ...prev, [stage]: { processed, failed } }));
    setLogs((prev) => [...prev, `✔ ${stage}: ${JSON.stringify(result)}`]);
    setRunningStages({}); setRunningFull(false); setRunningOrch(false);
    sessionStorage.removeItem(SESSION_KEY);
    refetch();
  }, [refetch]));

  const triggerStage = useCallback(async (stage: string) => {
    setRunningStages((prev) => ({ ...prev, [stage]: true }));
    setLogs((prev) => [...prev, `Triggering ${stage}…`]);
    try { await api.post(`/pipeline/${stage}`, {}); }
    catch (e) { toast.error(e instanceof Error ? e.message : `Stage ${stage} failed`); }
    finally { setRunningStages((prev) => ({ ...prev, [stage]: false })); refetch(); }
  }, [refetch]);

  const triggerFull = useCallback(async () => {
    setRunningFull(true); setLogs((prev) => [...prev, "Full pipeline starting…"]);
    try { await api.post("/pipeline/full", {}); }
    catch (e) { toast.error(e instanceof Error ? e.message : "Full pipeline failed"); }
    finally { setRunningFull(false); refetch(); }
  }, [refetch]);

  const triggerOrchestrator = useCallback(async (includeDownloads: boolean) => {
    setRunningOrch(true); setLogs((prev) => [...prev, `Orchestrator${includeDownloads ? " +downloads" : ""} starting…`]);
    try {
      const result = await api.post<OrchestrateResult>("/pipeline/orchestrate", { include_downloads: includeDownloads });
      setLogs((prev) => [...prev, `✔ Orchestrator: ${result.processed} processed, ${result.failed} failed`]);
    } catch (e) { toast.error(e instanceof Error ? e.message : "Orchestrator failed"); }
    finally { setRunningOrch(false); refetch(); }
  }, [refetch]);

  const anyRunning = runningFull || runningOrch || Object.values(runningStages).some(Boolean);

  return (
    <div className="space-y-6 px-1">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold tracking-tight">Pipeline</h2>
          <span className="text-xs text-gray-600 font-medium tracking-widest uppercase mt-0.5">Monitor</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => triggerOrchestrator(false)}
            disabled={anyRunning}
            className="flex items-center gap-2 px-3.5 py-2 text-sm font-medium rounded-xl disabled:opacity-40 cursor-pointer transition-all duration-200"
            style={{ background: "linear-gradient(135deg, rgba(139,92,246,0.25) 0%, rgba(109,40,217,0.15) 100%)", border: "1px solid rgba(139,92,246,0.35)", color: "#c4b5fd" }}
          >
            {runningOrch ? <Loader2 size={14} className="animate-spin" /> : <Workflow size={14} />}
            Orchestrate
          </button>
          <button
            onClick={() => triggerOrchestrator(true)}
            disabled={anyRunning}
            className="flex items-center gap-2 px-3.5 py-2 text-sm font-medium rounded-xl disabled:opacity-40 cursor-pointer transition-all duration-200"
            style={{ background: "rgba(139,92,246,0.1)", border: "1px solid rgba(139,92,246,0.2)", color: "#a78bfa" }}
          >
            {runningOrch ? <Loader2 size={14} className="animate-spin" /> : <Workflow size={14} />}
            + Downloads
          </button>
          <button
            onClick={triggerFull}
            disabled={anyRunning}
            className="flex items-center gap-2 px-3.5 py-2 text-sm font-medium rounded-xl disabled:opacity-40 cursor-pointer transition-all duration-200"
            style={{ background: "linear-gradient(135deg, rgba(59,130,246,0.25) 0%, rgba(29,78,216,0.15) 100%)", border: "1px solid rgba(59,130,246,0.35)", color: "#93c5fd" }}
          >
            {runningFull ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            Run Full
          </button>
        </div>
      </div>

      {/* Stage buttons */}
      <div
        className="flex items-center gap-1.5 overflow-x-auto pb-2 px-4 py-4 rounded-2xl"
        style={CARD_STYLE}
      >
        {PIPELINE_STAGES.map((stage, i) => {
          const isRunning = !!runningStages[stage.key];
          const isOrchActive = activeOrchStage === stage.key;
          const result = stageResults[stage.key];
          return (
            <div key={stage.key} className="flex items-center shrink-0">
              <div className="flex flex-col items-center gap-1.5">
                <button
                  onClick={() => triggerStage(stage.key)}
                  disabled={anyRunning}
                  className="flex items-center gap-2 px-3.5 py-2.5 rounded-xl text-xs font-medium whitespace-nowrap disabled:opacity-40 cursor-pointer transition-all duration-200"
                  style={
                    isRunning
                      ? { background: "rgba(59,130,246,0.15)", border: "1px solid rgba(59,130,246,0.4)", color: "#93c5fd" }
                      : isOrchActive
                      ? { background: "rgba(139,92,246,0.15)", border: "1px solid rgba(139,92,246,0.4)", color: "#c4b5fd" }
                      : { background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", color: "#9ca3af" }
                  }
                >
                  {isRunning || isOrchActive
                    ? <Loader2 size={12} className="animate-spin" />
                    : <Play size={12} />}
                  {stage.label}
                </button>
                <AnimatePresence>
                  {(isRunning || isOrchActive) && (
                    <motion.div
                      initial={{ opacity: 0, scaleX: 0 }}
                      animate={{ opacity: 1, scaleX: 1 }}
                      exit={{ opacity: 0 }}
                      className="h-0.5 w-full rounded-full overflow-hidden"
                      style={{ background: "rgba(255,255,255,0.05)" }}
                    >
                      <motion.div
                        className="h-full rounded-full"
                        style={{ background: isOrchActive ? "#8b5cf6" : "#3b82f6", boxShadow: `0 0 6px ${isOrchActive ? "#8b5cf6" : "#3b82f6"}` }}
                        animate={{ x: ["-100%", "100%"] }}
                        transition={{ repeat: Infinity, duration: 1.2, ease: "linear" }}
                      />
                    </motion.div>
                  )}
                </AnimatePresence>
                {result && !isRunning && !isOrchActive && (
                  <p className="text-[10px] tabular-nums font-mono">
                    <span className="text-emerald-500">{result.processed}✓</span>
                    {result.failed > 0 && <span className="text-red-500 ml-1">{result.failed}✗</span>}
                  </p>
                )}
              </div>
              {i < PIPELINE_STAGES.length - 1 && (
                <ChevronRight size={14} className="text-gray-700 mx-1 shrink-0" />
              )}
            </div>
          );
        })}
      </div>

      {/* Logs + History */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Terminal log */}
        <div className="rounded-2xl overflow-hidden" style={CARD_STYLE}>
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
            <span className="text-xs font-semibold tracking-widest uppercase text-gray-500">Live Logs</span>
            <div className="flex gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: "#ef4444" }} />
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: "#f59e0b" }} />
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: "#10b981" }} />
            </div>
          </div>
          <div
            className="h-64 overflow-y-auto p-4 font-mono text-xs space-y-1 leading-relaxed"
            style={{ background: "rgba(0,0,0,0.4)" }}
          >
            {logs.length === 0 && (
              <p className="text-gray-700">$ waiting for pipeline events…</p>
            )}
            {logs.map((line, i) => {
              const isSuccess = line.startsWith("✓") || line.startsWith("✔");
              const isStart = line.startsWith("▶") || line.includes("starting");
              const isFail = line.includes("fail") && !isSuccess;
              return (
                <motion.p
                  key={i}
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.15 }}
                  className={
                    isSuccess ? "text-emerald-400"
                    : isStart ? "text-blue-400"
                    : isFail ? "text-red-400"
                    : "text-gray-500"
                  }
                >
                  {line}
                </motion.p>
              );
            })}
            <div ref={logsEndRef} />
          </div>
        </div>

        {/* Run history */}
        <div className="rounded-2xl overflow-hidden" style={CARD_STYLE}>
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
            <span className="text-xs font-semibold tracking-widest uppercase text-gray-500">Run History</span>
            <button onClick={refetch} className="p-1 rounded-lg text-gray-600 hover:text-gray-400 cursor-pointer transition-colors">
              <RefreshCw size={13} />
            </button>
          </div>
          <div className="space-y-0 h-64 overflow-y-auto">
            {(runs || []).map((run) => (
              <div
                key={run.id}
                className="flex items-center justify-between px-4 py-3 border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  {run.status === "completed"
                    ? <CheckCircle size={13} className="text-emerald-500 shrink-0" />
                    : run.status === "failed"
                    ? <XCircle size={13} className="text-red-500 shrink-0" />
                    : <Loader2 size={13} className="text-blue-400 animate-spin shrink-0" />}
                  <span className="text-sm text-gray-300 capitalize font-medium">{run.stage}</span>
                </div>
                <div className="text-xs text-gray-600 text-right font-mono">
                  <span className="text-emerald-600">{run.items_processed}✓</span>
                  {run.items_failed > 0 && <span className="text-red-600 ml-1">{run.items_failed}✗</span>}
                  <span className="ml-2 text-gray-700">{new Date(run.started_at ?? run.created_at ?? "").toLocaleTimeString()}</span>
                </div>
              </div>
            ))}
            {(runs || []).length === 0 && (
              <p className="px-4 py-8 text-sm text-gray-600">No runs yet</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
