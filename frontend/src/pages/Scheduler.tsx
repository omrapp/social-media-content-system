import { useState, useEffect, useCallback } from "react";
import {
  Clock, Play, CheckCircle2, XCircle, RefreshCw, Loader2,
  CalendarClock, Plus, X, Zap,
} from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { secondsUntil, fmtCountdown, fmtLocalTime } from "@/lib/time";

// ── Types ────────────────────────────────────────────────────────────────────

interface SchedulerStatus {
  running: boolean;
  auto_publish_enabled: boolean;
  auto_create_enabled: boolean;
  auto_create_mode: string;
  auto_create_strategy: string;
  auto_create_category: string;
  daily_slots: string[];
  timezone: string;
  max_per_day: number;
  next_slot: string | null;
  current_slot: string | null;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusBadge({ on, label }: { on: boolean; label: string }) {
  return (
    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
      on ? "bg-green-500/15 text-green-400 ring-1 ring-green-500/30" : "bg-gray-800 text-gray-500 ring-1 ring-gray-700"
    }`}>
      {on ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
      {label}
    </div>
  );
}

function NextSlotCountdown({ iso, tz }: { iso: string; tz: string }) {
  const [secs, setSecs] = useState(() => secondsUntil(iso));

  useEffect(() => {
    setSecs(secondsUntil(iso));
    const id = setInterval(() => setSecs(secondsUntil(iso)), 1000);
    return () => clearInterval(id);
  }, [iso]);

  const urgent = secs > 0 && secs < 600;

  return (
    <div className="flex flex-col gap-0.5">
      <span className={`text-2xl font-mono font-bold tabular-nums ${urgent ? "text-amber-400" : "text-white"}`}>
        {fmtCountdown(secs)}
      </span>
      <span className="text-xs text-gray-500">{fmtLocalTime(iso, tz)}</span>
    </div>
  );
}

function TimeSlotField({
  value,
  onChange,
}: {
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const update = (idx: number, t: string) => {
    const next = [...value];
    next[idx] = t;
    onChange(next.slice().sort());
  };
  const remove = (idx: number) => onChange(value.filter((_, i) => i !== idx));
  const add = () => onChange([...value, "12:00"].sort());

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-gray-300">Daily slots</span>
        <button
          onClick={add}
          className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 px-2 py-1 rounded-lg bg-blue-500/10 hover:bg-blue-500/20 transition-colors"
        >
          <Plus size={11} /> Add slot
        </button>
      </div>
      {value.length === 0 && (
        <p className="text-xs text-gray-600 py-2 text-center border border-dashed border-gray-700 rounded-lg">
          No slots — add at least one.
        </p>
      )}
      <div className="grid grid-cols-3 gap-2">
        {value.map((slot, idx) => (
          <div
            key={idx}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-gray-700 bg-gray-800"
          >
            <Clock size={12} className="text-gray-500 shrink-0" />
            <input
              type="time"
              value={slot}
              onChange={(e) => update(idx, e.target.value)}
              className="flex-1 bg-transparent text-sm tabular-nums text-gray-200 outline-none min-w-0"
            />
            <button
              onClick={() => remove(idx)}
              disabled={value.length <= 1}
              className="text-gray-600 hover:text-red-400 transition-colors disabled:opacity-20 shrink-0"
            >
              <X size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function SchedulerPage() {
  const { data: status, loading, refetch } = useApi<SchedulerStatus>("/scheduler/status");

  const [slots, setSlots] = useState<string[] | null>(null);
  const [timezone, setTimezone] = useState<string | null>(null);
  const [maxPerDay, setMaxPerDay] = useState<number | null>(null);
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const [runNowBusy, setRunNowBusy] = useState(false);
  const [runNowResult, setRunNowResult] = useState<{ ok: boolean; media_id?: string; reason?: string } | null>(null);

  // Sync local drafts from fetched status (only on initial load)
  useEffect(() => {
    if (!status) return;
    if (slots === null) setSlots(status.daily_slots);
    if (timezone === null) setTimezone(status.timezone);
    if (maxPerDay === null) setMaxPerDay(status.max_per_day);
  }, [status]);

  const saveSchedule = useCallback(async () => {
    if (!slots || !timezone || maxPerDay === null) return;
    setSavingSchedule(true);
    try {
      await api.put("/settings", { group: "schedule", value: { daily_slots: slots, timezone, max_per_day: maxPerDay } });
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2000);
      refetch();
    } finally {
      setSavingSchedule(false);
    }
  }, [slots, timezone, maxPerDay, refetch]);

  const runNow = useCallback(async () => {
    setRunNowBusy(true);
    setRunNowResult(null);
    try {
      const res = await api.post<{ ok: boolean; media_id?: string; reason?: string }>("/scheduler/run-now");
      setRunNowResult(res);
      if (res.ok) refetch();
    } finally {
      setRunNowBusy(false);
    }
  }, [refetch]);

  if (loading && !status) {
    return (
      <div className="flex items-center gap-3 text-gray-400 text-sm p-4">
        <div className="w-4 h-4 border-2 border-gray-600 border-t-blue-500 rounded-full animate-spin" />
        Loading scheduler…
      </div>
    );
  }

  const tz = status?.timezone ?? "UTC";
  const slotsValue = slots ?? status?.daily_slots ?? [];

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Posting Scheduler</h2>
          <p className="text-sm text-gray-500 mt-1">Daily slot configuration and live schedule status.</p>
        </div>
        <button onClick={refetch} className="p-2 hover:bg-gray-800 rounded-lg">
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Status indicators */}
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
          <CalendarClock size={14} className="text-purple-400" />
          Daemon status
        </h3>
        <div className="flex flex-wrap gap-2 mb-4">
          <StatusBadge on={status?.running ?? false} label="Scheduler running" />
          <StatusBadge on={status?.auto_publish_enabled ?? false} label="Auto-publish" />
          <StatusBadge on={status?.auto_create_enabled ?? false} label="Auto-create" />
        </div>
        {status?.auto_create_enabled && (
          <div className="text-xs text-gray-500 space-y-0.5">
            <p>Mode: <span className="text-gray-300">{status.auto_create_mode}</span></p>
            <p>Strategy: <span className="text-gray-300">{status.auto_create_strategy}</span></p>
            {status.auto_create_category && (
              <p>Category filter: <span className="text-gray-300">{status.auto_create_category}</span></p>
            )}
          </div>
        )}
      </section>

      {/* Next slot countdown */}
      {status?.next_slot && (
        <section className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
            <Clock size={14} className="text-amber-400" />
            Next slot
          </h3>
          <div className="flex items-center justify-between">
            <NextSlotCountdown iso={status.next_slot} tz={tz} />
            {status.current_slot && (
              <span className="text-xs text-purple-400 bg-purple-500/10 px-2 py-1 rounded-full ring-1 ring-purple-500/30 animate-pulse">
                Slot active now
              </span>
            )}
          </div>
        </section>
      )}

      {/* Upcoming slot times */}
      {status?.daily_slots && status.daily_slots.length > 0 && (
        <section className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">Today's slot times</h3>
          <div className="flex flex-wrap gap-2">
            {status.daily_slots.slice(0, status.max_per_day).map((slot) => (
              <span key={slot} className="flex items-center gap-1 px-2.5 py-1 bg-gray-800 rounded-lg text-sm text-gray-300 font-mono">
                <Clock size={11} className="text-gray-500" />
                {slot}
                <span className="text-xs text-gray-600 ml-0.5 font-sans">{status.timezone}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Manual trigger */}
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-gray-300 mb-1 flex items-center gap-2">
          <Zap size={14} className="text-yellow-400" />
          Manual trigger
        </h3>
        <p className="text-xs text-gray-500 mb-3">
          Force-create the next post now, bypassing slot timing. Respects auto-create mode ({status?.auto_create_mode ?? "approval"}).
        </p>
        <div className="flex items-center gap-3">
          <button
            onClick={runNow}
            disabled={runNowBusy}
            className="flex items-center gap-2 px-4 py-2 bg-yellow-600 hover:bg-yellow-700 disabled:opacity-50 rounded-lg text-sm font-medium"
          >
            {runNowBusy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            Create post now
          </button>
          {runNowResult && (
            <span className={`text-xs ${runNowResult.ok ? "text-green-400" : "text-red-400"}`}>
              {runNowResult.ok
                ? `Started: ${runNowResult.media_id?.slice(0, 8) ?? "—"}`
                : `No clip: ${runNowResult.reason}`}
            </span>
          )}
        </div>
      </section>

      {/* Schedule config */}
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
        <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
          <Clock size={14} className="text-purple-400" />
          Schedule configuration
        </h3>

        <TimeSlotField value={slotsValue} onChange={setSlots} />

        <div className="flex items-center justify-between gap-3 py-1">
          <label className="text-sm text-gray-300">Timezone</label>
          <input
            type="text"
            value={timezone ?? status?.timezone ?? ""}
            onChange={(e) => setTimezone(e.target.value)}
            placeholder="Asia/Beirut"
            className="w-48 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-gray-500"
          />
        </div>
        <p className="text-xs text-gray-500 -mt-2">IANA timezone — e.g. Asia/Beirut, Europe/London, America/New_York</p>

        <div className="flex items-center justify-between gap-3 py-1">
          <label className="text-sm text-gray-300">Max per day</label>
          <input
            type="number"
            min={1}
            max={20}
            value={maxPerDay ?? status?.max_per_day ?? 5}
            onChange={(e) => setMaxPerDay(Number(e.target.value))}
            className="w-24 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-right tabular-nums text-gray-200 focus:outline-none"
          />
        </div>
        <p className="text-xs text-gray-500 -mt-2">Hard cap on posts published per calendar day.</p>

        <div className="flex justify-end pt-2 border-t border-gray-800/50">
          <button
            onClick={saveSchedule}
            disabled={savingSchedule}
            className={`flex items-center gap-2 px-4 py-2 text-sm rounded-lg font-medium transition-all ${
              savedFlash
                ? "bg-green-600/20 text-green-400 ring-1 ring-green-500/30"
                : "bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white"
            }`}
          >
            {savedFlash ? (
              <><CheckCircle2 size={14} /> Saved</>
            ) : savingSchedule ? (
              <><Loader2 size={14} className="animate-spin" /> Saving…</>
            ) : (
              "Save schedule"
            )}
          </button>
        </div>
      </section>
    </div>
  );
}
