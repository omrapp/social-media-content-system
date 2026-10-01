import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { slideDown } from "@/lib/motion";
import { useNavigate } from "react-router-dom";
import {
  Activity, Loader2, CheckCircle2, XCircle, Clock,
  Film, Workflow, Download, Zap, Trash2, ChevronRight,
} from "lucide-react";
import { useActiveTasks, useRecentTasks } from "@/hooks/useTasks";
import { clearFinished } from "@/lib/taskStore";
import { useApi } from "@/hooks/useApi";
import { secondsUntil, fmtCountdown, fmtLocalTime } from "@/lib/time";
import type { Post } from "@/types/post";
import type { TaskType, TaskStatus } from "@/lib/taskStore";

// ── Scheduler status shape (same as Scheduler.tsx) ────────────────────────────

interface SchedulerStatus {
  running: boolean;
  auto_publish_enabled: boolean;
  auto_create_enabled: boolean;
  daily_slots: string[];
  timezone: string;
  max_per_day: number;
  next_slot: string | null;
  current_slot: string | null;
}

// ── Countdown hook ────────────────────────────────────────────────────────────

function useCountdown(iso: string | null | undefined): number {
  const [secs, setSecs] = useState(() => iso ? secondsUntil(iso) : 0);
  useEffect(() => {
    if (!iso) return;
    setSecs(secondsUntil(iso));
    const id = setInterval(() => setSecs(secondsUntil(iso)), 1000);
    return () => clearInterval(id);
  }, [iso]);
  return secs;
}

// ── Task type icon ─────────────────────────────────────────────────────────────

function TaskIcon({ type, status }: { type: TaskType; status: TaskStatus }) {
  if (status === "done")  return <CheckCircle2 size={13} className="text-green-400 shrink-0" />;
  if (status === "error") return <XCircle size={13} className="text-red-400 shrink-0" />;

  const iconMap: Record<TaskType, React.ReactElement> = {
    create:   <Film size={13} className="text-purple-400 shrink-0" />,
    pipeline: <Workflow size={13} className="text-blue-400 shrink-0" />,
    edit:     <Zap size={13} className="text-amber-400 shrink-0" />,
    download: <Download size={13} className="text-teal-400 shrink-0" />,
    publish:  <Activity size={13} className="text-green-400 shrink-0" />,
  };
  return iconMap[type];
}

// ── Platform result chips ──────────────────────────────────────────────────────

function PlatformChips({ post }: { post: Post }) {
  return (
    <div className="flex items-center gap-1 mt-0.5">
      {post.yt_video_id    && <span className="text-[10px] bg-red-900/40 text-red-300 px-1.5 py-0.5 rounded">YT ✓</span>}
      {post.yt_error       && <span className="text-[10px] bg-red-900/40 text-red-500 px-1.5 py-0.5 rounded" title={post.yt_error}>YT ✗</span>}
      {post.tiktok_video_id && <span className="text-[10px] bg-slate-700/60 text-slate-300 px-1.5 py-0.5 rounded">TT ✓</span>}
      {post.tiktok_error   && <span className="text-[10px] bg-orange-900/40 text-orange-400 px-1.5 py-0.5 rounded">TT ✗</span>}
      <span className="text-[10px] bg-pink-900/40 text-pink-300 px-1.5 py-0.5 rounded">IG ✓</span>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function TaskCenter() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const active = useActiveTasks();
  const recent = useRecentTasks();

  const { data: scheduler } = useApi<SchedulerStatus>("/scheduler/status");
  const { data: lastPostedArr } = useApi<Post[]>("/posts?status=posted&limit=1&sort=scheduled_desc");
  const lastPosted = lastPostedArr?.[0] ?? null;

  const nextSlotSecs = useCountdown(scheduler?.next_slot);

  // Outside-click close (mirrors NotificationBell)
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const totalActive = active.length;

  return (
    <div ref={ref} className="relative">
      {/* Trigger button */}
      <button
        onClick={() => setOpen((o) => !o)}
        title="Task Center"
        className="relative p-2 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors"
      >
        <Activity size={18} />
        {totalActive > 0 && (
          <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-blue-500 rounded-full text-[10px] font-bold flex items-center justify-center text-white animate-pulse">
            {totalActive > 9 ? "9+" : totalActive}
          </span>
        )}
      </button>

      {/* Dropdown panel */}
      <AnimatePresence>
      {open && (
        <motion.div
          variants={slideDown}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="absolute right-0 top-full mt-2 w-80 bg-gray-900/95 backdrop-blur border border-gray-700/80 rounded-xl shadow-2xl shadow-black/40 z-50 overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-gray-800 bg-gray-900/80 backdrop-blur-sm">
            <span className="text-sm font-semibold text-white flex items-center gap-2">
              <Activity size={14} className="text-blue-400" />
              Task Center
            </span>
            {totalActive > 0 && (
              <span className="text-[10px] bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded-full font-medium">
                {totalActive} running
              </span>
            )}
          </div>

          <div className="max-h-[30rem] overflow-y-auto">

            {/* ── Active tasks ─────────────────────────────────────────────── */}
            {active.length > 0 && (
              <section>
                <div className="px-3 pt-2.5 pb-1">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-500">Active</p>
                </div>
                {active.map((t) => (
                  <div
                    key={t.id}
                    className="px-3 py-2 border-b border-gray-800/50 flex items-start gap-2 hover:bg-gray-800/30"
                  >
                    <div className="pt-0.5">
                      <Loader2 size={13} className="animate-spin text-blue-400 shrink-0" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <TaskIcon type={t.type} status={t.status} />
                        <p className="text-xs font-medium text-white truncate">{t.label}</p>
                      </div>
                      {t.stage && (
                        <p className="text-[10px] text-blue-300 mt-0.5 truncate">→ {t.stage}</p>
                      )}
                      {t.detail && (
                        <p className="text-[10px] text-gray-500 mt-0.5 truncate">{t.detail}</p>
                      )}
                      {/* Navigate to page on click */}
                      {(t.type === "create" || (t.type === "pipeline")) && (
                        <button
                          onClick={() => {
                            navigate(t.type === "create" ? "/create" : "/pipeline");
                            setOpen(false);
                          }}
                          className="text-[10px] text-blue-400 hover:text-blue-300 flex items-center gap-0.5 mt-1"
                        >
                          View page <ChevronRight size={10} />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </section>
            )}

            {active.length === 0 && recent.length === 0 && (
              <p className="text-xs text-gray-500 py-5 text-center">No active tasks</p>
            )}

            {/* ── Scheduler ────────────────────────────────────────────────── */}
            <section className="border-b border-gray-800">
              <div className="px-3 pt-2.5 pb-1">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-500">Scheduler</p>
              </div>
              {scheduler ? (
                <div className="px-3 pb-2.5 space-y-2">
                  {/* Status pills */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                      scheduler.auto_publish_enabled
                        ? "bg-green-500/15 text-green-400"
                        : "bg-gray-800 text-gray-500"
                    }`}>
                      {scheduler.auto_publish_enabled ? "Auto-publish on" : "Auto-publish off"}
                    </span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                      scheduler.auto_create_enabled
                        ? "bg-purple-500/15 text-purple-400"
                        : "bg-gray-800 text-gray-500"
                    }`}>
                      {scheduler.auto_create_enabled ? "Auto-create on" : "Auto-create off"}
                    </span>
                  </div>
                  {/* Next slot countdown */}
                  {scheduler.next_slot ? (
                    <div className="flex items-center gap-2">
                      <Clock size={12} className="text-gray-500 shrink-0" />
                      <div>
                        <span className={`text-sm font-mono font-bold tabular-nums ${
                          nextSlotSecs > 0 && nextSlotSecs < 600 ? "text-amber-400" : "text-white"
                        }`}>
                          {fmtCountdown(nextSlotSecs)}
                        </span>
                        <span className="text-[10px] text-gray-500 ml-1.5">
                          {fmtLocalTime(scheduler.next_slot, scheduler.timezone)}
                        </span>
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-gray-500">No upcoming slots</p>
                  )}
                </div>
              ) : (
                <p className="text-xs text-gray-500 px-3 pb-2.5">Loading…</p>
              )}
            </section>

            {/* ── Last posted ──────────────────────────────────────────────── */}
            <section className="border-b border-gray-800">
              <div className="px-3 pt-2.5 pb-1">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-500">Last posted</p>
              </div>
              {lastPosted ? (
                <div
                  className="px-3 pb-2.5 cursor-pointer hover:bg-gray-800/30"
                  onClick={() => { navigate(`/preview/${lastPosted.media_id}`); setOpen(false); }}
                >
                  <p className="text-xs text-gray-300 truncate">{lastPosted.caption?.slice(0, 60) || lastPosted.media_id?.slice(0, 16)}</p>
                  <PlatformChips post={lastPosted} />
                  {lastPosted.scheduled_at && (
                    <p className="text-[10px] text-gray-600 mt-0.5">
                      {new Date(lastPosted.scheduled_at).toLocaleString()}
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-xs text-gray-500 px-3 pb-2.5">No posted videos yet</p>
              )}
            </section>

            {/* ── Recent finished tasks ─────────────────────────────────────── */}
            {recent.length > 0 && (
              <section>
                <div className="px-3 pt-2.5 pb-1 flex items-center justify-between">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-500">Recent</p>
                  <button
                    onClick={clearFinished}
                    className="text-[10px] text-gray-500 hover:text-gray-300 flex items-center gap-0.5"
                  >
                    <Trash2 size={10} /> Clear
                  </button>
                </div>
                {recent.slice(0, 5).map((t) => (
                  <div
                    key={t.id}
                    className="px-3 py-2 border-b border-gray-800/50 flex items-start gap-2 hover:bg-gray-800/30"
                  >
                    <TaskIcon type={t.type} status={t.status} />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-gray-300 truncate">{t.label}</p>
                      {t.detail && (
                        <p className={`text-[10px] mt-0.5 truncate ${t.status === "error" ? "text-red-400" : "text-gray-500"}`}>
                          {t.detail}
                        </p>
                      )}
                      {t.finishedAt && (
                        <p className="text-[10px] text-gray-600 mt-0.5">
                          {new Date(t.finishedAt).toLocaleTimeString()}
                        </p>
                      )}
                      {/* Navigate to created media on done create tasks */}
                      {t.type === "create" && t.status === "done" && t.mediaId && (
                        <button
                          onClick={() => { navigate(`/preview/${t.mediaId}`); setOpen(false); }}
                          className="text-[10px] text-blue-400 hover:text-blue-300 flex items-center gap-0.5 mt-0.5"
                        >
                          Preview <ChevronRight size={10} />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </section>
            )}
          </div>
        </motion.div>
      )}
      </AnimatePresence>
    </div>
  );
}
