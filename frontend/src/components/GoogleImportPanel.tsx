import { useState, useCallback, useEffect, useRef } from "react";
import {
  HardDrive, Image as ImageIcon, Search, Loader2, CheckCircle,
  AlertTriangle, Download as DownloadIcon, ExternalLink, RefreshCw,
} from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { CategoryTagsPicker } from "@/components/CategoryTagsPicker";
import type {
  GoogleStatus, DriveFile, DriveList, PhotosSession, PhotosPoll, ImportResponse,
} from "@/types/downloads";

const SELECT_STYLE = {
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
} as const;

function fmtSize(bytes?: number | null): string {
  if (!bytes) return "—";
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${(bytes / 1024).toFixed(0)} KB`;
}

function fmtDur(ms?: number | null): string {
  if (!ms) return "";
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

type Meta = { category: string; tags: string[] };

function DriveTab({ meta, tagged, onDone }: { meta: Meta; tagged: boolean; onDone: () => void }) {
  const [q, setQ] = useState("");
  const [files, setFiles] = useState<DriveFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, "importing" | "done" | "error">>({});
  const [rowErr, setRowErr] = useState<Record<string, string>>({});

  const load = useCallback(async (query: string) => {
    setLoading(true); setErr(null);
    try {
      const r = await api.get<DriveList>(`/downloads/google-drive/list?q=${encodeURIComponent(query)}`);
      setFiles(r.files ?? []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Drive list failed");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(""); }, [load]);

  const importFile = useCallback(async (f: DriveFile) => {
    if (!tagged) return;
    setBusy((b) => ({ ...b, [f.id]: "importing" }));
    try {
      const r = await api.post<ImportResponse>("/downloads/google-drive/import", {
        file_id: f.id, name: f.name, ...meta,
      });
      const ok = r.results?.[0]?.ok;
      setBusy((b) => ({ ...b, [f.id]: ok ? "done" : "error" }));
      if (!ok) setRowErr((e) => ({ ...e, [f.id]: r.results?.[0]?.error ?? "failed" }));
      else onDone();
    } catch (e) {
      setBusy((b) => ({ ...b, [f.id]: "error" }));
      setRowErr((er) => ({ ...er, [f.id]: e instanceof Error ? e.message : "failed" }));
    }
  }, [meta, tagged, onDone]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-2 flex-1 rounded-lg px-3 py-2" style={SELECT_STYLE}>
          <Search size={14} className="text-gray-500" />
          <input
            value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void load(q); }}
            placeholder="Search Drive videos by name…"
            className="flex-1 bg-transparent text-xs text-gray-300 placeholder-gray-600 focus:outline-none"
          />
        </div>
        <button onClick={() => void load(q)} className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/[0.04] cursor-pointer" title="Refresh">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {err && (
        <div className="flex items-center gap-2 p-3 rounded-xl text-xs" style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#fca5a5" }}>
          <AlertTriangle size={13} /> {err}
        </div>
      )}

      {loading && files.length === 0 ? (
        <p className="text-sm text-gray-600 py-4 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading Drive videos…</p>
      ) : files.length === 0 ? (
        <p className="text-sm text-gray-600 py-4">No videos found in Drive.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {files.map((f) => {
            const st = busy[f.id];
            return (
              <div key={f.id} className="flex items-center gap-2.5 rounded-xl p-2.5" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}>
                <div className="w-12 h-12 rounded-lg overflow-hidden shrink-0 flex items-center justify-center" style={{ background: "rgba(255,255,255,0.04)" }}>
                  {f.thumbnailLink ? <img src={f.thumbnailLink} alt="" className="w-full h-full object-cover" referrerPolicy="no-referrer" /> : <HardDrive size={16} className="text-gray-600" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-xs text-gray-200 truncate" title={f.name}>{f.name}</div>
                  <div className="text-[10px] text-gray-600 font-mono">{fmtSize(f.size)}{f.duration_ms ? ` · ${fmtDur(f.duration_ms)}` : ""}</div>
                  {st === "error" && <div className="text-[10px] text-red-400 truncate" title={rowErr[f.id]}>{rowErr[f.id]}</div>}
                </div>
                <button
                  onClick={() => void importFile(f)}
                  disabled={!tagged || st === "importing" || st === "done"}
                  className="p-1.5 rounded-lg cursor-pointer transition-all disabled:opacity-40"
                  style={{ background: "rgba(99,102,241,0.15)", border: "1px solid rgba(99,102,241,0.3)", color: "#c7d2fe" }}
                  title={tagged ? "Import to Library" : "Set a category first"}
                >
                  {st === "importing" ? <Loader2 size={13} className="animate-spin" /> : st === "done" ? <CheckCircle size={13} className="text-emerald-400" /> : <DownloadIcon size={13} />}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PhotosTab({ meta, tagged, onDone }: { meta: Meta; tagged: boolean; onDone: () => void }) {
  const [session, setSession] = useState<PhotosSession | null>(null);
  const [phase, setPhase] = useState<"idle" | "waiting" | "importing" | "done" | "error">("idle");
  const [msg, setMsg] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);
  useEffect(() => stopPoll, [stopPoll]);

  const runImport = useCallback(async (sessionId: string) => {
    setPhase("importing");
    try {
      const r = await api.post<ImportResponse>("/downloads/google-photos/import", { session_id: sessionId, ...meta });
      if (r.saved > 0) {
        setPhase("done"); setMsg(`Imported ${r.saved} video(s) from Google Photos.`); onDone();
      } else {
        setPhase("error"); setMsg(r.error ?? r.results?.find((x) => !x.ok)?.error ?? "No videos imported.");
      }
    } catch (e) {
      setPhase("error"); setMsg(e instanceof Error ? e.message : "Import failed");
    }
  }, [meta, onDone]);

  const start = useCallback(async () => {
    if (!tagged) return;
    setMsg(null); setPhase("waiting");
    try {
      const s = await api.post<PhotosSession>("/downloads/google-photos/session", {});
      setSession(s);
      if (s.picker_uri) window.open(s.picker_uri, "_blank", "noopener");
      stopPoll();
      pollRef.current = setInterval(async () => {
        try {
          const p = await api.get<PhotosPoll>(`/downloads/google-photos/session/${s.id}`);
          if (p.media_items_set) { stopPoll(); await runImport(s.id); }
        } catch { /* keep polling */ }
      }, Math.max(2000, s.poll_interval_ms || 3000));
    } catch (e) {
      setPhase("error"); setMsg(e instanceof Error ? e.message : "Could not start picker");
    }
  }, [tagged, stopPoll, runImport]);

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500 leading-relaxed">
        Opens Google's hosted picker in a new tab. Select your videos there, then return — picked clips import automatically.
      </p>
      <button
        onClick={() => void start()}
        disabled={!tagged || phase === "waiting" || phase === "importing"}
        className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-xl cursor-pointer transition-all disabled:opacity-40"
        style={{ background: "rgba(99,102,241,0.18)", border: "1px solid rgba(99,102,241,0.35)", color: "#c7d2fe" }}
      >
        {phase === "waiting" || phase === "importing"
          ? <Loader2 size={14} className="animate-spin" />
          : <ExternalLink size={14} />}
        {phase === "waiting" ? "Waiting for picker…" : phase === "importing" ? "Importing…" : "Open Google Photos Picker"}
      </button>
      {phase === "waiting" && session?.picker_uri && (
        <a href={session.picker_uri} target="_blank" rel="noopener noreferrer" className="block text-[11px] text-indigo-400 hover:underline">
          Picker didn't open? Click here.
        </a>
      )}
      {msg && (
        <div
          className="flex items-center gap-2 p-3 rounded-xl text-xs"
          style={phase === "done"
            ? { background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.2)", color: "#6ee7b7" }
            : { background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#fca5a5" }}
        >
          {phase === "done" ? <CheckCircle size={13} /> : <AlertTriangle size={13} />} {msg}
        </div>
      )}
    </div>
  );
}

export function GoogleImportPanel({ refetch, refetchFunnel }: { refetch: () => void; refetchFunnel: () => void }) {
  const { data: status, loading } = useApi<GoogleStatus>("/downloads/google/status");
  const [source, setSource] = useState<"drive" | "photos">("drive");
  const [meta, setMeta] = useState<Meta>({ category: "", tags: [] });
  const tagged = !!meta.category.trim();
  const onDone = useCallback(() => { refetch(); refetchFunnel(); }, [refetch, refetchFunnel]);

  if (loading) {
    return <p className="text-sm text-gray-600 py-4 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Checking Google connection…</p>;
  }
  if (!status?.configured) {
    return (
      <div className="p-4 rounded-xl text-sm space-y-2" style={{ background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.2)" }}>
        <div className="flex items-center gap-2 text-amber-400 font-medium"><AlertTriangle size={15} /> Google import not connected</div>
        <p className="text-xs text-gray-400 leading-relaxed">
          Set <code className="text-gray-300">GOOGLE_CLIENT_ID</code>, <code className="text-gray-300">GOOGLE_CLIENT_SECRET</code> and{" "}
          <code className="text-gray-300">GOOGLE_REFRESH_TOKEN</code> in the server <code className="text-gray-300">.env</code>. Mint the refresh
          token by running <code className="text-gray-300">python -m backend.scripts.auth_google</code> (enable the Drive API + Photos Picker API in Google Cloud first).
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {(["drive", "photos"] as const).map((s) => (
          <button
            key={s} onClick={() => setSource(s)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg cursor-pointer transition-colors ${
              source === s ? "text-white" : "text-gray-500 hover:text-gray-300"
            }`}
            style={source === s ? { background: "rgba(99,102,241,0.15)", border: "1px solid rgba(99,102,241,0.3)" } : { border: "1px solid transparent" }}
          >
            {s === "drive" ? <HardDrive size={13} /> : <ImageIcon size={13} />}
            {s === "drive" ? "Google Drive" : "Google Photos"}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl px-3 py-2.5" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}>
        <CategoryTagsPicker
          category={meta.category}
          tags={meta.tags}
          onCategoryChange={(category) => setMeta((m) => ({ ...m, category }))}
          onTagsChange={(tags) => setMeta((m) => ({ ...m, tags }))}
          variant="compact"
        />
        <span className="text-[11px] text-gray-600">{tagged ? "Applied to imports" : "Set a category to enable import"}</span>
      </div>

      {source === "drive"
        ? <DriveTab meta={meta} tagged={tagged} onDone={onDone} />
        : <PhotosTab meta={meta} tagged={tagged} onDone={onDone} />}
    </div>
  );
}
