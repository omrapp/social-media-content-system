// Demo-mode fixture layer: answers every /api/* call with in-memory sample data.
// State lives for the page session, so mutations (approve, edit, delete…) feel
// real until reload. All data is generic and non-personal (brand "@yourbrand").
import { emitLocalWsEvent } from "@/lib/ws";
import { SETTINGS_DEFAULTS } from "./settingsDefaults";
import type { Media } from "@/types/media";
import type { Post } from "@/types/post";
import type { Notification } from "@/types/notifications";
import type { PipelineRun } from "@/types/pipeline";
import type { AssetItem, AssetType } from "@/types/assets";
import type { Track } from "@/types/audio";
import type { StockClip } from "@/types/downloads";
import type { Cut, EDL, EditorVersion } from "@/types/editor";

const asset = (p: string) => `${import.meta.env.BASE_URL}demo/${p}`;
/** Absolute URL — editor proxies are joined to API_ORIGIN unless they start with http. */
const absAsset = (p: string) => `${window.location.origin}${asset(p)}`;

// ── helpers ──────────────────────────────────────────────────────────────────

const NOW = Date.now();
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
const iso = (ms: number) => new Date(ms).toISOString();

/** Deterministic PRNG so the demo looks the same on every load. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}
const rand = rng(42);

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const later = (ms: number, fn: () => void) => setTimeout(fn, ms);
const emit = (event: string, data: Record<string, unknown> = {}) => emitLocalWsEvent({ event, ...data });

// ── taxonomy ─────────────────────────────────────────────────────────────────

interface Theme { category: string; title: string; tags: string[]; hook: string; ar: string; hashtags: string[] }

const THEMES: Theme[] = [
  { category: "food", title: "Street Food Tour", tags: ["street food", "night market", "snacks"],
    hook: "5 bites you can't skip on a street food night", ar: "جولة طعام الشارع: خمس لقمات لا تفوّت",
    hashtags: ["streetfood", "foodie", "foodtour", "eatlocal", "reels"] },
  { category: "fitness", title: "Morning HIIT", tags: ["hiit", "workout", "morning routine"],
    hook: "A 6-minute HIIT that wakes you up faster than coffee", ar: "تمرين صباحي سريع لمدة ست دقائق",
    hashtags: ["hiit", "workout", "fitness", "morningroutine", "reels"] },
  { category: "nature", title: "Mountain Sunrise", tags: ["sunrise", "mountains", "hiking"],
    hook: "Woke up at 4am for this view. Worth it.", ar: "شروق الشمس فوق الجبال يستحق الاستيقاظ المبكر",
    hashtags: ["sunrise", "mountains", "hiking", "naturelovers", "reels"] },
  { category: "culture", title: "Old Town Walk", tags: ["old town", "architecture", "walking tour"],
    hook: "Every corner of this old town has a story", ar: "كل زاوية في البلدة القديمة تحكي قصة",
    hashtags: ["oldtown", "architecture", "culture", "walkingtour", "reels"] },
  { category: "tech", title: "Desk Setup 2026", tags: ["desk setup", "productivity", "gadgets"],
    hook: "The desk setup that finally fixed my focus", ar: "مكتب العمل الذي حسّن تركيزي",
    hashtags: ["desksetup", "productivity", "techtok", "workspace", "reels"] },
  { category: "beach", title: "Golden Hour Waves", tags: ["golden hour", "waves", "coastline"],
    hook: "Golden hour hits different by the water", ar: "الساعة الذهبية على الشاطئ لها سحر خاص",
    hashtags: ["goldenhour", "beachvibes", "ocean", "sunset", "reels"] },
  { category: "lifestyle", title: "Coffee Ritual", tags: ["coffee", "slow morning", "routine"],
    hook: "My 3-minute coffee ritual for calmer mornings", ar: "طقوس القهوة الصباحية في ثلاث دقائق",
    hashtags: ["coffee", "slowliving", "morningritual", "lifestyle", "reels"] },
  { category: "travel", title: "City Lights", tags: ["city", "night", "skyline"],
    hook: "This skyline after dark is pure cinema", ar: "أضواء المدينة ليلاً كأنها مشهد سينمائي",
    hashtags: ["citylights", "nightphotography", "travel", "skyline", "reels"] },
];
const CATEGORIES = THEMES.map((t) => t.category);
const ALL_TAGS = Array.from(new Set(THEMES.flatMap((t) => t.tags))).sort();
const clipNo = (i: number) => String((i % 8) + 1).padStart(2, "0");

function captionFor(t: Theme) {
  return `${t.hook} ✨\n\nSave this for later and send it to someone who needs it.\n\n${t.ar}`;
}

// ── media ────────────────────────────────────────────────────────────────────

type DemoMedia = Media & { metadata?: Record<string, unknown>; duration_s?: number; created_at?: string };

// 23 single clips spread across the pipeline + 1 merged reel.
const STATUS_PLAN = [
  "posted", "preview", "scheduled", "raw", "edited", "posted", "raw", "uploaded",
  "posted", "resized", "preview", "raw", "posted", "scheduled", "raw", "edited",
  "error", "raw", "resized", "uploaded", "posted", "raw", "resized",
];

const media: DemoMedia[] = STATUS_PLAN.map((status, i) => {
  const t = THEMES[i % 8];
  const n = clipNo(i);
  const processed = status !== "raw";
  return {
    id: `med_${(0x3a10 + i * 37).toString(16)}${String(i).padStart(2, "0")}`,
    source: i % 7 === 5 ? "upload" : i % 9 === 8 ? "stock" : "instagram",
    media_type: "VIDEO",
    caption: processed && status !== "resized" ? captionFor(t) : "",
    status,
    category: t.category,
    tags: t.tags,
    thumbnail_url: asset(`media/clip${n}.jpg`),
    r2_url: asset(`media/clip${n}.mp4`),
    hook_score: Math.round((0.55 + rand() * 0.4) * 100) / 100,
    taken_at: iso(NOW - (i + 1) * 2.5 * DAY),
    created_at: iso(NOW - (i + 1) * 2.5 * DAY),
    duration_s: 6,
    music_source: processed ? (i % 3 === 0 ? "original" : "licensed") : "unknown",
    licensed_music: processed && i % 3 !== 0 ? "upbeat_summer.mp3" : undefined,
    original_caption: `${t.title} — ${t.tags.join(", ")}`,
    metadata: {},
    ...(t.category === "fitness" && i < 16
      ? { series_id: "ser_fit", episode_number: i < 8 ? 1 : 2, episode_total: 4, series_arc_position: i < 8 ? "opener" : "build" }
      : {}),
  };
});

const MERGE_ID = "mrg_7c1e2a90";
media.unshift({
  id: MERGE_ID,
  source: "merge",
  media_type: "VIDEO",
  caption: `Eight moments, one week of content 🎬\n\nWhich one is your favourite? Tell me below.\n\nثماني لحظات في أسبوع واحد من المحتوى`,
  status: "preview",
  category: "travel",
  tags: ["montage", "highlights", "city"],
  thumbnail_url: asset("media/clip08.jpg"),
  r2_url: asset("media/clip08.mp4"),
  hook_score: 0.91,
  taken_at: iso(NOW - 6 * HOUR),
  created_at: iso(NOW - 6 * HOUR),
  duration_s: 18,
  music_source: "licensed",
  licensed_music: "upbeat_summer.mp3",
  metadata: { merge: { source_ids: [] as string[] } },
});

const findMedia = (id: string) => media.find((m) => m.id === id);

// ── posts ────────────────────────────────────────────────────────────────────

let postSeq = 1;
const newPostId = () => `pst_${(0x5b20 + postSeq++ * 53).toString(16)}`;

function makePost(m: DemoMedia, status: string, scheduledAt: number, extra: Partial<Post> = {}): Post {
  const t = THEMES.find((x) => x.category === m.category) ?? THEMES[7];
  return {
    id: newPostId(),
    media_id: m.id,
    caption: m.caption || captionFor(t),
    status,
    scheduled_at: iso(scheduledAt),
    publish_after: status === "preview" ? iso(scheduledAt + 60 * MIN) : undefined,
    hashtags_en: t.hashtags,
    hashtags_ar: ["محتوى", "ريلز", "إلهام"],
    approval_status: status === "posted" ? "approved" : status === "rejected" ? "rejected" : "pending",
    platforms: ["instagram", "youtube", "tiktok"].slice(0, status === "posted" ? 3 : 2),
    ...extra,
  };
}

const posts: Post[] = [];
{
  let future = 0;
  let past = 0;
  for (const m of media) {
    if (m.status === "preview") {
      future += 1;
      posts.push(makePost(m, "preview", NOW + future * 3 * HOUR - 40 * MIN));
    } else if (m.status === "scheduled") {
      future += 1;
      posts.push(makePost(m, "scheduled", NOW + future * 5 * HOUR));
    } else if (m.status === "posted") {
      past += 1;
      posts.push(makePost(m, "posted", NOW - past * 1.5 * DAY, {
        ig_media_id: `1790${past}4471${past}`,
        yt_video_id: `dQw${past}Demo${past}`,
        tiktok_video_id: past === 2 ? undefined : `73${past}0099${past}`,
        tiktok_error: past === 2 ? "TikTok rate limit — retry scheduled" : undefined,
        approved_at: iso(NOW - past * 1.5 * DAY - HOUR),
      }));
    } else if (m.status === "error") {
      posts.push(makePost(m, "error", NOW - 12 * HOUR, { yt_error: "Upload timed out" }));
    }
  }
  const rej = media.find((m) => m.status === "edited");
  if (rej) posts.push(makePost(rej, "rejected", NOW - 2 * DAY, { feedback: "Music too loud" }));
}
const findPost = (id: string) => posts.find((p) => p.id === id);

// ── settings ─────────────────────────────────────────────────────────────────

const settings: Record<string, Record<string, unknown>> = clone(SETTINGS_DEFAULTS);
const SECRETS_SET: Record<string, boolean> = {
  "telegram.bot_token": true,
  "ai.groq_api_key": true,
  "ai.openrouter_api_key": true,
  "platforms.youtube_client_secret": true,
  "platforms.youtube_refresh_token": true,
  "platforms.tiktok_client_secret": false,
  "platforms.tiktok_access_token": false,
  "uploads.google_client_secret": false,
  "uploads.google_refresh_token": false,
  "stock.pexels_api_key": true,
  "stock.pixabay_api_key": false,
};

// ── assets ───────────────────────────────────────────────────────────────────

function assetRow(type: AssetType, i: number, name: string, filename: string, url: string | null, extra: Partial<AssetItem> = {}): AssetItem {
  return {
    id: `ast_${type}_${i}`,
    type,
    name,
    filename,
    local_path: `${type === "lut" ? "luts" : type === "font" ? "fonts" : type + "s"}/${filename}`,
    url,
    local_exists: true,
    size_bytes: 40_000 + Math.round(rand() * 900_000),
    parent_asset_id: null,
    meta: {},
    created_at: iso(NOW - (i + 3) * 4 * DAY),
    favourite: i % 3 === 0,
    usage_count: Math.round(rand() * 30),
    tags: [],
    last_used_at: i % 2 ? iso(NOW - i * DAY) : null,
    mood: null,
    ...extra,
  };
}

const assets: AssetItem[] = [
  ...["Inter", "Playfair Display", "Montserrat", "Bebas Neue", "DM Serif", "Space Grotesk"].map((n, i) =>
    assetRow("font", i, n, `${n.replace(/\s+/g, "")}-Regular.ttf`, null)),
  ...[
    ["Teal & Orange", "cinematic/teal_orange.cube", ["cinematic", "warm"]],
    ["Golden Hour", "cinematic/golden_hour.cube", ["warm", "sunset"]],
    ["Moody Blue", "cinematic/moody_blue.cube", ["cool", "moody"]],
    ["Clean Bright", "bright_clean.cube", ["bright"]],
    ["Vintage Film", "vintage_film.cube", ["film", "retro"]],
    ["Night City", "cinematic/night_city.cube", ["cool", "night"]],
  ].map(([n, f, tags], i) =>
    assetRow("lut", i, n as string, (f as string).split("/").pop()!, null, {
      local_path: `luts/${f}`, tags: tags as string[],
      meta: { categories: [CATEGORIES[i % 8], CATEGORIES[(i + 3) % 8]], intensity: 0.8 },
    })),
  ...["Brand Sting", "Logo Reveal", "Swipe Intro"].map((n, i) =>
    assetRow("intro", i, n, `${n.toLowerCase().replace(/\s+/g, "_")}.mp4`, asset(`media/clip0${i + 1}.mp4`), { meta: { category: CATEGORIES[i] } })),
  ...["Follow Card", "Subscribe End", "See You Soon"].map((n, i) =>
    assetRow("outro", i, n, `${n.toLowerCase().replace(/\s+/g, "_")}.jpg`, asset(`media/clip0${i + 5}.jpg`), { meta: { category: CATEGORIES[i + 4] } })),
];

// Music: no demo audio ships, so tracks reuse the clips' own audio stream.
const TRACK_DEFS: [string, string, string, string[]][] = [
  ["upbeat_summer", "Upbeat Summer", "happy", ["beach", "travel"]],
  ["lofi_morning", "Lo-fi Morning", "calm", ["lifestyle", "tech"]],
  ["epic_rise", "Epic Rise", "epic", ["nature", "travel"]],
  ["street_groove", "Street Groove", "energetic", ["food", "culture"]],
  ["pulse_run", "Pulse Run", "energetic", ["fitness"]],
  ["ambient_coast", "Ambient Coast", "calm", ["beach", "nature"]],
  ["neon_nights", "Neon Nights", "moody", ["travel", "tech"]],
  ["acoustic_cafe", "Acoustic Café", "warm", ["lifestyle", "food"]],
];
let tracks: Track[] = TRACK_DEFS.map(([id, title, mood, cats], i) => ({
  id,
  filename: `${id}.mp3`,
  title,
  source: i % 3 === 0 ? "jamendo" : "local",
  duration: 95 + Math.round(rand() * 120),
  popularity: Math.round(rand() * 100),
  license: "CC BY 4.0",
  mood,
  categories: cats,
  favourite: i % 3 === 0,
  usage_count: Math.round(rand() * 25),
  last_used_at: i % 2 ? iso(NOW - i * DAY) : null,
  url: asset(`media/clip${clipNo(i)}.mp4`),
}));

const stickers = ["Brand Badge", "Sale Tag", "Subscribe Arrow"].map((name, i) => ({
  id: `stk_${i}`,
  name,
  file: `${name.toLowerCase().replace(/\s+/g, "_")}.png`,
  asset: `stickers/${name.toLowerCase().replace(/\s+/g, "_")}.png`,
  url: asset(`media/clip0${i + 2}.jpg`),
}));

// ── notifications / runs ─────────────────────────────────────────────────────

const notifications: Notification[] = [
  { id: "ntf_1", type: "success", title: "Reel published", message: "\"Golden Hour Waves\" is live on Instagram, YouTube and TikTok.", read: false, created_at: iso(NOW - 25 * MIN) },
  { id: "ntf_2", type: "info", title: "Preview ready", message: "A new merged reel is waiting for approval.", read: false, created_at: iso(NOW - 6 * HOUR) },
  { id: "ntf_3", type: "warning", title: "TikTok rate limit", message: "One upload was deferred and will retry automatically.", read: false, created_at: iso(NOW - 20 * HOUR) },
  { id: "ntf_4", type: "success", title: "Captions generated", message: "12 captions generated (EN + AR).", read: true, created_at: iso(NOW - 1.5 * DAY) },
  { id: "ntf_5", type: "error", title: "Upload failed", message: "YouTube upload timed out — retry from the Queue.", read: true, created_at: iso(NOW - 2 * DAY) },
  { id: "ntf_6", type: "info", title: "Weekly digest", message: "Reach up 18% week over week.", read: true, created_at: iso(NOW - 4 * DAY) },
];

const STAGES = ["index", "classify", "resize", "enhance", "edit", "upload", "caption", "schedule"];
let runSeq = 1;
const runs: PipelineRun[] = Array.from({ length: 18 }, (_, i) => {
  const at = NOW - i * 3.3 * HOUR - 7 * MIN;
  return {
    id: `run_${1000 - i}`,
    stage: STAGES[i % STAGES.length],
    status: i === 5 ? "error" : "success",
    items_processed: 1 + Math.round(rand() * 14),
    items_failed: i === 5 ? 1 : 0,
    started_at: iso(at),
    created_at: iso(at),
  };
});
function logRun(stage: string, processed = 1, status = "success") {
  const r: PipelineRun = { id: `run_${2000 + runSeq++}`, stage, status, items_processed: processed, items_failed: 0, started_at: iso(Date.now()), created_at: iso(Date.now()) };
  runs.unshift(r);
}

// ── stock ────────────────────────────────────────────────────────────────────

let stockClips: (StockClip & { key: string })[] = [
  ["pexels", "beach", ["waves", "drone"], 7],
  ["pexels", "beach", ["sand", "sunset"], 6],
  ["pixabay", "nature", ["forest", "fog"], 3],
  ["pexels", "travel", ["skyline", "timelapse"], 8],
  ["pixabay", "food", ["coffee", "pour"], 7],
].map(([provider, category, tags], i) => ({
  id: `stk_${(0x9f00 + i * 17).toString(16)}`,
  key: `${provider}:${48120 + i}`,
  provider: provider as string,
  provider_id: String(48120 + i),
  category: category as string,
  tags: tags as string[],
  status: "raw",
  width: 720,
  height: 1280,
  duration_s: 8 + i * 2,
  size_mb: 6.2 + i * 1.3,
  created_at: iso(NOW - (i + 1) * 3 * DAY),
}));

// ── analytics ────────────────────────────────────────────────────────────────

const timeseries = Array.from({ length: 30 }, (_, i) => {
  const day = 29 - i;
  const growth = 1 + i * 0.045;
  const wobble = 0.85 + rand() * 0.3;
  const reach = Math.round(1800 * growth * wobble);
  return {
    fetched_at: iso(NOW - day * DAY),
    reach,
    impressions: Math.round(reach * (1.35 + rand() * 0.2)),
    likes: Math.round(reach * (0.065 + rand() * 0.02)),
    comments: Math.round(reach * (0.006 + rand() * 0.004)),
    saves: Math.round(reach * (0.018 + rand() * 0.01)),
  };
});

function countBy<T>(arr: T[], key: (t: T) => string) {
  const out: Record<string, number> = {};
  for (const x of arr) out[key(x)] = (out[key(x)] ?? 0) + 1;
  return out;
}
const liveMedia = () => media.filter((m) => m.status !== "deleted");

// ── editor ───────────────────────────────────────────────────────────────────

function hydrate(mediaId: string): EDL {
  const m = findMedia(mediaId);
  const isMerge = mediaId.startsWith("mrg_");
  const n = isMerge ? 8 : 1;
  const transitions = ["fade", "dissolve", "slideup", "wipeleft", "smoothleft", "circleopen", "fade", "fade"];
  const cuts: Cut[] = Array.from({ length: n }, (_, i) => {
    const src = isMerge ? media.find((x) => x.r2_url.endsWith(`clip${clipNo(i)}.mp4`) && x.id !== mediaId) : m;
    const inS = isMerge ? 0.4 + (i % 3) * 0.3 : 0;
    return {
      id: `c${i + 1}`,
      src_media_id: src?.id ?? mediaId,
      in_s: Math.round(inS * 10) / 10,
      out_s: isMerge ? Math.round((inS + 2.4 + (i % 2) * 0.6) * 10) / 10 : 6,
      speed: i % 4 === 2 ? 0.85 : 1,
      smooth_slowmo: false,
      ken_burns: { enabled: i % 2 === 0, direction: i % 4 === 0 ? "in" : "out", drift: i % 3 === 1 ? 1 : 0 },
      transition: { name: transitions[i], duration_s: i % 3 === 2 ? 0.04 : 0.4 },
    };
  });
  return {
    edl_version: 1,
    source_media_id: mediaId,
    approx: false,
    canvas: { w: 1080, h: 1920, fps: 30 },
    cuts,
    reel: {
      grade: { profile: isMerge ? "cinematic_warm" : "", deband: true, grain: false, vignette: isMerge },
      lut: null,
      eq: { brightness: 0, contrast: 1.05, saturation: 1.1 },
      audio_mode: "original",
      music: { path: null, volume: 0.15, fade_s: 1, start_offset_s: null, duck_volume: null },
      voiceover: false,
      branding: true,
      intro: { enabled: true },
      cast: { enabled: false },
      loop_friendly: false,
    },
    layers: {
      text: [
        { id: "t1", content: "One week of content", font: "", size: 64, color: "#ffffff", x: 0.5, y: 0.18, anchor: "center", start_s: 0, end_s: 3, animation: "fade" },
        { id: "t2", content: "@yourbrand", font: "", size: 40, color: "#fbbf24", x: 0.5, y: 0.88, anchor: "center", start_s: 0.5, end_s: 16, animation: "none" },
      ],
      image: [],
    },
  };
}

const editorVersions: Record<string, (EditorVersion & { edl: EDL })[]> = {};
{
  const base = hydrate(MERGE_ID);
  editorVersions[MERGE_ID] = [
    { id: "ver_2", version: 2, label: "Tighter opening", approx: false, created_at: iso(NOW - 2 * HOUR), edl: base },
    { id: "ver_1", version: 1, label: null, approx: false, created_at: iso(NOW - 5 * HOUR), edl: hydrate(MERGE_ID) },
  ];
}

function editorDoc(mediaId: string, fresh: boolean) {
  const v = editorVersions[mediaId]?.[0];
  if (v && !fresh) {
    return { media_id: mediaId, edl: clone(v.edl), approx: v.approx, version: v.version, project_id: `prj_${mediaId}`, saved_at: v.created_at };
  }
  return { media_id: mediaId, edl: hydrate(mediaId), approx: false, version: 0, project_id: v ? `prj_${mediaId}` : null, saved_at: null };
}

// ── simulated background work ────────────────────────────────────────────────

function simulatePipeline(mediaId: string, stages: string[], onDone?: () => void) {
  stages.forEach((stage, i) => later(500 + i * 650, () => emit("pipeline_start", { stage, media_id: mediaId })));
  later(500 + stages.length * 650, () => {
    onDone?.();
    stages.forEach((s) => logRun(s));
    emit("pipeline_complete", { media_id: mediaId, stage: stages[stages.length - 1] });
    emit("post_status", { media_id: mediaId });
  });
}

function promoteToPreview(m: DemoMedia) {
  const t = THEMES.find((x) => x.category === m.category) ?? THEMES[0];
  m.status = "preview";
  if (!m.caption) m.caption = captionFor(t);
  if (!posts.some((p) => p.media_id === m.id && p.status === "preview")) {
    posts.unshift(makePost(m, "preview", NOW + 26 * HOUR));
  }
}

// ── query filters ────────────────────────────────────────────────────────────

function filterMedia(q: URLSearchParams) {
  let list = liveMedia();
  const status = q.get("status");
  const category = q.get("category");
  const tags = q.getAll("tags");
  const search = (q.get("q") ?? "").toLowerCase();
  if (status && status !== "all") list = list.filter((m) => m.status === status);
  if (category && category !== "all") list = list.filter((m) => m.category === category);
  if (tags.length) list = list.filter((m) => tags.every((t) => (m.tags ?? []).includes(t)));
  if (search) list = list.filter((m) => `${m.caption} ${(m.tags ?? []).join(" ")} ${m.category}`.toLowerCase().includes(search));
  const sort = q.get("sort") ?? "taken_at_desc";
  list = [...list].sort((a, b) => {
    if (sort.startsWith("hook")) return (b.hook_score ?? 0) - (a.hook_score ?? 0);
    const d = new Date(b.taken_at ?? 0).getTime() - new Date(a.taken_at ?? 0).getTime();
    return sort.endsWith("_asc") ? -d : d;
  });
  const offset = Number(q.get("offset") ?? 0);
  const limit = Number(q.get("limit") ?? 50);
  return list.slice(offset, offset + limit);
}

function filterPosts(q: URLSearchParams) {
  let list = [...posts];
  const status = q.get("status");
  const mediaId = q.get("media_id");
  if (status) list = list.filter((p) => p.status === status);
  if (mediaId) list = list.filter((p) => p.media_id === mediaId);
  const asc = q.get("sort") === "scheduled_asc";
  list.sort((a, b) => {
    const d = new Date(b.scheduled_at).getTime() - new Date(a.scheduled_at).getTime();
    return asc ? -d : d;
  });
  return list.slice(0, Number(q.get("limit") ?? 100));
}

function nextSlotIso(): string {
  const slots = (settings.schedule?.daily_slots as string[]) ?? ["08:00"];
  const now = new Date();
  for (let d = 0; d < 2; d++) {
    for (const s of [...slots].sort()) {
      const [h, m] = s.split(":").map(Number);
      const t = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + d, h, m));
      if (t.getTime() > now.getTime()) return t.toISOString();
    }
  }
  return iso(Date.now() + DAY);
}

// ── router ───────────────────────────────────────────────────────────────────

type Body = Record<string, unknown> | undefined;

export function handleDemoRequest(method: string, path: string, query: URLSearchParams, body: unknown): unknown | undefined {
  const b = (body && typeof body === "object" ? body : undefined) as Body;
  const seg = path.replace(/\/+$/, "").split("/").filter(Boolean);
  const [root, a1, a2, a3] = seg;
  const GET = method === "GET";
  const POST = method === "POST";
  const PUT = method === "PUT";
  const DEL = method === "DELETE";

  switch (root) {
    // ── system ──
    case "health":
      return { status: "ok", scheduler: true, telegram: "webhook" };
    case "version":
      return {
        backend: { commit: "a1b2c3d", branch: "main", tag: "v2.0.4", build_time: iso(NOW - 3 * DAY) },
        runtime: { python: "3.12.4", fastapi: "0.115.0", uvicorn: "0.30.6", supabase: "2.7.4", openrouter: "1.0", groq: "0.11.0" },
      };

    // ── settings ──
    case "settings": {
      if (GET && !a1) return { settings: clone(settings), secrets_set: SECRETS_SET };
      if (GET && a1) return { group: a1, value: clone(settings[a1] ?? {}) };
      if (PUT && b) {
        const group = String(b.group);
        settings[group] = { ...(settings[group] ?? {}), ...((b.value as Record<string, unknown>) ?? {}) };
        return { group, value: clone(settings[group]) };
      }
      return undefined;
    }

    // ── taxonomy ──
    case "taxonomy":
      if (a1 === "categories") return { categories: CATEGORIES };
      if (a1 === "tags") {
        const cat = query.get("category");
        const tags = cat ? THEMES.filter((t) => t.category === cat).flatMap((t) => t.tags) : ALL_TAGS;
        return { tags };
      }
      return undefined;

    case "series":
      return [{ id: "ser_fit", title: "30-Day Fitness Reset", posted: 1, total: 4, next_episode: 2 }];

    // ── media ──
    case "media": {
      if (GET && !a1) return filterMedia(query);
      if (GET && a1 === "count") {
        const q = new URLSearchParams(query);
        q.set("status", "raw"); q.set("limit", "1000"); q.delete("offset");
        return { count: filterMedia(q).filter((m) => m.media_type === "VIDEO").length };
      }
      const m = a1 ? findMedia(a1) : undefined;
      if (!m) return undefined;
      if (GET) return clone(m);
      if (PUT && b) {
        const { metadata, ...rest } = b;
        Object.assign(m, rest);
        if (metadata && typeof metadata === "object") m.metadata = { ...(m.metadata ?? {}), ...(metadata as object) };
        return clone(m);
      }
      if (DEL) { m.status = "deleted"; return { ok: true, id: m.id }; }
      if (POST && a2 === "reprocess") {
        m.status = String(b?.target_status ?? "raw");
        return { ok: true, id: m.id, status: m.status };
      }
      if (POST && a2 === "enhance") {
        m.metadata = { ...(m.metadata ?? {}), ...(b ?? {}), enhanced: true };
        later(1500, () => emit("edit_complete", { media_id: m.id, post_id: posts.find((p) => p.media_id === m.id)?.id }));
        return { status: "started", media: clone(m) };
      }
      return undefined;
    }

    // ── posts ──
    case "posts": {
      if (GET && !a1) return filterPosts(query);
      if (POST && !a1) {
        const m = findMedia(String(b?.media_id ?? ""));
        if (!m) return undefined;
        const p = makePost(m, "preview", NOW + DAY);
        posts.unshift(p);
        return p;
      }
      if (POST && a1 === "select-preview") {
        const exclude = new Set((b?.exclude_ids as string[]) ?? []);
        const cat = b?.category as string | undefined;
        const pool = liveMedia().filter((m) => m.status === "raw" && !exclude.has(m.id) && (!cat || m.category === cat));
        const pick = pool[0] ?? liveMedia().find((m) => m.status === "raw");
        if (!pick) return { media_id: "", category: cat };
        return { media_id: pick.id, local_path: `uploads/${pick.category}/${pick.id}.mp4`, category: pick.category, tags: pick.tags, duration_s: 6 };
      }
      if (POST && a1 === "create") {
        const id = (b?.media_id as string) || liveMedia().find((m) => m.status === "raw" && (!b?.category || m.category === b.category))?.id;
        const m = id ? findMedia(id) : undefined;
        if (!m) return { status: "no_media", source: "api" };
        simulatePipeline(m.id, ["resize", "edit", "caption", "upload", "schedule"], () => promoteToPreview(m));
        return { media_id: m.id, status: "started", source: "api" };
      }
      if (POST && a1 === "create-merge") {
        const id = `mrg_${Math.random().toString(16).slice(2, 10)}`;
        const cat = (b?.category as string) || "travel";
        const n = THEMES.findIndex((t) => t.category === cat);
        const m: DemoMedia = {
          ...clone(findMedia(MERGE_ID)!), id, category: cat, status: "edited",
          thumbnail_url: asset(`media/clip${clipNo(Math.max(0, n))}.jpg`),
          r2_url: asset(`media/clip${clipNo(Math.max(0, n))}.mp4`),
          taken_at: iso(Date.now()), created_at: iso(Date.now()),
        };
        media.unshift(m);
        simulatePipeline(id, ["merge", "edit", "caption", "upload", "schedule"], () => promoteToPreview(m));
        return { status: "started", source: "api" };
      }
      if (POST && a1 === "auto-schedule") {
        let k = 0;
        for (const p of posts) if (p.status === "preview" || p.status === "scheduled") p.scheduled_at = iso(NOW + ++k * 4 * HOUR);
        return { scheduled: k };
      }
      if (PUT && a1 === "reorder") return { ok: true };
      const p = a1 ? findPost(a1) : undefined;
      if (!p) return undefined;
      if (GET && !a2) return clone(p);
      if (PUT && !a2 && b) { Object.assign(p, b); return clone(p); }
      if (DEL && !a2) { posts.splice(posts.indexOf(p), 1); return { ok: true }; }
      if (POST) {
        switch (a2) {
          case "approve":
          case "publish":
          case "approve-platforms":
            p.status = "posted"; p.approval_status = "approved"; p.approved_at = iso(Date.now());
            p.ig_media_id = p.ig_media_id ?? `1790${Date.now() % 100000}`;
            { const m = findMedia(p.media_id); if (m) m.status = "posted"; }
            later(300, () => emit("post_status", { post_id: p.id, status: "posted" }));
            return { ok: true, status: "approved" };
          case "reject":
            p.status = "rejected"; p.approval_status = "rejected";
            return { ok: true, status: "rejected" };
          case "cancel":
            p.status = "cancelled";
            return { ok: true, status: "cancelled" };
          case "reschedule": {
            const at = b?.scheduled_at ? new Date(String(b.scheduled_at)).getTime() : NOW + DAY;
            p.scheduled_at = iso(at); p.publish_after = iso(at + 60 * MIN); p.status = "preview";
            p.yt_error = undefined;
            return { ok: true, scheduled_at: p.scheduled_at };
          }
          case "edit":
            later(2000, () => emit("edit_complete", { post_id: p.id, media_id: p.media_id }));
            return { status: "dispatched", stages: ["edit"] };
          case "retry-youtube":
            p.yt_error = undefined; p.yt_video_id = `dQwRetry${Date.now() % 1000}`;
            return { ok: true };
        }
      }
      return undefined;
    }

    // ── captions ──
    case "captions": {
      if (POST && a1 === "generate") {
        const m = findMedia(String(b?.media_id ?? ""));
        const t = THEMES.find((x) => x.category === (m?.category ?? b?.category)) ?? THEMES[0];
        const caption = `${t.hook} 🔥\n\nTry it this week and tell me how it went.\n\n${t.ar}`;
        if (m) m.caption = caption;
        return {
          caption, caption_ar: t.ar, hashtags_en: t.hashtags, hashtags_ar: ["محتوى", "ريلز", "إلهام"],
          alt_text: `Vertical video: ${t.title.toLowerCase()}`,
        };
      }
      if (GET && a1) {
        const m = findMedia(a1);
        return m?.caption ? [{ id: `cap_${a1}`, media_id: a1, caption: m.caption, created_at: m.created_at }] : [];
      }
      return undefined;
    }

    // ── analytics / statistics / classification ──
    case "analytics": {
      const lm = liveMedia();
      if (a1 === "overview") return { total_media: lm.length, by_status: countBy(lm, (m) => m.status), by_category: countBy(lm, (m) => m.category), recent_analytics: [] };
      if (a1 === "categories") {
        const c = countBy(lm, (m) => m.category);
        return Object.fromEntries(Object.entries(c).map(([k, v]) => [k, { count: v }]));
      }
      if (a1 === "timeseries") return timeseries.slice(-Number(query.get("days") ?? 30));
      if (a1 === "pillars" || a1 === "hashtags") return {};
      return undefined;
    }
    case "statistics": {
      const lm = liveMedia();
      if (a1 === "overview") {
        const by = countBy(lm, (m) => m.status);
        return {
          total_media: lm.length, by_status: by, by_category: countBy(lm, (m) => m.category),
          funnel: ["raw", "resized", "edited", "uploaded", "posted"].map((stage) => ({ stage, count: by[stage] ?? 0 })),
        };
      }
      if (a1 === "categories") {
        return CATEGORIES.map((category) => {
          const rows = lm.filter((m) => m.category === category);
          return { category, total: rows.length, posted: rows.filter((m) => m.status === "posted").length, error: rows.filter((m) => m.status === "error").length, raw: rows.filter((m) => m.status === "raw").length };
        }).sort((x, y) => y.total - x.total);
      }
      if (a1 === "posts") {
        const posted = posts.filter((p) => p.status === "posted");
        return {
          total: posts.length, by_status: countBy(posts, (p) => p.status),
          platforms: { instagram: posted.filter((p) => p.ig_media_id).length, youtube: posted.filter((p) => p.yt_video_id).length, tiktok: posted.filter((p) => p.tiktok_video_id).length },
        };
      }
      return undefined;
    }
    case "classification": {
      const lm = liveMedia();
      const classified = (m: DemoMedia, i: number) => m.status !== "raw" || i % 2 === 0;
      const scored = (m: DemoMedia, i: number) => m.status !== "raw" && i % 5 !== 0;
      if (a1 === "overview") {
        const g = lm.filter(classified).length;
        const v = lm.filter(scored).length;
        return {
          total_media: lm.length, video_media: lm.filter((m) => m.media_type === "VIDEO").length,
          groq: { classified: g, remaining: lm.length - g, pct: Math.round((g / lm.length) * 100) },
          vision: { scored: v, remaining: lm.length - v, pct: Math.round((v / lm.length) * 100) },
          by_category: countBy(lm, (m) => m.category), by_status: countBy(lm, (m) => m.status),
        };
      }
      if (a1 === "breakdown") {
        return CATEGORIES.map((category) => {
          const rows = lm.map((m, i) => [m, i] as const).filter(([m]) => m.category === category);
          return { category, total: rows.length, groq_classified: rows.filter(([m, i]) => classified(m, i)).length, vision_scored: rows.filter(([m, i]) => scored(m, i)).length };
        });
      }
      return undefined;
    }

    // ── notifications ──
    case "notifications": {
      if (GET && !a1) {
        const unread = query.get("unread") === "true";
        return notifications.filter((n) => !unread || !n.read).slice(0, Number(query.get("limit") ?? 50));
      }
      if (a1 === "token-status") return { status: "ok", days_left: 47, expires_at: iso(NOW + 47 * DAY), message: "Token valid for 47 days" };
      if (PUT && a1 === "read-all") { notifications.forEach((n) => (n.read = true)); return { ok: true }; }
      if (PUT && a2 === "read") { const n = notifications.find((x) => x.id === a1); if (n) n.read = true; return { ok: true }; }
      return undefined;
    }

    // ── pipeline ──
    case "pipeline": {
      if (GET && a1 === "runs") return runs.slice(0, Number(query.get("limit") ?? 20));
      if (POST && a1 === "orchestrate") {
        later(400, () => { logRun("index", 3); logRun("classify", 3); logRun("resize", 2); });
        return { status: "ok", processed: 8, failed: 0 };
      }
      if (POST && a1 === "full") { later(400, () => STAGES.forEach((s) => logRun(s, 2))); return { status: "started" }; }
      if (POST && a1) { logRun(a1, 1 + Math.round(rand() * 4)); return { status: "ok", stage: a1, processed: 2, failed: 0 }; }
      return undefined;
    }

    // ── scheduler ──
    case "scheduler": {
      if (GET && a1 === "status") {
        const p = settings.pipeline ?? {};
        const s = settings.schedule ?? {};
        return {
          running: true,
          auto_publish_enabled: Boolean(p.auto_publish_enabled ?? true),
          auto_create_enabled: Boolean(p.auto_create_enabled ?? true),
          auto_create_mode: String(p.auto_create_mode ?? "approval"),
          auto_create_strategy: String(p.auto_create_strategy ?? "diverse"),
          auto_create_category: String(p.auto_create_category ?? ""),
          daily_slots: (s.daily_slots as string[]) ?? [],
          timezone: String(s.timezone ?? "UTC"),
          max_per_day: Number(s.max_per_day ?? 3),
          next_slot: nextSlotIso(),
          current_slot: null,
        };
      }
      if (POST && a1 === "run-now") {
        const m = liveMedia().find((x) => x.status === "raw");
        if (!m) return { ok: false, reason: "No raw clips left" };
        simulatePipeline(m.id, ["resize", "edit", "caption", "upload", "schedule"], () => promoteToPreview(m));
        return { ok: true, media_id: m.id };
      }
      return undefined;
    }

    // ── downloads ──
    case "downloads": {
      if (GET && a1 === "status") {
        return {
          posts: { downloaded: 184, files: { video: 142, image: 61, other: 3, total_size_mb: 2310.4 } },
          highlights: {
            downloaded: 37,
            files: { video: 58, image: 12, other: 0, total_size_mb: 640.2 },
            breakdown: [
              { name: "Food", count: 14, last_downloaded: iso(NOW - 2 * DAY) },
              { name: "Workouts", count: 11, last_downloaded: iso(NOW - 3 * DAY) },
              { name: "Weekends", count: 9, last_downloaded: iso(NOW - 6 * DAY) },
              { name: "Studio", count: 3, last_downloaded: null },
            ],
          },
          organized: CATEGORIES.map((c, i) => ({ category: c, video: 12 + ((i * 7) % 19), image: 3 + ((i * 5) % 9), total_size_mb: Math.round((180 + i * 41.3) * 10) / 10 })),
          uploads: { video: 9, image: 2, total_size_mb: 212.7 },
        };
      }
      if (GET && a1 === "categories") {
        return CATEGORIES.map((category, i) => {
          const raw = 4 + (i % 4), resized = 2 + (i % 3), edited = 1 + (i % 2), uploaded = i % 3, posted = 3 + (i % 5), error = i === 4 ? 1 : 0;
          return { category, raw, resized, edited, uploaded, posted, error, total: raw + resized + edited + uploaded + posted + error };
        });
      }
      if (GET && a1 === "check-new") return { new_posts: 3, total_on_ig: 187 };
      if (a1 === "google") return { configured: true };
      if (a1 === "google-drive" && a2 === "list") {
        return {
          files: THEMES.slice(0, 6).map((t, i) => ({ id: `drv_${i}`, name: `${t.title}.mp4`, size: 24_000_000 + i * 3_100_000, mimeType: "video/mp4", thumbnailLink: asset(`media/clip${clipNo(i)}.jpg`), duration_ms: 6000 })),
          next_page_token: "",
        };
      }
      if (a1 === "google-photos" && a2 === "session") {
        if (POST) return { id: "gps_demo", picker_uri: "https://photos.google.com/", poll_interval_ms: 2000 };
        return { id: a3 ?? "gps_demo", media_items_set: true };
      }
      if (a1 === "stock") {
        if (a2 === "status") return { configured: true };
        if (a2 === "library") {
          const groups = Array.from(new Set(stockClips.map((c) => c.category))).map((category) => {
            const clips = stockClips.filter((c) => c.category === category);
            return { category, count: clips.length, total_size_mb: Math.round(clips.reduce((s, c) => s + c.size_mb, 0) * 10) / 10, clips: clips.map(({ key: _k, ...c }) => c) };
          });
          return {
            categories: groups, total_clips: stockClips.length,
            total_size_mb: Math.round(stockClips.reduce((s, c) => s + c.size_mb, 0) * 10) / 10,
            imported_keys: stockClips.map((c) => c.key),
          };
        }
        if (a2 === "search") {
          const provider = query.get("provider");
          return {
            results: Array.from({ length: 8 }, (_, i) => ({
              id: String(51000 + i), provider: (provider === "pixabay" || (!provider && i % 2)) ? "pixabay" : "pexels",
              thumbnail_url: asset(`media/clip${clipNo(i)}.jpg`), preview_url: asset(`media/clip${clipNo(i)}.mp4`),
              duration_s: 8 + i, width: 720, height: 1280,
            })),
          };
        }
        if (POST && a2 === "import") {
          const id = `stk_${Math.random().toString(16).slice(2, 8)}`;
          stockClips.push({
            id, key: `${b?.provider}:${b?.id}`, provider: String(b?.provider ?? "pexels"), provider_id: String(b?.id ?? ""),
            category: String(b?.category ?? "travel"), tags: (b?.tags as string[]) ?? [], status: "raw",
            width: 720, height: 1280, duration_s: 10, size_mb: 7.4, created_at: iso(Date.now()),
          });
          return { results: [{ filename: `${b?.provider}_${b?.id}.mp4`, ok: true, id }], saved: 1 };
        }
        if (DEL && a2) { stockClips = stockClips.filter((c) => c.id !== a2); return { ok: true, id: a2 }; }
      }
      if (POST && (a1 === "upload-url" || a1 === "upload")) {
        return a1 === "upload-url"
          ? { filename: "remote_clip.mp4", ok: true, id: `up_${Date.now().toString(16)}`, local_path: "uploads/travel/remote_clip.mp4" }
          : { results: [{ filename: "clip.mp4", ok: true, id: `up_${Date.now().toString(16)}` }], saved: 1 };
      }
      if (POST && (a1 === "google-drive" || a1 === "google-photos") && a2 === "import") {
        return { results: [{ filename: "drive_clip.mp4", ok: true, id: `up_${Date.now().toString(16)}` }], saved: 1 };
      }
      if (POST) return { status: "started", message: "Download started (demo)" };
      return undefined;
    }

    // ── assets ──
    case "assets": {
      if (a1 === "all") {
        if (GET && !a2) {
          const type = query.get("type");
          let list = assets.filter((x) => !type || x.type === type);
          if (query.get("favourite") === "true") list = list.filter((x) => x.favourite);
          if (type === "music") {
            list = tracks.map((t, i) => assetRow("music", i, t.title, t.filename, t.url, { id: `ast_music_${t.id}`, mood: t.mood, tags: t.categories, favourite: t.favourite }));
          }
          return { assets: clone(list) };
        }
        const it = assets.find((x) => x.id === a2);
        if (!it) return undefined;
        if (GET) return { asset: clone(it) };
        if (PUT && b) { Object.assign(it, b); return { asset: clone(it) }; }
        if (DEL) { assets.splice(assets.indexOf(it), 1); return { ok: true, id: a2 }; }
        return undefined;
      }
      if (POST && a1 === "sync") {
        const confirm = query.get("confirm") === "true";
        return { added: confirm ? [] : [{ filename: "new_asset" }], removed: [], updated: [], added_count: confirm ? 0 : 1, removed_count: 0, updated_count: 0 };
      }
      if (a1 === "music") {
        if (GET && !a2) return { music: tracks.map((t) => ({ id: t.id, title: t.title, duration: t.duration, source: "local", category: t.categories[0], shared: t.categories.length > 1, url: t.url })) };
        return { ok: true, music: [] };
      }
      if (a1 === "stickers") {
        if (GET && !a2) return { stickers };
        return { item: stickers[0] };
      }
      if (GET && a1 === "luts") return { luts: assets.filter((x) => x.type === "lut").map((x) => ({ name: x.name, file: x.local_path?.replace(/^luts\//, "") })) };
      if (GET && a1 === "fonts") return { fonts: assets.filter((x) => x.type === "font").map((x) => x.filename) };
      if (GET && (a1 === "intros" || a1 === "outros")) return { items: assets.filter((x) => x.type === a1.slice(0, -1)) };
      if (POST) return { ok: true };
      return undefined;
    }

    // ── audio ──
    case "audio": {
      if (GET && !a1) return { tracks: clone(tracks) };
      if (POST && a1 === "refresh") {
        return query.get("confirm") === "true"
          ? { new_files: [], dup_groups: [], would_delete_count: 0, orphaned: [], orphaned_count: 0 }
          : { new_files: ["sunset_drive.mp3"], dup_groups: [{ keep: "lofi_morning", delete: ["lofi_morning_1"], categories_merged: ["lifestyle", "tech"] }], would_delete_count: 1, orphaned: [], orphaned_count: 0 };
      }
      const t = tracks.find((x) => x.id === a1);
      if (!t) return POST ? { ok: true } : undefined;
      if (PUT && b) { Object.assign(t, b); return clone(t); }
      if (DEL) { tracks = tracks.filter((x) => x.id !== a1); return { ok: true, id: a1 }; }
      if (POST && a2 === "trim") {
        const nt: Track = { ...clone(t), id: `${t.id}_trim`, filename: `${t.id}_trim.mp3`, title: `${t.title} (trim)`, duration: Math.round(Number(b?.end_s ?? 30) - Number(b?.start_s ?? 0)), usage_count: 0 };
        tracks.push(nt);
        return nt;
      }
      return undefined;
    }

    // ── editor ──
    case "editor": {
      if (a1 === "proxy") return undefined; // signed streams are plain URLs in demo
      const mediaId = a1;
      if (!mediaId) return undefined;
      if (GET && !a2) return editorDoc(mediaId, query.get("fresh") === "1");
      if (PUT && !a2) {
        const list = (editorVersions[mediaId] ??= []);
        const version = (list[0]?.version ?? 0) + 1;
        list.unshift({ id: `ver_${version}`, version, label: (b?.label as string) ?? null, approx: false, created_at: iso(Date.now()), edl: clone(b?.edl as EDL) });
        return { media_id: mediaId, project_id: `prj_${mediaId}`, version, approx: false };
      }
      if (GET && a2 === "versions" && !a3) {
        return { media_id: mediaId, versions: (editorVersions[mediaId] ?? []).map(({ edl: _e, ...v }) => v) };
      }
      if (GET && a2 === "versions" && a3) {
        const v = (editorVersions[mediaId] ?? []).find((x) => String(x.version) === a3);
        return v ? { media_id: mediaId, ...clone(v) } : undefined;
      }
      if (POST && a2 === "proxies") {
        const edl = (b?.edl as EDL | undefined) ?? editorDoc(mediaId, false).edl;
        const cuts = edl.cuts ?? [];
        if (!cuts.length) return { media_id: mediaId, status: "no_cuts" };
        const proxies: Record<string, string> = {};
        cuts.forEach((c, i) => {
          const src = findMedia(c.src_media_id);
          const rel = src?.r2_url.split("/demo/")[1] ?? `media/clip${clipNo(i)}.mp4`;
          proxies[c.id] = absAsset(rel);
        });
        later(350, () => emit("editor_proxy_progress", { media_id: mediaId, done: Math.ceil(cuts.length / 2), total: cuts.length }));
        later(800, () => emit("editor_proxy_complete", { media_id: mediaId, proxies }));
        return { media_id: mediaId, status: "started", cuts: cuts.length };
      }
      if (POST && a2 === "export") {
        ["Rendering cuts…", "Compositing layers…", "Uploading…"].forEach((message, i) =>
          later(600 + i * 900, () => emit("editor_export_progress", { media_id: mediaId, message })));
        later(3400, () => emit("editor_export_complete", { media_id: mediaId }));
        return { media_id: mediaId, status: "started", merge_id: `mrg_${Date.now().toString(16).slice(-8)}` };
      }
      return undefined;
    }

    case "edit":
      return { status: "dispatched" };
  }
  return undefined;
}
