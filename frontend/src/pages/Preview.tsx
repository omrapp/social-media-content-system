import { Link, useParams } from "react-router-dom";
import { Wand2, Film, Loader2, Scissors } from "lucide-react";
import { usePreview } from "@/hooks/usePreview";
import { useSettings } from "@/lib/settings";
import { VideoPlayerPane } from "@/components/preview/VideoPlayerPane";
import { PublishPanel } from "@/components/preview/PublishPanel";
import { LocationPanel } from "@/components/preview/LocationPanel";
import { CaptionPanel } from "@/components/preview/CaptionPanel";
import { HashtagPanel } from "@/components/preview/HashtagPanel";
import { QuickFlagsPanel } from "@/components/preview/QuickFlagsPanel";
import { EnhancementPanel } from "@/components/preview/EnhancementPanel";
import { RescheduleInline } from "@/components/preview/RescheduleInline";
import { EditDrawer } from "@/components/preview/EditDrawer";
import { EditProgress } from "@/components/EditProgress";

export function PreviewPage() {
  const { id } = useParams<{ id: string }>();
  const p = usePreview(id);
  const { media, mediaLoading, post } = p;
  const { data: settingsData } = useSettings();
  const editorEnabled =
    (settingsData?.settings?.editor as { enabled?: boolean } | undefined)?.enabled !== false;

  if (mediaLoading) {
    return <div className="flex items-center justify-center h-full text-gray-400">Loading…</div>;
  }
  if (!media) {
    return <div className="flex items-center justify-center h-full text-gray-400">Media not found</div>;
  }

  return (
    <div className="flex h-full gap-0 -m-6">
      <VideoPlayerPane
        navigate={p.navigate}
        prevId={p.prevId}
        nextId={p.nextId}
        navIdx={p.navIdx}
        orderedIds={p.orderedIds}
        videoUrl={p.videoUrl}
        videoKey={p.videoKey}
        videoRef={p.videoRef}
        selectedFlags={p.selectedFlags}
      />

      {/* ── Side panel ── */}
      <div className="w-80 bg-gray-900 border-l border-gray-800 flex flex-col overflow-y-auto">
        {post && (
          <PublishPanel
            post={post}
            pubBusy={p.pubBusy}
            busy={p.busy}
            publishPlatforms={p.publishPlatforms}
            togglePlatform={p.togglePlatform}
            cancel={p.cancel}
            reject={p.reject}
            refetchPosts={p.refetchPosts}
          />
        )}

        {/* Render — re-run edit + upload to regenerate the final reel, then
            fetch the fresh r2_url so the player shows the newly-rendered video. */}
        {media.media_type === "VIDEO" && (
          <div className="px-4 pt-4">
            <button
              disabled={p.renderBusy}
              onClick={p.renderVideo}
              title="Re-render the final video and fetch the updated r2_url"
              className="w-full flex items-center justify-center gap-2 py-2 text-sm rounded-lg bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 font-medium"
            >
              {p.renderBusy
                ? <><Loader2 size={14} className="animate-spin" /> Rendering…</>
                : <><Film size={14} /> Render video</>}
            </button>

            {/* Timeline editor (2.0.0). hydrate() synthesizes a one-cut EDL for
                single-clip reels, so this opens on any video, not just merges. */}
            {editorEnabled && (
              <Link
                to={`/editor/${media.id}`}
                className="mt-2 w-full flex items-center justify-center gap-2 py-2 text-sm rounded-lg
                           bg-indigo-700 hover:bg-indigo-600 font-medium"
                title="Open the timeline editor for this reel"
              >
                <Scissors size={14} /> Edit timeline
              </Link>
            )}
          </div>
        )}

        {/* Page-level edit progress — visible for every apply action (music,
            LUT, flags) regardless of whether the Edit drawer is open. */}
        {post && (
          <div className="px-4 pt-4">
            <EditProgress postId={post.id} onComplete={p.bumpVideoKey} />
          </div>
        )}

        <LocationPanel
          media={media}
          locEdit={p.locEdit}
          setLocEdit={p.setLocEdit}
          locCategory={p.locCategory}
          setLocCategory={p.setLocCategory}
          locTags={p.locTags}
          setLocTags={p.setLocTags}
          saveLocation={p.saveLocation}
          locPending={p.locPending}
          currentTrackUrl={p.currentTrackUrl}
          trackPlaying={p.trackPlaying}
          toggleTrack={p.toggleTrack}
        />

        <CaptionPanel
          captionDraft={p.captionDraft}
          captionDirty={p.captionDirty}
          editCaption={p.editCaption}
          saveCaption={p.saveCaption}
          discardCaption={p.discardCaption}
          saveCapPending={p.saveCapPending}
          regenBusy={p.regenBusy}
          doRegen={p.doRegen}
        />

        {post && <HashtagPanel post={post} />}

        <QuickFlagsPanel
          selectedFlags={p.selectedFlags}
          toggleFlag={p.toggleFlag}
          actionableFlagCount={p.actionableFlagCount}
          flagBusy={p.flagBusy}
          applyFlags={p.applyFlags}
        />

        {media.media_type === "VIDEO" && (
          <EnhancementPanel
            wmEnabled={p.wmEnabled}
            setWmEnabled={p.setWmEnabled}
            wmPosition={p.wmPosition}
            setWmPosition={p.setWmPosition}
            skipStabilize={p.skipStabilize}
            toggleSkipStabilize={p.toggleSkipStabilize}
            enhanceBusy={p.enhanceBusy}
            handleEnhance={p.handleEnhance}
          />
        )}

        {post && ["preview", "approved"].includes(post.status) && (
          <div className="p-4 border-t border-gray-800 space-y-2">
            <label className="text-xs font-semibold uppercase tracking-widest text-gray-500">Reschedule</label>
            <RescheduleInline postId={post.id} onDone={p.refetchPosts} />
          </div>
        )}

        {post && (
          <div className="p-4 border-t border-gray-800">
            <button
              onClick={() => p.setEditOpen(!p.editOpen)}
              className="w-full flex items-center justify-center gap-2 py-2 text-sm rounded-lg bg-gray-800 hover:bg-gray-700"
            >
              <Wand2 size={14} />
              {p.editOpen ? "Close edit" : "Edit (AI)"}
            </button>
          </div>
        )}

        {p.editOpen && post && (
          <EditDrawer
            media={media}
            editMusic={p.editMusic}
            setEditMusic={p.setEditMusic}
            editLut={p.editLut}
            setEditLut={p.setEditLut}
            editFeedback={p.editFeedback}
            setEditFeedback={p.setEditFeedback}
            editBusy={p.editBusy}
            applyMusic={p.applyMusic}
            applyLut={p.applyLut}
            handleDispatchEdit={p.handleDispatchEdit}
            locCategory={p.locCategory}
            locTags={p.locTags}
          />
        )}
      </div>
    </div>
  );
}
