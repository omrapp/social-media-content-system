import { useState, useCallback, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle, XCircle, Ban, Edit3, Trash2, RotateCcw, RefreshCw, LayoutGrid, List, SlidersHorizontal } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { useApiMutation } from "@/hooks/useApiMutation";
import { onWsEvent } from "@/lib/ws";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { CountdownTimer } from "@/components/CountdownTimer";
import type { Post } from "@/types/post";

const ACTIVE = ["preview", "approved", "publishing", "scheduled"];

const STATUS_FILTERS = ["all", "preview", "approved", "scheduled", "posted", "rejected", "error"] as const;
type StatusFilter = typeof STATUS_FILTERS[number];
type SortKey = "scheduled_asc" | "scheduled_desc" | "status";

const POSTS_KEY = ["api", "/posts?limit=500&sort=scheduled_desc"];

export function QueuePage() {
  const navigate = useNavigate();
  const { data: posts, refetch } = useApi<Post[]>("/posts?limit=500&sort=scheduled_desc");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editCaption, setEditCaption] = useState("");
  const [rescheduleId, setRescheduleId] = useState<string | null>(null);
  const [rescheduleAt, setRescheduleAt] = useState("");
  const [viewMode, setViewMode] = useState<"list" | "grid">("list");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("scheduled_desc");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  useEffect(() => { setPage(1); }, [statusFilter, sortKey]);

  // Real-time: WS events are handled centrally via useWsInvalidation in App.tsx.
  // Keep a local listener here as well for the onExpired countdown callback refetch.
  useEffect(() => onWsEvent("post_status", () => refetch()), [refetch]);

  const filteredPosts = useMemo(() => {
    let list = posts || [];
    if (statusFilter !== "all") list = list.filter((p) => p.status === statusFilter);
    return [...list].sort((a, b) => {
      if (sortKey === "scheduled_asc")  return new Date(a.scheduled_at || 0).getTime() - new Date(b.scheduled_at || 0).getTime();
      if (sortKey === "scheduled_desc") return new Date(b.scheduled_at || 0).getTime() - new Date(a.scheduled_at || 0).getTime();
      // by status: active first, then alpha
      const ai = ACTIVE.includes(a.status) ? 0 : 1;
      const bi = ACTIVE.includes(b.status) ? 0 : 1;
      return ai !== bi ? ai - bi : a.status.localeCompare(b.status);
    });
  }, [posts, statusFilter, sortKey]);

  // ── Mutations (each has its own isPending → auto-disables buttons) ───────────

  const approveMut = useApiMutation({
    invalidates: [POSTS_KEY],
    successMessage: "Post approved",
  });

  const cancelMut = useApiMutation({
    invalidates: [POSTS_KEY],
    successMessage: "Post cancelled",
  });

  const rejectMut = useApiMutation({
    invalidates: [POSTS_KEY],
    successMessage: "Post rejected and deleted",
  });

  const removeMut = useApiMutation({
    method: "delete",
    invalidates: [POSTS_KEY],
    successMessage: "Post removed",
  });

  const saveEditMut = useApiMutation<void, [string, { caption: string }]>({
    method: "put",
    invalidates: [POSTS_KEY],
    successMessage: "Caption saved",
    onSuccess: () => { setEditingId(null); },
  });

  const saveRescheduleMut = useApiMutation<void, [string, { scheduled_at: string }]>({
    invalidates: [POSTS_KEY],
    successMessage: "Rescheduled",
    onSuccess: () => { setRescheduleId(null); },
  });

  const retryMut = useApiMutation({
    invalidates: [POSTS_KEY],
    successMessage: "Retrying…",
  });

  const bulkApproveMut = useApiMutation({
    invalidates: [POSTS_KEY],
    successMessage: false, // handled below with count
  });

  const togglePlatformMut = useApiMutation<void, [string, { platforms: string[] }]>({
    method: "put",
    invalidates: [POSTS_KEY],
    successMessage: false,
  });

  // ── Per-post busy derived from mutation state ─────────────────────────────
  // Since mutations are shared across posts we track the post ID being acted on
  const [actingId, setActingId] = useState<string | null>(null);
  const isBusy = (id: string) =>
    actingId === id &&
    (approveMut.isPending || cancelMut.isPending || rejectMut.isPending ||
     removeMut.isPending || saveEditMut.isPending || saveRescheduleMut.isPending ||
     retryMut.isPending || togglePlatformMut.isPending);

  const approve = (id: string) => {
    setActingId(id);
    approveMut.mutate(`/posts/${id}/approve`);
  };
  const cancel = (id: string) => {
    setActingId(id);
    cancelMut.mutate(`/posts/${id}/cancel`);
  };
  const reject = (id: string) => {
    if (!window.confirm("Permanently delete this video? This removes the post, media record, and all files and cannot be undone.")) return;
    setActingId(id);
    rejectMut.mutate(`/posts/${id}/reject`);
  };
  const remove = (id: string) => {
    setActingId(id);
    removeMut.mutate(`/posts/${id}`);
  };
  const saveEdit = (id: string) => {
    setActingId(id);
    saveEditMut.mutate([`/posts/${id}`, { caption: editCaption }]);
  };
  const saveReschedule = (id: string) => {
    setActingId(id);
    saveRescheduleMut.mutate([`/posts/${id}/reschedule`, { scheduled_at: new Date(rescheduleAt).toISOString() }]);
  };
  const retry = useCallback((id: string) => {
    setActingId(id);
    retryMut.mutate(`/posts/${id}/reschedule`);
  }, [retryMut]);

  const bulkApprove = useCallback(async () => {
    const previews = (posts || []).filter((p) => p.status === "preview");
    for (const p of previews) {
      bulkApproveMut.mutate(`/posts/${p.id}/approve`);
    }
  }, [posts, bulkApproveMut]);

  const togglePlatform = useCallback((postId: string, platform: string, current: string[]) => {
    const updated = current.includes(platform)
      ? current.filter((p) => p !== platform)
      : [...current, platform];
    setActingId(postId);
    togglePlatformMut.mutate([`/posts/${postId}`, { platforms: updated }]);
  }, [togglePlatformMut]);

  const previewCount = (posts || []).filter((p) => p.status === "preview").length;

  const totalPages = Math.max(1, Math.ceil(filteredPosts.length / PAGE_SIZE));
  const paged = filteredPosts.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const pagedActive = paged.filter((p) => ACTIVE.includes(p.status));
  const pagedDone   = paged.filter((p) => !ACTIVE.includes(p.status));

  const PlatformChips = ({ post }: { post: Post }) => (
    <div className="flex items-center gap-1 flex-wrap">
      {(["instagram", "youtube", "tiktok"] as const).map((p) => {
        const on = (post.platforms ?? ["instagram"]).includes(p);
        const canToggle = post.status === "preview";
        const cls = p === "instagram" ? "bg-pink-900/40 border-pink-700/60 text-pink-300"
          : p === "youtube" ? "bg-red-900/40 border-red-700/60 text-red-300"
          : "bg-slate-700/60 border-slate-500 text-slate-300";
        return (
          <button
            key={p}
            disabled={!canToggle || isBusy(post.id)}
            onClick={() => canToggle && togglePlatform(post.id, p, post.platforms ?? ["instagram"])}
            title={canToggle ? `Toggle ${p}` : p}
            className={`text-xs px-1.5 py-0.5 rounded border transition-colors ${on ? cls : "border-gray-700 text-gray-600"} ${canToggle ? "cursor-pointer hover:opacity-80" : "cursor-default"}`}
          >
            {p === "instagram" ? "IG" : p === "youtube" ? "YT" : "TT"}
          </button>
        );
      })}
      {post.yt_video_id     && <span className="text-xs text-red-400"    title="YouTube posted">YT ✓</span>}
      {post.yt_error        && <span className="text-xs text-red-600"    title={post.yt_error}>YT ✗</span>}
      {post.tiktok_video_id && <span className="text-xs text-slate-400"  title="TikTok posted">TT ✓</span>}
      {post.tiktok_error    && <span className="text-xs text-orange-500" title={post.tiktok_error}>TT ✗</span>}
    </div>
  );

  const ActionButtons = ({ post }: { post: Post }) => (
    // stopPropagation prevents button clicks from bubbling to the card-level navigate handler
    <div className="flex items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
      {post.status === "preview" && (
        <>
          <button disabled={isBusy(post.id)} onClick={() => approve(post.id)} title="Approve" className="p-1.5 hover:bg-gray-800 rounded text-gray-400 hover:text-green-400 disabled:opacity-40"><CheckCircle size={13} /></button>
          <button disabled={isBusy(post.id)} onClick={() => cancel(post.id)}  title="Cancel (soft)"  className="p-1.5 hover:bg-gray-800 rounded text-gray-400 hover:text-orange-400 disabled:opacity-40"><Ban size={13} /></button>
          <button disabled={isBusy(post.id)} onClick={() => reject(post.id)}  title="Reject (delete permanently)"  className="p-1.5 hover:bg-gray-800 rounded text-gray-400 hover:text-red-400 disabled:opacity-40"><XCircle size={13} /></button>
          <button onClick={() => { setRescheduleId(post.id); setRescheduleAt(""); }} title="Reschedule" className="p-1.5 hover:bg-gray-800 rounded text-gray-400 hover:text-blue-400"><RotateCcw size={13} /></button>
        </>
      )}
      {(post.status === "rejected" || post.status === "error") && (
        <button disabled={isBusy(post.id)} onClick={() => retry(post.id)} title="Retry" className="p-1.5 hover:bg-gray-800 rounded text-gray-400 hover:text-amber-400 disabled:opacity-40"><RefreshCw size={13} /></button>
      )}
      <button onClick={() => { setEditingId(post.id); setEditCaption(post.caption || ""); }} title="Edit caption" className="p-1.5 hover:bg-gray-800 rounded text-gray-400 hover:text-white"><Edit3 size={13} /></button>
      <button onClick={() => remove(post.id)} title="Delete post record" className="p-1.5 hover:bg-gray-800 rounded text-gray-400 hover:text-red-400"><Trash2 size={13} /></button>
    </div>
  );

  const PostCard = ({ post }: { post: Post }) => (
    <div
      className="rounded-2xl p-3 flex flex-col gap-2 cursor-pointer transition-all duration-200"
      style={post.status === "preview"
        ? { background: "rgba(17,19,31,1)", border: "1px solid rgba(245,158,11,0.3)", boxShadow: "0 0 16px rgba(245,158,11,0.06)" }
        : { background: "rgba(17,19,31,1)", border: "1px solid rgba(255,255,255,0.06)" }}
      onClick={() => post.media_id && navigate(`/preview/${post.media_id}`)}
      title="Open preview"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <StatusBadge status={post.status} />
          {post.status === "preview" && post.publish_after && (
            <CountdownTimer publishAfter={post.publish_after} onExpired={refetch} />
          )}
        </div>
        <ActionButtons post={post} />
      </div>

      {/* stopPropagation on interactive inner sections */}
      <div onClick={(e) => e.stopPropagation()}>
        <PlatformChips post={post} />
      </div>

      {editingId === post.id ? (
        <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
          <textarea value={editCaption} onChange={(e) => setEditCaption(e.target.value)} rows={3} className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs resize-none" />
          <div className="flex flex-col gap-1">
            <button onClick={() => saveEdit(post.id)} disabled={saveEditMut.isPending} className="text-green-400 text-xs px-1.5 py-1 border border-green-800 rounded hover:bg-green-900/30 disabled:opacity-40">Save</button>
            <button onClick={() => setEditingId(null)} className="text-gray-400 text-xs px-1.5 py-1 border border-gray-700 rounded hover:bg-gray-800">Cancel</button>
          </div>
        </div>
      ) : (
        <p className="text-xs text-gray-300 line-clamp-3">{post.caption || "No caption"}</p>
      )}

      {rescheduleId === post.id && (
        <div className="flex gap-1.5 items-center flex-wrap" onClick={(e) => e.stopPropagation()}>
          <input type="datetime-local" value={rescheduleAt} onChange={(e) => setRescheduleAt(e.target.value)} className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs" />
          <button onClick={() => saveReschedule(post.id)} disabled={saveRescheduleMut.isPending} className="text-blue-400 text-xs disabled:opacity-40">Set</button>
          <button onClick={() => setRescheduleId(null)} className="text-gray-400 text-xs">Cancel</button>
        </div>
      )}

      <div className="flex items-center gap-2 text-xs text-gray-500 mt-auto pt-1 border-t border-gray-800">
        <span className="font-mono">{post.media_id?.slice(0, 8)}</span>
        {post.scheduled_at && <span>{new Date(post.scheduled_at).toLocaleString()}</span>}
      </div>
    </div>
  );

  const PostRow = ({ post }: { post: Post }) => (
    <div
      className="rounded-2xl p-4 flex items-start gap-4 cursor-pointer transition-all duration-200"
      style={post.status === "preview"
        ? { background: "rgba(17,19,31,1)", border: "1px solid rgba(245,158,11,0.3)", boxShadow: "0 0 16px rgba(245,158,11,0.06)" }
        : { background: "rgba(17,19,31,1)", border: "1px solid rgba(255,255,255,0.06)" }}
      onClick={() => post.media_id && navigate(`/preview/${post.media_id}`)}
      title="Open preview"
    >
      <div className="flex-1 min-w-0 space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <StatusBadge status={post.status} />
          {post.status === "preview" && post.publish_after && (
            <CountdownTimer publishAfter={post.publish_after} onExpired={refetch} />
          )}
        </div>

        <div onClick={(e) => e.stopPropagation()}>
          <PlatformChips post={post} />
        </div>

        {editingId === post.id ? (
          <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
            <textarea
              value={editCaption}
              onChange={(e) => setEditCaption(e.target.value)}
              rows={3}
              className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm resize-none"
            />
            <div className="flex flex-col gap-1">
              <button onClick={() => saveEdit(post.id)} disabled={saveEditMut.isPending} className="text-green-400 text-xs px-2 py-1 border border-green-800 rounded hover:bg-green-900/30 disabled:opacity-40">Save</button>
              <button onClick={() => setEditingId(null)} className="text-gray-400 text-xs px-2 py-1 border border-gray-700 rounded hover:bg-gray-800">Cancel</button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-300 line-clamp-2">{post.caption || "No caption"}</p>
        )}

        {rescheduleId === post.id && (
          <div className="flex gap-2 items-center" onClick={(e) => e.stopPropagation()}>
            <input
              type="datetime-local"
              value={rescheduleAt}
              onChange={(e) => setRescheduleAt(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs"
            />
            <button onClick={() => saveReschedule(post.id)} disabled={saveRescheduleMut.isPending} className="text-blue-400 text-xs disabled:opacity-40">Set</button>
            <button onClick={() => setRescheduleId(null)} className="text-gray-400 text-xs">Cancel</button>
          </div>
        )}

        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className="font-mono">{post.media_id?.slice(0, 8)}</span>
          {post.scheduled_at && <span>{new Date(post.scheduled_at).toLocaleString()}</span>}
          {post.hashtags_en && (
            <span>{post.hashtags_en.length} EN · {post.hashtags_ar?.length ?? 0} AR tags</span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-1 shrink-0">
        <ActionButtons post={post} />
      </div>
    </div>
  );

  const PostItem = viewMode === "grid" ? PostCard : PostRow;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold tracking-tight">Queue</h2>
          <span className="text-xs text-gray-600 font-medium tracking-widest uppercase mt-0.5">Scheduler</span>
        </div>
        <div className="flex items-center gap-2">
          {previewCount > 0 && (
            <button
              onClick={bulkApprove}
              disabled={bulkApproveMut.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-green-600 hover:bg-green-700 disabled:opacity-50 rounded-lg"
            >
              <CheckCircle size={13} />
              Approve all ({previewCount})
            </button>
          )}
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Status filter pills */}
        <div className="flex items-center gap-1 flex-wrap">
          <SlidersHorizontal size={13} className="text-gray-500 shrink-0" />
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-2 py-0.5 rounded text-xs border transition-colors ${
                statusFilter === s
                  ? "bg-gray-700 border-gray-500 text-white"
                  : "border-gray-800 text-gray-500 hover:border-gray-600 hover:text-gray-300"
              }`}
            >
              {s === "all" ? "All" : s}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-1.5">
          {/* Sort */}
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="bg-gray-900 border border-gray-800 text-xs text-gray-300 rounded px-2 py-1 focus:outline-none focus:border-gray-600"
          >
            <option value="scheduled_asc">Scheduled ↑</option>
            <option value="scheduled_desc">Scheduled ↓</option>
            <option value="status">By status</option>
          </select>

          {/* Refresh */}
          <button
            onClick={() => refetch()}
            title="Refresh"
            className="p-1.5 border border-gray-800 rounded text-gray-400 hover:text-white hover:border-gray-600 transition-colors"
          >
            <RefreshCw size={13} />
          </button>

          {/* Grid / List toggle */}
          <div className="flex border border-gray-800 rounded overflow-hidden">
            <button
              onClick={() => setViewMode("list")}
              title="List view"
              className={`p-1.5 transition-colors ${viewMode === "list" ? "bg-gray-700 text-white" : "text-gray-500 hover:text-gray-300"}`}
            >
              <List size={13} />
            </button>
            <button
              onClick={() => setViewMode("grid")}
              title="Grid view"
              className={`p-1.5 transition-colors ${viewMode === "grid" ? "bg-gray-700 text-white" : "text-gray-500 hover:text-gray-300"}`}
            >
              <LayoutGrid size={13} />
            </button>
          </div>
        </div>
      </div>

      {pagedActive.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-widest text-gray-600">Pending</h3>
          <div className={viewMode === "grid" ? "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" : "space-y-2"}>
            {pagedActive.map((p) => <PostItem key={p.id} post={p} />)}
          </div>
        </section>
      )}

      {pagedDone.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-widest text-gray-600">History</h3>
          <div className={viewMode === "grid" ? "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" : "space-y-2"}>
            {pagedDone.map((p) => <PostItem key={p.id} post={p} />)}
          </div>
        </section>
      )}

      {filteredPosts.length === 0 && (
        <p className="text-center text-gray-500 py-12">
          {statusFilter !== "all" ? `No ${statusFilter} posts` : "Queue empty"}
        </p>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-1 pt-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 text-sm bg-gray-800 hover:bg-gray-700 disabled:opacity-40 rounded-lg cursor-pointer transition-colors"
          >
            ← Prev
          </button>
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
            <button
              key={n}
              onClick={() => setPage(n)}
              className={`px-3 py-1.5 text-sm rounded-lg cursor-pointer transition-colors ${
                n === page ? "bg-indigo-600 text-white" : "bg-gray-800 hover:bg-gray-700 text-gray-300"
              }`}
            >
              {n}
            </button>
          ))}
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-3 py-1.5 text-sm bg-gray-800 hover:bg-gray-700 disabled:opacity-40 rounded-lg cursor-pointer transition-colors"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
