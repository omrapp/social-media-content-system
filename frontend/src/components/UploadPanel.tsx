import { useState, useCallback, useRef } from "react";
import { Upload, Link2, X, Loader2, CheckCircle, AlertTriangle, Plus } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { CategoryTagsPicker } from "@/components/CategoryTagsPicker";
import type { UploadResult } from "@/types/downloads";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

const SELECT_STYLE = {
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
} as const;

type RowStatus = "idle" | "uploading" | "done" | "error";

interface UploadRow {
  uid: string;
  kind: "file" | "url";
  file?: File;
  url?: string;
  name: string;
  size?: number;
  category: string;
  tags: string[];
  status: RowStatus;
  error?: string;
}

let _uid = 0;
const nextUid = () => `row_${Date.now()}_${_uid++}`;

function fmtSize(bytes?: number): string {
  if (!bytes) return "—";
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
        <span className="max-w-[120px] truncate">{error || "failed"}</span>
      </span>
    );
  return <span className="text-[11px] text-gray-600">ready</span>;
}

export function UploadPanel({ refetch, refetchFunnel }: { refetch: () => void; refetchFunnel: () => void }) {
  const [rows, setRows] = useState<UploadRow[]>([]);
  const [urlInput, setUrlInput] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((files: FileList | File[]) => {
    const incoming = Array.from(files).filter((f) => f.type.startsWith("video/") || /\.(mp4|mov|m4v|webm)$/i.test(f.name));
    if (incoming.length === 0) return;
    setSuccessMsg(null);
    setRows((prev) => [
      ...prev,
      ...incoming.map((f) => ({
        uid: nextUid(),
        kind: "file" as const,
        file: f,
        name: f.name,
        size: f.size,
        category: "",
        tags: [] as string[],
        status: "idle" as RowStatus,
      })),
    ]);
  }, []);

  const addUrl = useCallback(() => {
    const url = urlInput.trim();
    if (!url) return;
    setSuccessMsg(null);
    setRows((prev) => [
      ...prev,
      {
        uid: nextUid(),
        kind: "url",
        url,
        name: url,
        category: "",
        tags: [],
        status: "idle",
      },
    ]);
    setUrlInput("");
  }, [urlInput]);

  const removeRow = useCallback((uid: string) => {
    setRows((prev) => prev.filter((r) => r.uid !== uid));
  }, []);

  const updateRow = useCallback(
    (uid: string, patch: Partial<UploadRow>) => {
      setRows((prev) => prev.map((r) => (r.uid === uid ? { ...r, ...patch } : r)));
    },
    [],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
    },
    [addFiles],
  );

  const allTagged = rows.length > 0 && rows.every((r) => r.category.trim());
  const pendingCount = rows.filter((r) => r.status !== "done").length;

  const uploadFiles = useCallback(
    async (fileRows: UploadRow[]): Promise<Record<string, UploadResult>> => {
      const fd = new FormData();
      fileRows.forEach((r) => fd.append("files", r.file as File));
      fd.append(
        "meta",
        JSON.stringify(fileRows.map((r) => ({ category: r.category.trim(), tags: r.tags }))),
      );

      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token;

      return new Promise<Record<string, UploadResult>>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${BASE}/downloads/upload`);
        if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 100));
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
          let results: UploadResult[] = [];
          try {
            results = (JSON.parse(xhr.responseText).results ?? []) as UploadResult[];
          } catch {
            /* empty */
          }
          const byUid: Record<string, UploadResult> = {};
          fileRows.forEach((r, i) => {
            byUid[r.uid] = results[i] ?? { filename: r.name, ok: false, error: "no result returned" };
          });
          resolve(byUid);
        };
        xhr.onerror = () => reject(new Error("network error"));
        xhr.send(fd);
      });
    },
    [],
  );

  const submit = useCallback(async () => {
    if (!allTagged || submitting) return;
    setSubmitting(true);
    setSuccessMsg(null);
    setProgress(0);

    const targets = rows.filter((r) => r.status !== "done");
    setRows((prev) => prev.map((r) => (r.status !== "done" ? { ...r, status: "uploading", error: undefined } : r)));

    let anyOk = false;

    // File rows: single multipart batch with real upload progress.
    const fileRows = targets.filter((r) => r.kind === "file");
    if (fileRows.length > 0) {
      try {
        const byUid = await uploadFiles(fileRows);
        setRows((prev) =>
          prev.map((r) => {
            const res = byUid[r.uid];
            if (!res) return r;
            if (res.ok) anyOk = true;
            return { ...r, status: res.ok ? "done" : "error", error: res.error };
          }),
        );
      } catch (e) {
        const msg = e instanceof Error ? e.message : "upload failed";
        setRows((prev) =>
          prev.map((r) => (fileRows.some((f) => f.uid === r.uid) ? { ...r, status: "error", error: msg } : r)),
        );
      }
    }

    // URL rows: one request each (indeterminate progress when there were no files).
    const urlRows = targets.filter((r) => r.kind === "url");
    if (urlRows.length > 0 && fileRows.length === 0) setProgress(0);
    for (const r of urlRows) {
      try {
        const res = await api.post<UploadResult>("/downloads/upload-url", {
          url: r.url,
          category: r.category.trim(),
          tags: r.tags,
        });
        if (res.ok) anyOk = true;
        setRows((prev) =>
          prev.map((x) => (x.uid === r.uid ? { ...x, status: res.ok ? "done" : "error", error: res.error } : x)),
        );
      } catch (e) {
        const msg = e instanceof Error ? e.message : "fetch failed";
        setRows((prev) => prev.map((x) => (x.uid === r.uid ? { ...x, status: "error", error: msg } : x)));
      }
    }

    setProgress(null);
    setSubmitting(false);
    if (anyOk) {
      setSuccessMsg("Uploaded — new clips added to your Library as raw media.");
      refetch();
      refetchFunnel();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allTagged, submitting, rows, uploadFiles, refetch, refetchFunnel]);

  return (
    <div className="space-y-5">
      {/* Drop zone + URL paste */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
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
          <span className="text-sm text-gray-300 font-medium">Drop videos or click to browse</span>
          <span className="text-[11px] text-gray-600">mp4 · mov · m4v · webm</span>
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        <div className="flex flex-col justify-center gap-2 rounded-2xl px-5 py-8" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}>
          <div className="flex items-center gap-2 text-sm text-gray-300 font-medium">
            <Link2 size={16} className="text-gray-500" />
            Add by URL
          </div>
          <div className="flex items-center gap-2">
            <input
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") addUrl();
              }}
              placeholder="https://…"
              className="flex-1 rounded-xl px-3 py-2 text-sm text-gray-300 placeholder-gray-600 focus:outline-none transition-colors"
              style={SELECT_STYLE}
            />
            <button
              onClick={addUrl}
              disabled={!urlInput.trim()}
              className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-xl cursor-pointer transition-all disabled:opacity-40"
              style={{ background: "rgba(99,102,241,0.15)", border: "1px solid rgba(99,102,241,0.3)", color: "#c7d2fe" }}
            >
              <Plus size={14} />
              Add URL
            </button>
          </div>
          <span className="text-[11px] text-gray-600">Public Google Drive / Dropbox / direct video link</span>
        </div>
      </div>

      {/* Per-item rows */}
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
                  className="flex flex-wrap items-center gap-2 rounded-xl px-3 py-2.5"
                  style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}
                >
                  <div className="flex items-center gap-2 min-w-[160px] flex-1">
                    {r.kind === "url" ? <Link2 size={13} className="text-gray-500 shrink-0" /> : <Upload size={13} className="text-gray-500 shrink-0" />}
                    <span className="text-sm text-gray-200 truncate" title={r.name}>{r.name}</span>
                    <span className="text-[11px] text-gray-600 font-mono shrink-0 ml-auto">{r.kind === "file" ? fmtSize(r.size) : "url"}</span>
                  </div>

                  <CategoryTagsPicker
                    category={r.category}
                    tags={r.tags}
                    onCategoryChange={(category) => updateRow(r.uid, { category })}
                    onTagsChange={(tags) => updateRow(r.uid, { tags })}
                    disabled={r.status === "uploading"}
                    variant="compact"
                  />

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

          {/* Progress + submit */}
          {progress !== null && (
            <div className="h-1.5 w-full rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.05)" }}>
              {progress > 0 ? (
                <div className="h-full bg-indigo-500 rounded-full transition-all" style={{ width: `${progress}%` }} />
              ) : (
                <motion.div className="h-full bg-indigo-500 rounded-full w-1/3" animate={{ x: ["-100%", "300%"] }} transition={{ repeat: Infinity, duration: 1.4, ease: "linear" }} />
              )}
            </div>
          )}

          <div className="flex items-center justify-between pt-1">
            <span className="text-[11px] text-gray-600">
              {allTagged ? "All items tagged" : "Set a category for every item to enable upload"}
            </span>
            <button
              onClick={submit}
              disabled={!allTagged || submitting || pendingCount === 0}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-xl cursor-pointer transition-all disabled:opacity-40"
              style={{ background: "rgba(99,102,241,0.18)", border: "1px solid rgba(99,102,241,0.35)", color: "#c7d2fe" }}
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              Upload {pendingCount} video{pendingCount === 1 ? "" : "s"}
            </button>
          </div>
        </div>
      )}

      {rows.length === 0 && !successMsg && (
        <p className="text-sm text-gray-600 py-2">No videos queued. Drop files or paste a link to begin.</p>
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
