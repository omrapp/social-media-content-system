import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useApi } from "@/hooks/useApi";
import { useApiMutation } from "@/hooks/useApiMutation";
import { api } from "@/lib/api";
import { onWsEvent } from "@/lib/ws";
import { toast } from "sonner";
import { MEDIA_BASE, resolveUrl, FLAGS, ACTIONABLE_FLAGS, type FlagKey } from "@/components/preview/shared";
import type { Media } from "@/types/media";
import type { Post } from "@/types/post";

const POSTS_KEY = ["api"];   // prefix — invalidates any query starting with ["api", "/posts…"]
const MEDIA_KEY = (id: string) => ["api", `/media/${id}`];

// All Preview page data, state, and handlers. The page + panels stay presentational.
export function usePreview(id: string | undefined) {
  const navigate = useNavigate();

  const { data: media, loading: mediaLoading, setData: setMediaData, refetch: refetchMedia } = useApi<Media>(id ? `/media/${id}` : null);
  const { data: postsRaw, refetch: refetchPosts } = useApi<Post[]>(id ? `/posts?media_id=${id}&limit=10` : null);
  // Queue order (same query the Queue page uses) drives prev/next navigation.
  const { data: queuePosts } = useApi<Post[]>("/posts?limit=500&sort=scheduled_desc");
  // Music catalog — resolves a playable URL for the post's current licensed track.
  const { data: musicList } = useApi<{ music: { id: string; url: string; title: string }[] }>("/assets/music");

  // The active post is the most recent preview/approved one
  const post = (postsRaw ?? []).find((p) => ["preview", "approved", "publishing"].includes(p.status))
    ?? postsRaw?.[0];

  // Prev/next media ids in Queue order (deduped, only posts with media).
  const orderedIds = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const p of queuePosts ?? []) {
      if (p.media_id && !seen.has(p.media_id)) { seen.add(p.media_id); out.push(p.media_id); }
    }
    return out;
  }, [queuePosts]);
  const navIdx = id ? orderedIds.indexOf(id) : -1;
  const prevId = navIdx > 0 ? orderedIds[navIdx - 1] : null;
  const nextId = navIdx >= 0 && navIdx < orderedIds.length - 1 ? orderedIds[navIdx + 1] : null;

  // Resolve a playable URL for the post's current licensed track (stored as a
  // bare filename) by matching it against the music catalog.
  const currentTrackUrl = useMemo(() => {
    const lm = media?.licensed_music;
    if (!lm) return null;
    const stem = lm.replace(/\.[^.]+$/, "");
    const hit = (musicList?.music ?? []).find((t) => t.id === stem || t.url.endsWith(lm));
    if (hit?.url) return hit.url;
    // Fallback: a licensed track muxed into the reel may not be in the browsable
    // catalog — play the cached file straight from the static music dir.
    return `/static/assets/music/${lm}`;
  }, [media?.licensed_music, musicList]);

  const [flags, setFlags]               = useState<Set<FlagKey>>(new Set());
  const [captionDraft, setCaptionDraft] = useState("");
  const [captionDirty, setCaptionDirty] = useState(false);
  const [editOpen, setEditOpen]         = useState(false);
  const [skipStabilize, setSkipStabilize] = useState(false);
  const [wmEnabled, setWmEnabled]       = useState(false);
  const [wmPosition, setWmPosition]     = useState<"bottom" | "top" | "both">("bottom");
  const [videoKey, setVideoKey]         = useState(0);
  const [editFeedback, setEditFeedback] = useState("");
  const [editMusic, setEditMusic]       = useState<{ id: string; url: string; startSec?: number; endSec?: number } | null>(null);
  const [editLut, setEditLut]           = useState("");
  // Location editing
  const [locEdit, setLocEdit]           = useState(false);
  const [locCategory, setLocCategory]   = useState("");
  const [locTags, setLocTags]           = useState<string[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);
  // Per-platform publish in-flight set — each platform publishes independently
  // so launching one never disables/hides the others.
  const [pubBusy, setPubBusy] = useState<Set<string>>(new Set());
  // Current-track audio preview
  const [trackPlaying, setTrackPlaying] = useState(false);
  const trackAudioRef = useRef<HTMLAudioElement | null>(null);

  // Seed caption draft from media
  useEffect(() => {
    if (media && !captionDirty) setCaptionDraft(media.caption ?? "");
  }, [media, captionDirty]);

  // Seed location fields from media
  useEffect(() => {
    if (media && !locEdit) {
      setLocCategory(media.category ?? "");
      setLocTags(media.tags ?? []);
    }
  }, [media?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Seed watermark + stabilize state from media metadata
  useEffect(() => {
    if (!media) return;
    const meta = (media as unknown as { metadata?: Record<string, unknown> }).metadata ?? {};
    if (typeof meta.watermark_removed === "boolean") setWmEnabled(meta.watermark_removed);
    if (meta.watermark_position === "top" || meta.watermark_position === "both") {
      setWmPosition(meta.watermark_position as "top" | "both");
    }
    if (typeof meta.skip_stabilize === "boolean") setSkipStabilize(meta.skip_stabilize);
  }, [media?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Real-time: refresh post status on WS event for this post
  useEffect(() => {
    if (!post?.id) return;
    return onWsEvent("post_status", (data) => {
      if (data.post_id === post.id) refetchPosts();
    });
  }, [post?.id, refetchPosts]);

  // WS: listen for edit complete → also refresh post
  useEffect(() => {
    if (!post?.id) return;
    return onWsEvent("edit_complete", (data) => {
      if (data.post_id === post.id) {
        toast.success("Edit complete — video updated");
        refetchPosts();
        // Pull the fresh media row (new r2_url / licensed_music) after the edit
        // stage re-uploaded to R2, then cache-bust the player so the newly
        // rendered file loads even when the Edit drawer is closed.
        refetchMedia();
        setVideoKey((k) => k + 1);
      }
    });
  }, [post?.id, refetchPosts, refetchMedia]);

  // ── Mutations ─────────────────────────────────────────────────────────────

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
    successMessage: false,
    onSuccess: () => navigate("/queue"),
  });

  const saveCapMut = useApiMutation<void, [string, { caption: string }]>({
    method: "put",
    invalidates: [POSTS_KEY],
    successMessage: "Caption saved",
    onSuccess: () => setCaptionDirty(false),
  });

  const locMut = useApiMutation<void, [string, { category: string; tags: string[] }]>({
    method: "put",
    invalidates: id ? [MEDIA_KEY(id)] : [],
    successMessage: "Location saved",
    onSuccess: () => setLocEdit(false),
  });

  const platformMut = useApiMutation<void, [string, { platforms: string[] }]>({
    method: "put",
    invalidates: [POSTS_KEY],
    successMessage: false,
  });

  // ── Handlers ──────────────────────────────────────────────────────────────

  // Publish specific platforms independently. Each platform tracks its own busy
  // state so publishing one keeps the others' buttons enabled.
  const publishPlatforms = useCallback(async (platforms: string[]) => {
    if (!post || platforms.length === 0) return;
    setPubBusy((prev) => new Set([...prev, ...platforms]));
    try {
      await api.post(`/posts/${post.id}/approve-platforms`, { platforms });
      toast.success(`Publishing ${platforms.join(", ")}…`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Publish failed");
    } finally {
      setPubBusy((prev) => {
        const n = new Set(prev);
        platforms.forEach((p) => n.delete(p));
        return n;
      });
      refetchPosts();
    }
  }, [post, refetchPosts]);

  // Play/stop the post's current music track.
  const toggleTrack = useCallback(() => {
    if (!currentTrackUrl) return;
    if (trackPlaying) {
      trackAudioRef.current?.pause();
      setTrackPlaying(false);
      return;
    }
    if (!trackAudioRef.current) trackAudioRef.current = new Audio();
    trackAudioRef.current.src = currentTrackUrl.startsWith("http")
      ? currentTrackUrl : `${MEDIA_BASE}${currentTrackUrl}`;
    trackAudioRef.current.onended = () => setTrackPlaying(false);
    trackAudioRef.current.play()
      .then(() => setTrackPlaying(true))
      .catch((e) => {
        setTrackPlaying(false);
        toast.error(e instanceof Error ? `Could not play track: ${e.message}` : "Could not play track");
      });
  }, [currentTrackUrl, trackPlaying]);

  // Stop track audio on unmount and whenever the previewed media changes.
  useEffect(() => {
    trackAudioRef.current?.pause();
    setTrackPlaying(false);
    return () => { trackAudioRef.current?.pause(); };
  }, [id]);

  const cancel = () => post && cancelMut.mutate(`/posts/${post.id}/cancel`);
  const reject = async () => {
    if (!post) return;
    if (!window.confirm("Permanently delete this video? This removes the post, media record, and all files and cannot be undone.")) return;
    rejectMut.mutate(`/posts/${post.id}/reject`);
  };

  const saveLocation = useCallback(() => {
    if (!media) return;
    locMut.mutate([`/media/${media.id}`, { category: locCategory, tags: locTags }]);
  }, [media, locCategory, locTags, locMut]);

  const regenCaption = useCallback(async () => {
    if (!media) return;
    try {
      const res = await api.post("/captions/generate", {
        media_id: media.id,
        category: locCategory || media.category,
        tags: locTags.length ? locTags : media.tags,
      }) as {
        caption?: string; hashtags_en?: string[]; hashtags_ar?: string[];
        caption_ig?: string; caption_tt?: string;
        caption_yt_title?: string; caption_yt_description?: string;
      };
      if (res?.caption) {
        setCaptionDraft(res.caption);
        if (post) {
          await api.put(`/posts/${post.id}`, {
            caption: res.caption,
            ...(res.hashtags_en && { hashtags_en: res.hashtags_en }),
            ...(res.hashtags_ar && { hashtags_ar: res.hashtags_ar }),
            // Keep per-platform captions in sync so IG/TikTok/YouTube don't
            // publish the stale pre-regen text.
            ...(res.caption_ig && { caption_ig: res.caption_ig }),
            ...(res.caption_tt && { caption_tt: res.caption_tt }),
            ...(res.caption_yt_title && { caption_yt_title: res.caption_yt_title }),
            ...(res.caption_yt_description && { caption_yt_description: res.caption_yt_description }),
          });
          setCaptionDirty(false);
          toast.success("Caption regenerated and saved");
        } else {
          setCaptionDirty(true);
          toast.info("Caption regenerated — save when ready");
        }
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Regeneration failed");
    }
  }, [media, post, locCategory, locTags]);

  // regenBusy: managed separately since we do it inline (not via useApiMutation)
  const [regenBusy, setRegenBusy] = useState(false);
  const doRegen = useCallback(async () => {
    setRegenBusy(true);
    await regenCaption();
    setRegenBusy(false);
  }, [regenCaption]);

  const saveCaption = () => {
    if (!post) return;
    saveCapMut.mutate([`/posts/${post.id}`, { caption: captionDraft }]);
  };
  const discardCaption = () => { setCaptionDraft(media?.caption ?? ""); setCaptionDirty(false); };
  const editCaption = (v: string) => { setCaptionDraft(v); setCaptionDirty(true); };

  const saveFlags = useCallback(async () => {
    if (!post) return;
    const editRequests = Array.from(flags).map((key) => ({ stage: key, params: {} }));
    try {
      await api.put(`/posts/${post.id}`, { edit_requests: editRequests });
    } catch {
      toast.error("Failed to save flags");
    }
  }, [post, flags]);

  const toggleFlag = (key: FlagKey) => {
    setFlags((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  // Auto-save flags after change
  useEffect(() => { if (flags.size > 0) saveFlags(); }, [flags, saveFlags]);

  // Re-render the video for the actionable subset of selected flags (music /
  // color / aspect / clip-order). Caption/category flags stay annotation-only.
  const actionableFlags = useMemo(
    () => Array.from(flags).filter((f) => ACTIONABLE_FLAGS.has(f)),
    [flags],
  );
  const [flagBusy, setFlagBusy] = useState(false);
  const applyFlags = useCallback(async () => {
    if (!post || actionableFlags.length === 0) return;
    setFlagBusy(true);
    try {
      const labels = actionableFlags
        .map((k) => FLAGS.find((f) => f.key === k)?.label ?? k)
        .join(", ");
      await api.post(`/posts/${post.id}/edit`, {
        feedback: `Re-render the video addressing these issues: ${labels}.`,
        flags: actionableFlags,
        picks: {},
      });
      toast.success("Flags apply dispatched — watch progress");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to apply flags");
    } finally {
      setFlagBusy(false);
    }
  }, [post, actionableFlags]);

  const doEnhance = useCallback(async () => {
    if (!media) return;
    try {
      const result = await api.post(`/media/${media.id}/enhance`, {
        remove_watermarks: wmEnabled,
        watermark_position: wmPosition,
        stabilize: false,
      }) as { ok: boolean; media?: Media };
      // Endpoint is synchronous — inject returned media into cache, then remount video.
      if (result.media) setMediaData(result.media);
      setVideoKey((k) => k + 1);
      toast.success("Enhancement applied");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Enhancement failed");
    }
  }, [media, wmEnabled, wmPosition, setMediaData]);

  const [enhanceBusy, setEnhanceBusy] = useState(false);
  const handleEnhance = useCallback(async () => {
    setEnhanceBusy(true);
    await doEnhance();
    setEnhanceBusy(false);
  }, [doEnhance]);

  const toggleSkipStabilize = useCallback(async (val: boolean) => {
    if (!media) return;
    setSkipStabilize(val);
    try {
      await api.put(`/media/${media.id}`, { metadata: { skip_stabilize: val } });
    } catch {
      setSkipStabilize(!val); // revert on failure
    }
  }, [media]);

  const [editBusy, setEditBusy] = useState(false);

  // One-click apply: music swap (no free-text required)
  const applyMusic = useCallback(async () => {
    if (!post || !editMusic) return;
    setEditBusy(true);
    try {
      await api.post(`/posts/${post.id}/edit`, {
        feedback: "Swap the background music to the selected track.",
        flags: [],
        picks: { music_swap: { track_id: editMusic.id, url: editMusic.url, ...(editMusic.startSec != null && { start_sec: editMusic.startSec }), ...(editMusic.endSec != null && { end_sec: editMusic.endSec }) } },
      });
      toast.success("Music apply dispatched");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to apply music");
    } finally {
      setEditBusy(false);
    }
  }, [post, editMusic]);

  // One-click apply: LUT color grade (no free-text required)
  const applyLut = useCallback(async () => {
    if (!post || !editLut) return;
    setEditBusy(true);
    try {
      await api.post(`/posts/${post.id}/edit`, {
        feedback: "Apply the selected color grade LUT.",
        flags: [],
        picks: { color_grade: { lut: editLut } },
      });
      toast.success("LUT apply dispatched");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to apply LUT");
    } finally {
      setEditBusy(false);
    }
  }, [post, editLut]);

  const handleDispatchEdit = useCallback(async () => {
    if (!post || !editFeedback.trim()) return;
    setEditBusy(true);
    try {
      const picks: Record<string, unknown> = {};
      if (editMusic) picks.music_swap = { track_id: editMusic.id, url: editMusic.url, ...(editMusic.startSec != null && { start_sec: editMusic.startSec }), ...(editMusic.endSec != null && { end_sec: editMusic.endSec }) };
      if (editLut)   picks.color_grade = { lut: editLut };
      await api.post(`/posts/${post.id}/edit`, {
        feedback: editFeedback,
        flags: Array.from(flags),
        picks,
      });
      toast.success("Dispatched — watch progress below");
      setEditFeedback("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Dispatch failed");
    } finally {
      setEditBusy(false);
    }
  }, [post, editFeedback, editMusic, editLut, flags]);

  const togglePlatform = useCallback((p: string) => {
    if (!post) return;
    const current = post.platforms ?? ["instagram"];
    const updated = current.includes(p) ? current.filter((x) => x !== p) : [...current, p];
    platformMut.mutate([`/posts/${post.id}`, { platforms: updated }]);
  }, [post, platformMut]);

  const bumpVideoKey = useCallback(() => setVideoKey((k) => k + 1), []);

  // Re-render the final reel (video_edit) and re-upload to R2, then pull the
  // fresh media row so the player loads the newly-rendered r2_url.
  const [renderBusy, setRenderBusy] = useState(false);
  const renderVideo = useCallback(async () => {
    if (!media) return;
    setRenderBusy(true);
    try {
      await api.post("/pipeline/orchestrate", {
        stages: ["edit", "upload"],
        media_id: media.id,
      });
      const fresh = await api.get<Media>(`/media/${media.id}`);
      if (fresh) setMediaData(fresh);
      refetchMedia();
      refetchPosts();
      setVideoKey((k) => k + 1); // cache-bust the player onto the new r2_url
      toast.success("Render complete — video updated");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Render failed");
    } finally {
      setRenderBusy(false);
    }
  }, [media, setMediaData, refetchMedia, refetchPosts]);

  // Global busy gates Cancel/Reject only — per-platform publish has its own pubBusy.
  const busy = approveMut.isPending || cancelMut.isPending || rejectMut.isPending;

  const videoUrl = media ? resolveUrl(media) : "";

  return {
    navigate,
    media, mediaLoading, post,
    // navigation
    orderedIds, navIdx, prevId, nextId,
    // video
    videoUrl, videoKey, videoRef, bumpVideoKey,
    renderVideo, renderBusy,
    // track preview
    currentTrackUrl, trackPlaying, toggleTrack,
    // flags
    selectedFlags: flags, toggleFlag,
    actionableFlagCount: actionableFlags.length, flagBusy, applyFlags,
    // caption
    captionDraft, captionDirty, editCaption, saveCaption, discardCaption,
    saveCapPending: saveCapMut.isPending, regenBusy, doRegen,
    // location
    locEdit, setLocEdit, locCategory, setLocCategory, locTags, setLocTags,
    saveLocation, locPending: locMut.isPending,
    // enhancement
    wmEnabled, setWmEnabled, wmPosition, setWmPosition,
    skipStabilize, toggleSkipStabilize, enhanceBusy, handleEnhance,
    // publish
    pubBusy, busy, publishPlatforms, togglePlatform, cancel, reject,
    // edit drawer
    editOpen, setEditOpen, editMusic, setEditMusic, editLut, setEditLut,
    editFeedback, setEditFeedback, editBusy, applyMusic, applyLut, handleDispatchEdit,
    // misc
    refetchPosts,
  };
}

export type UsePreview = ReturnType<typeof usePreview>;
