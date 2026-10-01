import { useState, useCallback, useRef } from "react";
import { Upload, X, Loader2, CheckCircle, AlertTriangle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { supabase } from "@/lib/supabase";
import type { Track } from "@/types/audio";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

type RowStatus = "idle" | "uploading" | "done" | "error";

interface UploadRow {
  uid: string;
  file: File;
  name: string;
  size: number;
  status: RowStatus;
  error?: string;
}

let _uid = 0;
const nextUid = () => `audio_row_${Date.now()}_${_uid++}`;

function fmtSize(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${(bytes / 1024).toFixed(0)} KB`;
}

function RowBadge({ status, error }: { status: RowStatus; error?: string }) {
  if (status === "uploading") return <Loader2 size={13} className="animate-spin text-blue-400" />;
  if (status === "done") return <CheckCircle size={13} className="text-emerald-500" />;
  if (status === "error")
    return (
      <span className="flex items-center gap-1 text-[11px] text-red-400" title={error}>
        <AlertTriangle size={13} className="shrink-0" />
        <span className="max-w-[140px] truncate">{error || "failed"}</span>
      </span>
    );
  return <span className="text-[11px] text-gray-600">ready</span>;
}

/** Posts one file to /api/audio/upload via raw XHR for real upload-progress events. */
function uploadOne(file: File, token: string | undefined, onProgress: (pct: number) => void): Promise<Track> {
  const fd = new FormData();
  fd.append("file", file);
  return new Promise<Track>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/audio/upload`);
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        let detail = xhr.statusText;
        try {
          detail = JSON.parse(xhr.responseText).detail ?? detail;
        } catch {
          /* keep statusText */
        }
        reject(new Error(detail));
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText) as Track);
      } catch {
        reject(new Error("Malformed response"));
      }
    };
    xhr.onerror = () => reject(new Error("network error"));
    xhr.send(fd);
  });
}

export function AudioUploadPanel({ onUploaded }: { onUploaded: () => void }) {
  const [rows, setRows] = useState<UploadRow[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((files: FileList | File[]) => {
    const incoming = Array.from(files).filter(
      (f) => f.type.startsWith("audio/") || /\.(mp3|m4a|wav|ogg|flac)$/i.test(f.name),
    );
    if (incoming.length === 0) return;
    setSuccessMsg(null);
    setRows((prev) => [
      ...prev,
      ...incoming.map((f) => ({ uid: nextUid(), file: f, name: f.name, size: f.size, status: "idle" as RowStatus })),
    ]);
  }, []);

  const removeRow = useCallback((uid: string) => setRows((prev) => prev.filter((r) => r.uid !== uid)), []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
    },
    [addFiles],
  );

  const pendingCount = rows.filter((r) => r.status !== "done").length;

  const submit = useCallback(async () => {
    if (submitting || pendingCount === 0) return;
    setSubmitting(true);
    setSuccessMsg(null);

    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;

    const targets = rows.filter((r) => r.status !== "done");
    let anyOk = false;

    for (const r of targets) {
      setRows((prev) => prev.map((x) => (x.uid === r.uid ? { ...x, status: "uploading", error: undefined } : x)));
      setProgress(0);
      try {
        await uploadOne(r.file, token, (pct) => setProgress(pct));
        anyOk = true;
        setRows((prev) => prev.map((x) => (x.uid === r.uid ? { ...x, status: "done" } : x)));
      } catch (e) {
        const msg = e instanceof Error ? e.message : "upload failed";
        setRows((prev) => prev.map((x) => (x.uid === r.uid ? { ...x, status: "error", error: msg } : x)));
      }
    }

    setProgress(null);
    setSubmitting(false);
    if (anyOk) {
      setSuccessMsg("Uploaded — new tracks added to your Audio library.");
      onUploaded();
    }
  }, [submitting, pendingCount, rows, onUploaded]);

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        className="flex flex-col items-center justify-center gap-2 rounded-2xl px-5 py-8 cursor-pointer transition-colors"
        style={{
          background: dragOver ? "rgba(99,102,241,0.08)" : "rgba(255,255,255,0.02)",
          border: `1px dashed ${dragOver ? "rgba(99,102,241,0.5)" : "rgba(255,255,255,0.12)"}`,
        }}
      >
        <Upload size={20} className={dragOver ? "text-indigo-400" : "text-gray-500"} />
        <span className="text-sm text-gray-300 font-medium">Drop tracks or click to browse</span>
        <span className="text-[11px] text-gray-600">mp3 · m4a · wav · ogg · flac</span>
        <input
          ref={fileInputRef}
          type="file"
          accept="audio/*"
          multiple
          className="hidden"
          onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }}
        />
      </div>

      {rows.length > 0 && (
        <div className="space-y-2">
          <AnimatePresence initial={false}>
            {rows.map((r) => (
              <motion.div
                key={r.uid}
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.18 }}
                className="flex items-center gap-2 rounded-xl px-3 py-2.5"
                style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}
              >
                <Upload size={13} className="text-gray-500 shrink-0" />
                <span className="text-sm text-gray-200 truncate flex-1" title={r.name}>{r.name}</span>
                <span className="text-[11px] text-gray-600 font-mono shrink-0">{fmtSize(r.size)}</span>
                <div className="w-[110px] flex items-center justify-end">
                  <RowBadge status={r.status} error={r.error} />
                </div>
                <button
                  onClick={() => removeRow(r.uid)}
                  disabled={r.status === "uploading"}
                  className="p-1 rounded-lg text-gray-600 hover:text-red-400 hover:bg-white/[0.04] cursor-pointer transition-colors disabled:opacity-30"
                  title="Remove"
                >
                  <X size={14} />
                </button>
              </motion.div>
            ))}
          </AnimatePresence>

          {progress !== null && (
            <div className="h-1.5 w-full rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.05)" }}>
              <div className="h-full bg-indigo-500 rounded-full transition-all" style={{ width: `${progress}%` }} />
            </div>
          )}

          <div className="flex items-center justify-end pt-1">
            <button
              onClick={() => void submit()}
              disabled={submitting || pendingCount === 0}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-xl cursor-pointer transition-all disabled:opacity-40"
              style={{ background: "rgba(99,102,241,0.18)", border: "1px solid rgba(99,102,241,0.35)", color: "#c7d2fe" }}
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              Upload {pendingCount} track{pendingCount === 1 ? "" : "s"}
            </button>
          </div>
        </div>
      )}

      {rows.length === 0 && !successMsg && (
        <p className="text-sm text-gray-600 py-2">No tracks queued. Drop files or click to begin.</p>
      )}

      {successMsg && (
        <div className="flex items-center gap-2 p-3 rounded-xl text-sm" style={{ background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.2)", color: "#6ee7b7" }}>
          <CheckCircle size={14} className="shrink-0" />
          {successMsg}
        </div>
      )}
    </div>
  );
}
