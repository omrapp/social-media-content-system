import { XCircle, Ban, Loader2, Send } from "lucide-react";
import { CountdownTimer } from "@/components/CountdownTimer";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { PlatformPublishRow } from "@/components/PlatformPublishRow";
import { PLATFORMS, type Platform } from "./shared";
import type { UsePreview } from "@/hooks/usePreview";
import type { Post } from "@/types/post";

type Props = Pick<UsePreview,
  "pubBusy" | "busy" | "publishPlatforms" | "togglePlatform" |
  "cancel" | "reject" | "refetchPosts"> & {
  post: Post;
};

export function PublishPanel({
  post, pubBusy, busy, publishPlatforms, togglePlatform, cancel, reject, refetchPosts,
}: Props) {
  const isPublished = (p: Platform) =>
    p === "youtube" ? !!post.yt_video_id :
    p === "tiktok"  ? !!post.tiktok_video_id :
                      !!post.ig_media_id;
  const publishIdOf = (p: Platform): string | undefined =>
    p === "youtube" ? post.yt_video_id ?? undefined :
    p === "tiktok"  ? post.tiktok_video_id ?? undefined :
                      post.ig_media_id ?? undefined;
  // Post can still receive publishes unless it was shelved/deleted. A platform
  // already published is just skipped — it never blocks others.
  const postPublishable = !["cancelled", "rejected", "deleted"].includes(post.status);
  // Active platforms that still need publishing → the "Publish all" set.
  const pendingPlatforms = PLATFORMS.filter(
    (p) => (post.platforms ?? ["instagram"]).includes(p) && !isPublished(p)
  );

  return (
    <>
      {/* Status + countdown */}
      <div className="p-4 border-b border-gray-800 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <StatusBadge status={post.status} />
          {post.status === "preview" && post.publish_after && (
            <CountdownTimer publishAfter={post.publish_after} onExpired={refetchPosts} />
          )}
        </div>
      </div>

      {/* Per-platform publish */}
      <div className="p-4 border-b border-gray-800 space-y-2">
        <label className="text-xs font-semibold uppercase tracking-widest text-gray-500">Publish to</label>

        <div className="space-y-1.5">
          {PLATFORMS.map((p) => {
            const inPlatforms = (post.platforms ?? ["instagram"]).includes(p);
            const published = isPublished(p);
            const error =
              p === "youtube" ? post.yt_error :
              p === "tiktok"  ? post.tiktok_error : undefined;
            const platformBusy = pubBusy.has(p);
            // Independent per platform: stays clickable while the post is
            // publishable — even after publishing (backend blocks the duplicate
            // and returns the existing id), so a failed/partial re-publish works.
            const canPublish = postPublishable && !busy;
            return (
              <PlatformPublishRow
                key={p}
                platform={p}
                active={inPlatforms}
                published={published}
                publishId={publishIdOf(p)}
                error={error}
                canPublish={canPublish}
                busy={platformBusy}
                onPublish={() => publishPlatforms([p])}
                onToggle={() => { if (canPublish && !published) togglePlatform(p); }}
              />
            );
          })}
        </div>

        {/* Publish to all active, not-yet-published platforms at once */}
        {postPublishable && pendingPlatforms.length > 1 && (
          <button
            disabled={busy || pendingPlatforms.some((p) => pubBusy.has(p))}
            onClick={() => publishPlatforms([...pendingPlatforms])}
            className="w-full flex items-center justify-center gap-1.5 py-2 text-xs font-semibold rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 transition-colors"
          >
            {pendingPlatforms.some((p) => pubBusy.has(p))
              ? <Loader2 size={12} className="animate-spin" />
              : <Send size={12} />}
            Publish to all ({pendingPlatforms.length})
          </button>
        )}

        {/* Cancel + Reject */}
        {["preview", "approved"].includes(post.status) && (
          <div className="flex gap-2 pt-1">
            <button
              disabled={busy}
              onClick={cancel}
              className="flex-1 flex items-center justify-center gap-1.5 py-1.5 text-xs rounded-lg bg-gray-800 hover:bg-orange-900/40 text-gray-400 hover:text-orange-300 disabled:opacity-40"
              title="Cancel — keep media, shelve this post"
            >
              <Ban size={12} /> Cancel
            </button>
            <button
              disabled={busy}
              onClick={reject}
              className="flex-1 flex items-center justify-center gap-1.5 py-1.5 text-xs rounded-lg bg-gray-800 hover:bg-red-900/50 text-gray-400 hover:text-red-300 disabled:opacity-40"
              title="Reject — permanently delete video and all files"
            >
              <XCircle size={12} /> Reject
            </button>
          </div>
        )}
      </div>
    </>
  );
}
