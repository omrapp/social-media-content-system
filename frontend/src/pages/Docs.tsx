import { useState } from "react";
import {
  BookOpen, Download, Layers, Film, CalendarDays, BarChart3,
  Settings, MessageCircle, ChevronDown, ChevronUp, ExternalLink,
  Info, AlertCircle, CheckCircle2, Terminal, Globe, Wand2,
  Sparkles, ScanSearch, Monitor, Eraser, Video, Mic, FolderOpen, Scissors,
} from "lucide-react";

// ── types ─────────────────────────────────────────────────────────────────────

interface Section {
  id: string;
  label: string;
  icon: React.ElementType;
  accent: string;
  content: React.ReactNode;
}

// ── helpers ───────────────────────────────────────────────────────────────────

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="text-xs font-mono bg-gray-800 text-amber-300 px-1.5 py-0.5 rounded">
      {children}
    </code>
  );
}

function Pre({ children }: { children: string }) {
  return (
    <pre className="bg-gray-950 border border-gray-800 rounded-xl p-4 text-xs font-mono text-gray-300 overflow-x-auto whitespace-pre leading-5 mt-2">
      {children}
    </pre>
  );
}

function Note({ type = "info", children }: { type?: "info" | "warn" | "tip"; children: React.ReactNode }) {
  const styles = {
    info: { bg: "bg-blue-950/30 border-blue-800/50", icon: Info, text: "text-blue-300", iconCls: "text-blue-400" },
    warn: { bg: "bg-amber-950/30 border-amber-800/50", icon: AlertCircle, text: "text-amber-300", iconCls: "text-amber-400" },
    tip:  { bg: "bg-green-950/30 border-green-800/50", icon: CheckCircle2, text: "text-green-300", iconCls: "text-green-400" },
  };
  const s = styles[type];
  const Icon = s.icon;
  return (
    <div className={`flex gap-3 p-3 rounded-xl border text-xs ${s.bg} mt-3`}>
      <Icon size={14} className={`${s.iconCls} shrink-0 mt-0.5`} />
      <p className={s.text}>{children}</p>
    </div>
  );
}

function H3({ children }: { children: React.ReactNode }) {
  return <h3 className="text-sm font-semibold text-white mt-5 mb-2 first:mt-0">{children}</h3>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-gray-400 leading-relaxed">{children}</p>;
}

function Ul({ children }: { children: React.ReactNode }) {
  return <ul className="text-sm text-gray-400 space-y-1 list-none mt-1">{children}</ul>;
}

function Li({ children }: { children: React.ReactNode }) {
  return <li className="flex gap-2"><span className="text-gray-600 shrink-0">·</span><span>{children}</span></li>;
}

function Rec({ value }: { value: string }) {
  return (
    <p className="text-xs text-emerald-400/80 font-medium mt-0.5">
      ✦ Recommended: <span className="font-mono text-emerald-300">{value}</span>
    </p>
  );
}

function Table({ headers, rows }: { headers: string[]; rows: (string | React.ReactNode)[][] }) {
  return (
    <div className="overflow-x-auto mt-3 rounded-xl border border-gray-800">
      <table className="w-full text-xs text-left">
        <thead>
          <tr className="border-b border-gray-800 bg-gray-900/60">
            {headers.map((h) => (
              <th key={h} className="px-3 py-2 text-gray-400 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-gray-800/40 hover:bg-gray-800/20">
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-2 text-gray-300 align-top">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── section content ───────────────────────────────────────────────────────────

const overviewContent = (
  <div className="space-y-3">
    <P>Travel CMS is a full pipeline system: download Instagram posts → index → classify → resize → generate captions → queue for publish.</P>

    <H3>Pipeline stages (in order)</H3>
    <Table
      headers={["Stage", "What it does"]}
      rows={[
        [<Code>download_posts</Code>, "Fetches new IG posts from the archive API into organized/"],
        [<Code>download_highlights</Code>, "Fetches Highlights albums into organized/"],
        [<Code>index</Code>, "Scans organized/ and upserts every video into the media table. Idempotent."],
        [<Code>classify</Code>, "Calls Groq Llama 3.3 70B to tag each media with category / tags. Only runs on new downloads."],
        [<Code>resize</Code>, "FFmpeg crops video to 9:16 (vertical Reels format, 1080×1920)."],
        [<Code>enhance</Code>, "FFmpeg post-processing: sharpening, contrast/saturation boost, fade in/out, optional libvidstab stabilization, optional watermark blur, audio loudnorm (EBU R128). Runs automatically after resize."],
        [<Code>caption</Code>, "OpenRouter (openai/gpt-oss-20b:free) generates EN + AR captions, hashtags, alt text."],
        [<Code>upload</Code>, "Pushes the finished video to Cloudflare R2 (needed for publishing)."],
        [<Code>edit</Code>, "AI-driven edit dispatch — swap music, apply LUT, trim."],
      ]}
    />

    <H3>Media status machine</H3>
    <Pre>{`raw → resized → enhanced → edited → uploaded → scheduled → preview → posted
                                                              ↘ error (any stage)`}</Pre>
    <P>Every media row starts as <Code>raw</Code> after indexing. Each pipeline stage advances the status forward.</P>

    <H3>Post approval flow</H3>
    <Ul>
      <Li>Post created with <Code>status=preview</Code>, <Code>publish_after = now + approval window</Code> (default 60 min)</Li>
      <Li>Daemon checks every 60 s — if <Code>publish_after ≤ now</Code> and <Code>status=preview</Code>, auto-publishes (the 1-hour safety net)</Li>
      <Li><strong className="text-white">Approve</strong> publishes <strong className="text-white">immediately</strong> to all enabled platforms — flips <Code>status=publishing</Code>, posts in background, then <Code>status=posted</Code>. The approve button disables once clicked.</Li>
      <Li><strong className="text-white">Reject</strong> sets <Code>status=cancelled</Code> — nothing publishes</Li>
    </Ul>
  </div>
);

const downloadsContent = (
  <div className="space-y-3">
    <P>Downloads fetches your raw Instagram content into <Code>organized/</Code> on the server disk.</P>

    <H3>Posts vs Highlights</H3>
    <Ul>
      <Li><strong className="text-white">Posts</strong> — fetches new posts from your IG archive since last run. Stores each video under <Code>organized/&lt;category&gt;/</Code></Li>
      <Li><strong className="text-white">Highlights</strong> — fetches all Highlight albums. Each album becomes a sub-folder.</Li>
    </Ul>

    <H3>After downloading</H3>
    <P>Run <strong className="text-white">Pipeline → Index</strong> to register new downloads into the database. Without indexing, the rest of the pipeline won't see them.</P>

    <Note type="warn">Downloads require a valid IG access token. Token expires every 60 days — check the Notifications bell for a token-expiry warning.</Note>

    <H3>Organized breakdown (table)</H3>
    <P>The Downloads page shows a category breakdown of everything in <Code>organized/</Code>, including file counts and total size. This is a disk-level view — not the database.</P>
  </div>
);

const pipelineContent = (
  <div className="space-y-3">
    <P>The Pipeline page lets you trigger individual stages or the full orchestrated pipeline.</P>

    <H3>Trigger a single stage</H3>
    <Pre>{`POST /api/pipeline/{stage}
stages: index | classify | resize | enhance | edit | upload | caption`}</Pre>
    <Note type="tip">Always run <Code>index</Code> first after a download. Otherwise classify/resize won't see new files.</Note>

    <H3>Full orchestration</H3>
    <P>The <strong className="text-white">Orchestrate</strong> button chains: index → classify → resize → enhance → edit → caption → upload. Runs in background, streams events over WebSocket to the Pipeline page in real-time.</P>

    <H3>Pipeline run log</H3>
    <P>Each stage execution creates a row in <Code>pipeline_runs</Code> with: stage name, status, items processed, items failed, started_at, completed_at.</P>

    <H3>CLI equivalent</H3>
    <Pre>{`# Single stage
python -m backend.pipeline.index_content
python -m backend.pipeline.classify_groq
python -m backend.pipeline.resize_clips
python -m backend.pipeline.enhance_video
python -m backend.pipeline.enhance_video --media-id abc123

# Full orchestration
python -m backend.pipeline.orchestrator --stages index,classify,resize,enhance,caption`}</Pre>
  </div>
);

const createContent = (
  <div className="space-y-3">
    <P>Create Video picks one raw clip, runs resize + caption, and enqueues it as a preview post ready for approval.</P>

    <H3>Strategies</H3>
    <Table
      headers={["Strategy", "How it picks", "Requires"]}
      rows={[
        ["Best clip", "Highest hook_score raw clip for the selected category/tags", "category + tags selected"],
        ["Random", "Random unposted clip matching the selected filters", "category + tags selected"],
      ]}
    />

    <H3>Customize step (music + LUT + clip preview) (1.6.0)</H3>
    <P>After picking filters, both <strong className="text-white">Single</strong> and <strong className="text-white">Merge</strong> flows show a Customize step:</P>
    <Ul>
      <Li><strong className="text-white">Single:</strong> the backend dry-run selects a clip via <Code>POST /api/posts/select-preview</Code> (no processing) and shows its <Code>media_id</Code> + source path so you can review it. <Code>Pick new video</Code> re-selects a different clip (excluding ones already skipped).</Li>
      <Li><strong className="text-white">Merge:</strong> music/LUT only — the montage still auto-selects its clips.</Li>
      <Li>Pick a <strong className="text-white">music</strong> track and/or a <strong className="text-white">LUT</strong> colour grade — both optional, each with a live <strong className="text-white">search box</strong> to filter the list.</Li>
      <Li><strong className="text-white">Keep original when blank:</strong> no track picked → the clip's own audio is kept (no auto-added bed); no LUT picked → no colour grade (original video look). For merge, blank music uses the clips' own audio (<Code>audio_mode=original</Code>).</Li>
      <Li><strong className="text-white">Decaption toggle:</strong> per-reel override to strip burned-in captions/watermarks. Seeds from the global <Code>decaption.enabled</Code> setting and can force on/off for this reel only.</Li>
      <Li>Buttons: <Code>Continue</Code> → Confirm · <Code>Pick new video</Code> (single) · <Code>Back</Code> → filters · <Code>Cancel</Code> → restart the flow.</Li>
    </Ul>
    <P>Music resolves to a track under the music library; the LUT is a <Code>LUTS_DIR</Code>-relative <Code>.cube</Code>. Both are applied at the edit stage (for merge, music is muxed at the merge stage; the LUT rides the edit tail).</P>
    <Note type="info">These keep-original defaults + decaption override apply only to the <strong>manual</strong> Create wizard. The automatic timer/daemon flow is unchanged — it still auto-picks music, auto-grades, and respects the global decaption setting.</Note>

    <H3>What happens after you click Create</H3>
    <Ul>
      <Li>Backend processes the clip you locked in (or picks one matching your filters when none was previewed)</Li>
      <Li>resize stage runs (FFmpeg → 9:16 crop)</Li>
      <Li>caption stage runs (OpenRouter → EN + AR captions)</Li>
      <Li>edit stage applies your picked music / LUT (or auto-defaults)</Li>
      <Li>Post created with <Code>status=preview</Code> in the Queue</Li>
      <Li>WebSocket event fires — Create page shows "Done" with links to Preview and Queue</Li>
    </Ul>

    <H3>Quality gate (0.6.0)</H3>
    <P>Every strategy now skips clips that fail the <Code>selection</Code> rules — too short (<Code>min_duration_s</Code>), too low-res (<Code>min_short_side</Code>), or below <Code>min_quality_score</Code> once the blur/shake probe has scored them. Skips are logged with a reason. The probe runs as the first create stage; at the default <Code>min_quality_score=0</Code> it only measures (stores scores), so calibrate a threshold from real scores before enforcing.</P>

    <Note type="info">
      "No indexed media found" in the category dropdown means the media table is empty. Run <strong>Downloads → Posts</strong> then <strong>Pipeline → Index</strong>.
    </Note>
  </div>
);

const queueContent = (
  <div className="space-y-3">
    <P>Queue shows all posts with <Code>status=preview</Code> or <Code>status=scheduled</Code>, ordered by <Code>scheduled_at</Code>.</P>

    <H3>Actions</H3>
    <Table
      headers={["Action", "What it does"]}
      rows={[
        ["Approve", "Publishes immediately to all enabled platforms (bypasses the approval window). Button disables once clicked."],
        ["Reject", "Sets status=cancelled — post is archived, never publishes"],
        ["Reschedule", "Pick a new scheduled_at + approval window — sets publish_after accordingly"],
        ["Preview", "Opens the fullscreen Preview page for that post"],
      ]}
    />

    <H3>Countdown timer</H3>
    <P>Each post shows a live countdown to its <Code>publish_after</Code> timestamp. Timer pulses red when under 5 minutes. When it expires, the daemon auto-publishes (the 1-hour safety net) — clicking Approve before then publishes immediately instead.</P>

    <H3>Auto-post setting</H3>
    <P>The <Code>approval.auto_post_after_minutes</Code> setting (default 60) controls how long a post sits in preview before the daemon auto-publishes it if not manually approved/rejected. Manually created videos use this same 1-hour window.</P>
    <Note type="tip">Set <Code>auto_post_after_minutes</Code> to a large number (e.g. 9999) to effectively require manual approval for all posts.</Note>
  </div>
);

const settingsContent = (
  <div className="space-y-3">
    <P>All runtime configuration lives in the Settings page. Changes are saved per-group to Supabase.</P>

    <H3>Settings groups</H3>
    <Table
      headers={["Group", "Key settings"]}
      rows={[
        ["platforms", <><Code>instagram_enabled</Code>, <Code>youtube_enabled</Code>, <Code>tiktok_enabled</Code> — toggle each platform independently. All default to disabled except Instagram.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: instagram_enabled=true, others=false until OAuth configured</span></>],
        ["approval", <><Code>auto_post_after_minutes</Code> — how long preview sits before auto-publishing. <Code>require_manual_for_categories</Code> — list of categories that always need manual approval.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: auto_post_after_minutes=60</span></>],
        ["schedule", <><Code>daily_slots</Code> — list of HH:MM times (e.g. <Code>09:00,13:00,19:00</Code>). <Code>timezone</Code> (e.g. <Code>Asia/Beirut</Code>). <Code>max_per_day</Code> — cap posts per day.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: max_per_day=3, optimize_times=true</span></>],
        ["ai", <><Code>classifier_model</Code> defaults to <Code>groq/llama-3.3-70b</Code>. <Code>caption_model</Code> and <Code>refine_model</Code> default to <Code>openai/gpt-oss-20b:free</Code> (OpenRouter).<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: keep defaults</span></>],
        ["telegram", <><Code>mode</Code>: <Code>poll</Code> (dev) or <Code>webhook</Code> (prod). <Code>chat_id</Code>: your Telegram chat ID. <Code>preview_push_enabled</Code>: push preview before auto-publish.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: mode=webhook (prod), preview_push_enabled=true</span></>],
        ["music", <><Code>preferred_source</Code>: <Code>licensed</Code> or <Code>pixabay</Code>. <Code>pixabay_query</Code>: search term. <Code>swap_on_detect_original</Code>: replace original audio automatically.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: preferred_source=licensed, mood_match=true</span></>],
        ["taxonomy", <><Code>categories</Code>: comma-separated list of content categories used by the classifier. Default: <Code>hidden_gem,budget,culture,nature,food,beach</Code><br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: keep default taxonomy</span></>],
        ["selection", <><Code>min_duration_s</Code> (10), <Code>min_short_side</Code> (720px), <Code>min_hook_score</Code> (0=off) — quality gate that skips weak clips at selection. <Code>quality_probe_enabled</Code> + <Code>min_quality_score</Code> (0=measure-only) — FFmpeg blur/shake probe run as the first create stage. <Code>use_performance</Code>/<Code>performance_weight</Code> blend proven-category engagement into the pick.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: min_duration_s=10, min_short_side=720, performance_weight=0.5, category_cooldown_categories=20</span></>],
        ["caption", <><Code>use_feedback</Code>: inject top-performing past hooks (Enh A). <Code>use_trends</Code>: inject weekly Google-Trends topics (Enh B). <Code>self_critique</Code>: extra Haiku hook-rewrite pass (Enh J). <Code>draft_with_groq</Code>: draft on free Groq tier (Enh L). <Code>use_hook_library</Code>: inject curated viral hook templates into the prompt. <Code>trends_geo</Code>: geo-target Trends to the clip's location. <Code>hook_templates</Code>: custom hook strings; empty = built-in library.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: use_feedback=true, use_trends=true, self_critique=true, use_hook_library=true, trends_geo=true</span></>],
        ["hashtags", <><Code>ab_test</Code>: coin-flip between hashtag variants per post (Enh D). <Code>blocked</Code>: over-saturated tags to strip; empty = built-in denylist (Enh L). <Code>curated_enabled</Code>: blend curated viral pool tags with LLM-generated tags. <Code>blend_count</Code>: number of curated tags injected per post (default 8). <Code>pools</Code>: per-platform curated pools for Instagram, TikTok, and YouTube; empty lists = built-in pools.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: ab_test=true, curated_enabled=true, blend_count=8</span></>],
        ["monetize", <><Code>enabled</Code>: append a CTA line to captions on selected platforms. <Code>cta_text</Code>: the call-to-action string appended to caption body (e.g. "Full guide &amp; links in bio 🔗"). <Code>youtube_link</Code>: additional link line appended to YouTube description only. <Code>platforms</Code>: list of platforms that receive the CTA injection.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: set cta_text before enabling</span></>],
        ["video", <><Code>auto_stabilize</Code>: run libvidstab 2-pass stabilization (slow, ~1–3 min/clip). <Code>remove_watermarks</Code>: blur the IG watermark strip — <strong className="text-white">off by default</strong>. <Code>watermark_position</Code>: <Code>bottom</Code> | <Code>top</Code> | <Code>both</Code>.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: enhance_quality=true, denoise=true, sharpen_amount=0.4, crf=20, preset=medium</span></>],
        ["intro", <>Master toggle <Code>enabled</Code>. <Code>mode</Code>: <Code>generated</Code> | <Code>asset</Code>. <Code>duration_s</Code> (1.5 s), <Code>animation</Code> (fade/zoom/none), <Code>bg_color</Code>, <Code>bg_opacity</Code> (0.20 default — overlay over grabbed video frame). Per-element keys: <Code>header_*</Code>, <Code>subheader_*</Code>, <Code>tags_*</Code>, <Code>category_*</Code>, <Code>handle_*</Code> — each with <Code>_enabled</Code>, <Code>_color</Code>, <Code>_font_size</Code>, <Code>_order</Code>, <Code>_bottom_padding</Code>. See Design page docs.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: mode=generated, duration_s=1.5, animation=fade, bg_opacity=0.20</span></>],
        ["cast", <>Same structure as intro. <Code>cta_text</Code> defaults to "Follow for more". Per-element keys start with <Code>cta_*</Code> instead of <Code>header_*</Code>. Frame grabbed at <Code>ss=2.0 s</Code>.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: mode=generated, duration_s=1.5, animation=fade, bg_opacity=0.20</span></>],
        ["analytics", <><Code>ingest_interval_hours</Code>: how often IG analytics data is pulled.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: ingest_interval_hours=6</span></>],
        ["pipeline", <><Code>auto_publish_enabled</Code>: master kill-switch for the publish daemon. <Code>auto_create_reel_type</Code>: <Code>merge</Code> (multi-clip cinematic montage — randomly picks a category, weighted by footage, when <Code>auto_create_category</Code> is empty, same cooldown as the diverse strategy so it won't repeat a just-used category; auto-enables <Code>merge.enabled</Code>) or <Code>single</Code> (one clip via <Code>auto_create_strategy</Code>). Per-stage toggles: <Code>index_enabled</Code>, <Code>classify_enabled</Code>, <Code>resize_enabled</Code>, <Code>enhance_enabled</Code>, <Code>caption_enabled</Code>, <Code>upload_enabled</Code>.<br/><span className="text-emerald-400/80 text-xs font-medium">✦ Recommended: auto_create_reel_type=merge, auto_create_strategy=diverse, auto_create_mode=approval</span></>],
      ]}
    />

    <H3>Deployment info</H3>
    <P>The Settings page shows a Deployment card with the backend git commit, branch, tag, and build time. Useful for confirming which version is running on the server after a deploy.</P>

    <H3>Secrets</H3>
    <P>API keys and tokens live in <Code>.env</Code> only — never in the settings table. The Settings page shows a green/red indicator for each secret to confirm it's loaded.</P>
    <Table
      headers={["Secret", "Used for"]}
      rows={[
        ["OPENROUTER_API_KEY", "OpenRouter (openai/gpt-oss-20b:free) — caption generation + AI edit dispatch"],
        ["GROQ_API_KEY", "Llama 3.3 classification"],
        ["TELEGRAM_BOT_TOKEN", "Telegram bot commands + preview push"],
        ["YOUTUBE_CLIENT_SECRET + REFRESH_TOKEN", "YouTube Shorts publishing"],
        ["TIKTOK_CLIENT_SECRET + ACCESS_TOKEN", "TikTok publishing"],
        ["IG_TOKEN", "Instagram graph API — download + publish"],
      ]}
    />
  </div>
);

const analyticsContent = (
  <div className="space-y-3">
    <P>Analytics shows aggregated performance data from your published posts.</P>

    <H3>Panels</H3>
    <Ul>
      <Li><strong className="text-white">Overview</strong> — total posts, reach, impressions, avg engagement rate</Li>
      <Li><strong className="text-white">Categories breakdown</strong> — which content categories perform best</Li>
      <Li><strong className="text-white">Timeseries</strong> — daily post count and reach over time</Li>
    </Ul>

    <H3>Data freshness</H3>
    <P>Analytics ingests from the Instagram Graph API on the schedule set by <Code>analytics.ingest_interval_hours</Code>. Data may lag 24–48 h behind IG's own dashboard.</P>

    <Note type="info">Analytics only covers posts made through Travel CMS, not posts made directly on Instagram before you started using the system.</Note>
  </div>
);

const telegramContent = (
  <div className="space-y-3">
    <P>The Telegram bot lets you manage the system from your phone without opening the web UI.</P>

    <H3>Commands</H3>
    <Table
      headers={["Command", "What it does"]}
      rows={[
        ["/queue", "Lists upcoming scheduled posts"],
        ["/pending", "Lists posts awaiting approval"],
        ["/stats", "Media counts by status"],
        ["/settings", "Current settings summary"],
        ["/create", "Interactive wizard: category → tags → confirm → pipeline → preview push"],
        ["/help", "Full command list"],
      ]}
    />

    <H3>Inline buttons on preview push</H3>
    <P>Per-platform publish buttons appear for each enabled platform:</P>
    <Ul>
      <Li><strong className="text-white">📸 Publish IG / 🎵 Publish TikTok / ▶️ Publish YT</strong> — one button per enabled platform; publishes to that platform only</Li>
      <Li><strong className="text-white">✅ Approve All</strong> — publishes all enabled platforms at once (shown when more than one platform is pending)</Li>
      <Li><strong className="text-white">✏️ Edit caption</strong> — choose AI Refine (sends feedback to the caption model) or Replace (verbatim text)</Li>
      <Li><strong className="text-white">ℹ️ Details</strong> — shows full post info: category/tags, duration, hook score, per-platform IDs, errors</Li>
      <Li><strong className="text-white">🕐 Reschedule</strong> — sub-menu: +1h / +3h / +1d</Li>
      <Li><strong className="text-white">🔄 Regenerate</strong> — pick a different clip with the same category/tags</Li>
      <Li><strong className="text-white">🚫 Cancel</strong> — cancel the post and mark the clip do-not-use</Li>
      <Li><strong className="text-white">❌ Reject</strong> — permanently delete the post and clip</Li>
    </Ul>

    <Note type="info">Admin buttons (Edit caption, Details, Reschedule menu, Regenerate) are shown by default. Disable <Code>telegram.admin_controls</Code> for a minimal approve/reject-only preview.</Note>

    <H3>New settings (1.3.0)</H3>
    <Table
      headers={["Key", "Default", "Description"]}
      rows={[
        [<Code>telegram.always_preview</Code>, "true", "Push a rich preview at creation even when auto-publish is on — lets you cancel or reschedule before the slot fires."],
        [<Code>telegram.rich_publish_notify</Code>, "true", "Post-publish daemon notification loads media details, caption excerpt, and a Watch link instead of just the platform ID."],
        [<Code>telegram.admin_controls</Code>, "true", "Show extended admin buttons on every preview (Edit caption, Details, Reschedule menu, Regenerate). Disable for a minimal approve/reject-only UI."],
      ]}
    />

    <H3>Setup (production)</H3>
    <Pre>{`# 1. Set TELEGRAM_MODE=webhook in .env
# 2. After deploying backend, register webhook:
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<domain>/api/telegram/webhook/<SECRET>"

# 3. Set telegram.mode=webhook in Settings page
# 4. Set telegram.chat_id to your chat ID`}</Pre>

    <Note type="tip">In development, leave <Code>TELEGRAM_MODE=poll</Code>. The bot polls for updates automatically — no webhook needed.</Note>
  </div>
);

const libraryContent = (
  <div className="space-y-3">
    <P>Library shows all media rows in the database — every file ever indexed, with its current status.</P>

    <H3>Filters</H3>
    <Ul>
      <Li><strong className="text-white">Status</strong> — filter by raw / resized / uploaded / posted / error</Li>
      <Li><strong className="text-white">Category</strong> — filter by content category</Li>
      <Li><strong className="text-white">Tags</strong> — filter by tag</Li>
    </Ul>

    <H3>Preview button</H3>
    <P>Click the eye icon on any media card to open the fullscreen Preview page. From there you can play the video, view captions, edit with AI, and manage the linked post.</P>

    <H3>Reprocess</H3>
    <P>If a stage failed (status=error), use the Reprocess action on a media row to re-run the pipeline from that stage.</P>
  </div>
);

const enhanceContent = (
  <div className="space-y-3">
    <P>The enhance stage runs automatically after resize. It applies a series of FFmpeg filters to improve video quality before the clip reaches the Queue.</P>

    <H3>What it applies (in order)</H3>
    <Table
      headers={["Filter", "Effect"]}
      rows={[
        ["libvidstab (optional)", "2-pass camera shake stabilization. Slow (~1–3 min/clip). Toggle via video.auto_stabilize."],
        ["unsharp", "Edge sharpening to compensate for resize softening."],
        ["eq", "Contrast +0.05 and saturation +0.1 for more vivid footage."],
        ["fade", "0.3 s fade-in and 0.5 s fade-out."],
        ["Watermark blur (optional, off by default)", "Gaussian blur over the bottom 12 % strip (Instagram footer bar). Off by default — enable via video.remove_watermarks. Position: bottom | top | both."],
        ["Thumbnail", "Extracted at the video midpoint (duration / 2) so the poster frame isn't the common black first second."],
        ["loudnorm", "EBU R128 audio normalization — consistent loudness across clips."],
      ]}
    />

    <H3>Settings keys (video group)</H3>
    <Table
      headers={["Key", "Default", "Description"]}
      rows={[
        [<Code>video.auto_stabilize</Code>, "true", <><span>Run libvidstab stabilization. Disable to speed up the pipeline.</span><Rec value="false (enable only for shaky footage)" /></>],
        [<Code>video.remove_watermarks</Code>, "false", <><span>Blur the IG watermark strip. Off by default — videos publish with the original footer intact.</span><Rec value="false" /></>],
        [<Code>video.watermark_position</Code>, "bottom", <><span>bottom | top | both — which edge to blur.</span><Rec value="bottom" /></>],
        [<Code>video.enhance_quality</Code>, "true", <><span>Master toggle for the free FFmpeg quality chain at the edit stage (denoise + sharpen + better encode).</span><Rec value="true" /></>],
        [<Code>video.denoise</Code>, "true", <><span>hqdn3d denoise before motion so a zoom doesn't amplify grain.</span><Rec value="true" /></>],
        [<Code>video.denoise_strength</Code>, "light", <><span>light | medium | strong — denoise intensity.</span><Rec value="light" /></>],
        [<Code>video.sharpen</Code>, "true", <><span>Contrast-adaptive sharpen (cas) applied after the colour LUT.</span><Rec value="true" /></>],
        [<Code>video.sharpen_amount</Code>, "0.4", <><span>Sharpen strength 0.0–1.0. &gt;0.6 can look crunchy.</span><Rec value="0.4" /></>],
        [<Code>video.crf</Code>, "20", <><span>x264 quality (lower = sharper + bigger). Was 22 before 0.4.0.</span><Rec value="20" /></>],
        [<Code>video.preset</Code>, "medium", <><span>x264 preset — medium balances quality vs the server CPU cap.</span><Rec value="medium" /></>],
        [<Code>video.smooth_motion</Code>, "false", <><span>minterpolate frame-interp. CPU-EXPENSIVE — opt-in for slow-mo / pans.</span><Rec value="false (very CPU-heavy)" /></>],
        [<Code>video.smooth_fps</Code>, "60", <><span>Target fps when smooth_motion is on.</span><Rec value="60" /></>],
        [<Code>color.lut_mode</Code>, "category", <><span>Content-aware colour grade pick: <Code>category</Code> (by content category) | <Code>mood</Code> (by caption mood) | <Code>vision</Code> (AI picks from frames) | <Code>fixed</Code> (always one LUT). Configure in <strong className="text-white">Design → Color Grade</strong>.</span><Rec value="category" /></>],
        [<Code>color.fixed_lut</Code>, "(empty)", <><span>The single LUT applied to every reel when <Code>lut_mode = fixed</Code>. Value is the LUTS_DIR-relative path, e.g. <Code>cinematic/teal_orange.cube</Code>.</span></>],
        [<Code>color.use_vision</Code>, "false", <><span>Allow AI-vision to override the LUT by looking at the frames (reuses <Code>classify_vision</Code>; prefers a cached category to avoid a second Groq call). Off by default.</span><Rec value="false" /></>],
        [<Code>color.intensity</Code>, "1.0", <><span>Advisory grade strength 0.0–1.0. The full LUT is applied for now (no opacity blend in v1).</span><Rec value="1.0" /></>],
      ]}
    />

    <Note type="info">
      The quality chain (<Code>enhance_quality</Code> and friends) runs at the <strong className="text-white">edit</strong> stage
      in <Code>video_edit.py</Code> — denoise → Ken Burns → LUT → sharpen → optional smooth-motion — all free, CPU-only,
      no GPU. Resize also now scales with the sharper <Code>lanczos</Code> filter.
    </Note>

    <Note type="info">
      <strong className="text-white">Content-aware colour grading.</strong> <Code>lut_select.select_lut()</Code> picks the
      best-fitting LUT per clip via a cascade — manual pick → <Code>fixed</Code> → <Code>vision</Code> → <Code>mood</Code> → <Code>category</Code> —
      always degrading to the legacy category→LUT map. Curated cinematic LUTs live in <Code>assets/luts/cinematic/</Code>, tagged by
      mood/category in <Code>assets/luts/catalog.json</Code>. Build the library from raw vendor cubes with the manual script:
      <Code>python -m backend.scripts.curate_luts --apply</Code> (add <Code>--ffmpeg-test</Code> to smoke-test each LUT).
    </Note>

    <H3>On-demand re-enhancement</H3>
    <P>From the Preview page you can re-run the enhance stage for a single clip. Useful after changing watermark settings.</P>
    <Pre>{`POST /api/media/{id}/enhance
Body: { "remove_watermarks": false, "watermark_position": "bottom" }`}</Pre>

    <Note type="info">The enhance stage skips clips that are not in <Code>resized</Code> status. Re-run it manually from Preview if needed after a setting change.</Note>

    <H3>CLI</H3>
    <Pre>{`# Enhance all resized clips
python -m backend.pipeline.enhance_video

# Enhance a single clip
python -m backend.pipeline.enhance_video --media-id abc123`}</Pre>

    <H3>Merged-reel quality (montage enhancement · 1.7.0)</H3>
    <P>Merged reels get their own CPU-only, FFmpeg + OpenCV quality pass inside <Code>merge_clips.py</Code> — no GPU, no new dependency. The near-free improvements are on by default; the two CPU-heavy ones (smooth slow-mo, strong denoise) are opt-in.</P>
    <P><strong className="text-white">Per-clip adaptive treatment</strong> (<Code>merge.adaptive_fx</Code>, default on): instead of applying the same rule to every clip by index, each clip is treated by its <em>own</em> content (from the OpenCV metrics) — stronger clips hold longer on screen, calm/scenic clips get slow-motion + a Ken Burns push, already-dynamic action clips stay real-time, soft clips get sharpened, and only dark/noisy clips get denoised. Turn it off to fall back to the fixed alternating rules.</P>
    <Table
      headers={["Key (merge group)", "Default", "What it does"]}
      rows={[
        [<Code>merge.adaptive_fx</Code>, "true", <><span>Master toggle for per-clip content-adaptive FX (screen-time by quality, slow-mo on calm clips, Ken Burns on low-motion clips, sharpen soft clips, denoise noisy clips). Off = fixed index-parity rules.</span><Rec value="true" /></>],
        [<Code>merge.smart_select</Code>, "true", <><span>Picks the <strong className="text-white">best</strong> sub-shot of each clip via cheap OpenCV scoring (sharpness + exposure + motion, with a colour-histogram variety guard) instead of just the longest scene. Falls back to longest-scene when OpenCV is absent.</span><Rec value="true" /></>],
        [<Code>merge.select_sharpness_weight</Code>, "0.5", <><span>How hard sharpness weighs in the sub-shot score (0–1).</span><Rec value="0.5" /></>],
        [<Code>merge.select_min_sharpness</Code>, "0.0", <><span>Reject sub-shots below this normalized sharpness (0–1). 0 = rank only, never reject.</span><Rec value="0" /></>],
        [<Code>merge.color_match</Code>, "true", <><span>Gentle per-segment gray-world white-balance nudge (±12% max) so mixed-source clips don't jump in colour cut-to-cut.</span><Rec value="true" /></>],
        [<Code>merge.deband</Code>, "true", <><span>Anti-banding pass after the grade — removes sky/gradient banding grading introduces. Cheap.</span><Rec value="true" /></>],
        [<Code>merge.hard_cuts_on_beat</Code>, "true", <><span>Mixes ~1-frame hard cuts among the crossfades (every 3rd join) for a punchier, trend-native rhythm.</span><Rec value="true" /></>],
        [<Code>merge.deblock</Code>, "true", <><span>Removes IG-compression blocking artifacts from each segment. Cheap.</span><Rec value="true" /></>],
        [<Code>merge.smooth_slowmo</Code>, "false", <><span>Judder-free slow-mo via motion-compensated interpolation (minterpolate). Much smoother but <strong className="text-white">CPU-HEAVY (2–5×)</strong>.</span><Rec value="false (enable per-reel)" /></>],
        [<Code>merge.smooth_slowmo_max_s</Code>, "3.0", <><span>Only interpolate slowed segments up to this length (s) — caps the cost.</span><Rec value="3" /></>],
        [<Code>merge.sharpen</Code>, "false", <><span>Per-segment contrast-adaptive sharpen. Off by default — the edit stage already sharpens the final reel, so both on can over-sharpen.</span><Rec value="false" /></>],
        [<Code>merge.sharpen_amount</Code>, "0.3", <><span>cas strength 0–1 when <Code>merge.sharpen</Code> is on.</span><Rec value="0.2–0.4" /></>],
        [<Code>merge.strong_denoise</Code>, "false", <><span>nlmeans strong denoise for grainy clips. High quality, <strong className="text-white">CPU-HEAVY</strong>.</span><Rec value="false" /></>],
      ]}
    />
    <P>Three new <Code>merge.grade</Code> film profiles were added: <Code>teal_orange</Code> (cinematic split-tone), <Code>golden_hour</Code> (warm sunset), <Code>vivid_pop</Code> (punchy &amp; saturated).</P>
    <H3>Freshness &amp; Variety — non-repeating same-category reels</H3>
    <P>
      Make a second (third, Nth) merged reel from the <strong className="text-white">same category</strong> look
      different from the last so viewers don't see duplicates. Each reel records which sub-shots it used
      (source clip + timestamp + score) in its own metadata — <strong className="text-white">no extra storage,
      no cache, no migration</strong>. A new reel reads that memory, prefers never-used footage, spreads across
      as many different clips as possible, and only recycles proven best shots when the fresh pool runs out.
    </P>
    <Table
      headers={["Key (merge group)", "Default", "What it does"]}
      rows={[
        [<Code>merge.dedupe_enabled</Code>, "true", <><span>Avoid repeating clips across same-category reels. Hard-blocks sub-shots used in recent reels, down-weights older ones. First reel of a category is unchanged.</span><Rec value="true" /></>],
        [<Code>merge.subshot_cooldown_reels</Code>, "3", <><span>A used sub-shot is hard-blocked for the last N same-category reels (0–20). Beyond N it's down-weighted, not blocked.</span><Rec value="3" /></>],
        [<Code>merge.dedupe_soft_weight</Code>, "0.5", <><span>Selection-score multiplier for sub-shots past the cooldown (0–1). Lower = avoid reuse harder.</span><Rec value="0.5" /></>],
        [<Code>merge.proven_topup</Code>, "true", <><span>When the fresh pool can't fill the reel, top up with the highest-scoring previously-used sub-shots instead of falling short.</span><Rec value="true" /></>],
        [<Code>merge.proven_min_score</Code>, "0.5", <><span>Only recycle a sub-shot for top-up if its aesthetic score is ≥ this (0–1).</span><Rec value="0.5" /></>],
        [<Code>merge.dynamic_count</Code>, "true", <><span>Scale cut count to the category's footage and favor <strong className="text-white">maximum distinct clips</strong> (one cut per clip when the pool allows). Off = fixed <Code>min_segments</Code>/<Code>clips_per_reel</Code>.</span><Rec value="true" /></>],
        [<Code>merge.max_cuts_per_source</Code>, "1", <><span>Max cuts from one clip before another is reused — the variety lever. 1 = one cut/clip while distinct clips remain (relaxed on small pools so the reel still fills). 0 = auto.</span><Rec value="1" /></>],
        [<Code>merge.min_segments</Code>, "20", <><span>Auto-count floor — the montage never has fewer than this many cuts (15–30). Raised 15→20 in 1.8.1.</span><Rec value="20" /></>],
        [<Code>merge.split_stock_local</Code>, "true", <><span>Auto-select only: pull a floor of <strong className="text-white">stock B-roll</strong> AND <strong className="text-white">local-archive</strong> clips per montage. A thin pool on one side tops up from the other so the reel still fills.</span><Rec value="true" /></>],
        [<Code>merge.min_stock_segments</Code>, "8", <><span>Minimum stock (Pexels/Pixabay) clips per merged reel. Per-run overridable in the Create merge wizard's <em>Segment mix</em> panel.</span><Rec value="8" /></>],
        [<Code>merge.min_local_segments</Code>, "12", <><span>Minimum local-archive clips per merged reel. Per-run overridable in the Create merge wizard's <em>Segment mix</em> panel.</span><Rec value="12" /></>],
        [<Code>merge.auto_fetch_stock</Code>, "false", <><span>Opt-in: when the merge's category has <strong className="text-white">no stock yet</strong>, download a few clips per provider on the fly (before selection) so the montage can blend them. Needs <Code>stock.enabled</Code> + a provider key; best-effort, never aborts the merge.</span><Rec value="false" /></>],
        [<Code>merge.auto_fetch_pexels</Code>, "3", <><span>Clips pulled from Pexels when <Code>auto_fetch_stock</Code> fires.</span><Rec value="3" /></>],
        [<Code>merge.auto_fetch_pixabay</Code>, "3", <><span>Clips pulled from Pixabay when <Code>auto_fetch_stock</Code> fires.</span><Rec value="3" /></>],
      ]}
    />
    <Note type="info">
      Memory is <strong className="text-white">metadata-only</strong>: reuse re-cuts a clip on demand from the
      stored timestamp — no segment files are cached, so there's no disk budget to manage.
    </Note>
    <Note type="info">
      Neural upscaling / RIFE frame-interpolation are intentionally <strong className="text-white">not</strong> included — they require a GPU. On the CPU-only server, detail work is FFmpeg deblock + adaptive sharpen (a sharpness <em>illusion</em>), never true super-resolution.
    </Note>
  </div>
);

const enhancementsContent = (
  <div className="space-y-3">
    <P>
      Release 0.4.0 adds a set of AI feedback loops that make captions, hashtags, music,
      scheduling, and clip selection learn from what already performed. Each is an independent
      toggle in <strong className="text-white">Settings</strong> — all default <Code>on</Code>,
      and every one degrades gracefully (a failed external call just skips that enhancement).
    </P>

    <H3>Feature → setting map</H3>
    <Table
      headers={["Feature", "Setting", "Default", "What it does"]}
      rows={[
        ["Feedback hooks", <Code>caption.use_feedback</Code>, "true", "Injects the top-performing past hooks into the caption generator so new captions echo what already worked."],
        ["Trend topics", <Code>caption.use_trends</Code>, "true", "Injects the current weekly Google-Trends travel topics for timeliness. Trends 429 = skipped silently."],
        ["Self-critique", <Code>caption.self_critique</Code>, "true", "Extra OpenRouter pass that rewrites only the hook line for stronger scroll-stopping power."],
        ["Groq draft (Enh L)", <Code>caption.draft_with_groq</Code>, "false", "Draft the caption on the free Groq tier, then polish with the OpenRouter self-critique pass — caption cost stays $0. Falls back to full OpenRouter on any Groq error."],
        ["Hashtag A/B", <Code>hashtags.ab_test</Code>, "true", "Per post, coin-flips between the primary hashtag set and an alternate variant. Reach compared under Analytics → Hashtags."],
        ["Hashtag denylist (Enh L)", <Code>hashtags.blocked</Code>, "[] (built-in)", "Strips over-saturated / shadow-ban-prone tags from every generated set. Empty list uses the built-in default denylist."],
        ["Vision scoring", <Code>vision.enabled</Code>, "true", "Hook-scores each video's opening frames (Groq vision → local Moondream/Ollama fallback). Also runs as a nightly backfill at 03:00 (schedule.timezone) over un-scored footage. Tracked on the Classification page."],
        ["Vision provider", <Code>vision.provider</Code>, "auto", "Provider for the nightly 03:00 backfill: auto (Groq → local fallback) | groq | local."],
        ["Vision nightly limit", <Code>vision.nightly_limit</Code>, "50", "Max un-scored clips the nightly 03:00 vision backfill scores per run."],
        ["Mood music", <Code>music.mood_match</Code>, "true", "Picks background music whose mood matches the caption tone instead of a fixed query."],
        ["Slot optimization", <Code>schedule.optimize_times</Code>, "true", "Orders free daily slots by historical engagement so the best time fills first."],
        ["What-works selection", <Code>selection.use_performance</Code>, "true", "Blends each category's realized engagement into clip selection so proven categories get picked more often."],
        ["Selection weight", <Code>selection.performance_weight</Code>, "0.5", "How hard proven categories lift a clip's hook score (0 = ignore performance, 1 = max lift)."],
      ]}
    />

    <H3>Caption pipeline order</H3>
    <P>
      Caption generation now runs <strong className="text-white">before</strong> the edit stage so
      on-screen overlays carry the real hook text. Order: feedback + trends injected → caption
      generated (EN + AR) → self-critique hook rewrite → hashtag variant chosen.
    </P>

    <Note type="info">
      All toggles live in their own Settings groups: <Code>Caption AI</Code>, <Code>Vision scoring</Code>,
      <Code>Hashtag A/B test</Code>, <Code>Clip selection</Code>, plus <Code>schedule.optimize_times</Code> and
      <Code>music.mood_match</Code> inside the schedule and music groups.
    </Note>

    <Note type="tip">
      Turn any enhancement off to fall back to the 0.3.0 behavior — the pipeline runs identically,
      just without that signal.
    </Note>
  </div>
);

const classificationContent = (
  <div className="space-y-3">
    <P>
      The Classification page tracks server-side tagging progress across the whole media library:
      how much has been classified by Groq (category / tags) and how much has a vision
      hook-score, versus how much is still pending.
    </P>

    <H3>What the numbers mean</H3>
    <Ul>
      <Li><strong className="text-white">Groq classified</strong> — rows where <Code>category</Code> is set. The Groq classifier writes category + tags together and only runs on unclassified rows.</Li>
      <Li><strong className="text-white">Vision scored</strong> — rows with a <Code>hook_score</Code>. Vision only runs on <Code>VIDEO</Code> media, so its percentage is measured against the video subset, not all media.</Li>
      <Li><strong className="text-white">Remaining</strong> — Groq-pending + vision-pending counts still to process.</Li>
    </Ul>

    <H3>Breakdown table</H3>
    <P>
      A Category → Tags table shows total / Groq-done / vision-done per row. Filter by
      category or tag, and sort any column. Rows with no category or tags show as
      <Code>Unknown</Code>.
    </P>

    <H3>Backend</H3>
    <Table
      headers={["Endpoint", "Returns"]}
      rows={[
        [<Code>GET /api/classification/overview</Code>, "Totals: groq classified/remaining/pct, vision scored/remaining/pct, by_category, by_status."],
        [<Code>GET /api/classification/breakdown</Code>, "Nested category → tags counts for the filterable table."],
      ]}
    />

    <Note type="info">
      Both endpoints aggregate over the full media table via paginated fetch, so counts are
      accurate past Supabase's 1000-row response cap (the bug that made Analytics under-count
      before 0.4.0).
    </Note>

    <H3>Running classification</H3>
    <Pre>{`# Groq classifier (new downloads only)
python -m backend.pipeline.classify_groq

# Vision hook-scoring (Enh E) — local fallback, background backfill
python -m backend.pipeline.classify_vision --provider local --limit 50`}</Pre>
  </div>
);

const designContent = (
  <div className="space-y-3">
    <P>The Design page configures branded intro and cast (outro) screens prepended/appended to every generated reel. It uses a two-column layout: element controls on the left with a live animated preview on the right.</P>

    <H3>Intro screen</H3>
    <P>Prepended to the reel. At render time it grabs a frame at <Code>0.5 s</Code> from the reel video, scales it to 1080×1920, applies a semi-transparent color overlay (<Code>bg_opacity</Code>), then draws the configured text elements centered on top.</P>

    <H3>Cast (outro) screen</H3>
    <P>Appended to the reel. Same mechanism but grabs a frame at <Code>2.0 s</Code> (deeper into the clip for visual variety). Default CTA text: "Follow for more".</P>

    <H3>Per-element controls</H3>
    <P>Both screens decompose into individually configurable text elements. Each element has its own toggle, text override, color, font, font size, vertical order, and bottom padding. Order can be changed via drag-and-drop in the UI — the backend renders elements top-to-bottom by ascending <Code>*_order</Code> value.</P>

    <Table
      headers={["Intro elements (default order)", "Cast elements (default order)"]}
      rows={[
        ["Header (0) — custom text or @handle", "CTA (0) — call-to-action text"],
        ["Sub-header (1) — optional custom line", "Sub-header (1) — optional custom line"],
        ["Tags (2) — from media metadata", "Tags (2) — from media metadata"],
        ["Category (3) — from media metadata", "Category (3) — from media metadata"],
        ["Handle (5) — @handle from branding", "Handle (5) — @handle from branding"],
      ]}
    />

    <H3>Video frame backdrop</H3>
    <Ul>
      <Li>Intro grabs the reel frame at <Code>ss=0.5 s</Code>; cast grabs at <Code>ss=2.0 s</Code></Li>
      <Li><Code>bg_color</Code> + <Code>bg_opacity</Code> composite a color layer over the frame — at the default <Code>0.20</Code>, 80 % of the video frame shows through</Li>
      <Li>Falls back to a solid color if <Code>reel_ready_path</Code> is unavailable</Li>
    </Ul>

    <H3>Key settings — intro group</H3>
    <Table
      headers={["Key", "Default", "Description"]}
      rows={[
        [<Code>intro.enabled</Code>,            "false",       <><span>Master toggle — prepend intro screen to every reel.</span><Rec value="true (once configured)" /></>],
        [<Code>intro.mode</Code>,               '"generated"', <><span>"generated" (text card) | "asset" (uploaded file from assets/intros/).</span><Rec value="generated" /></>],
        [<Code>intro.duration_s</Code>,         "1.5",         <><span>Hold duration in seconds (1.0–4.0).</span><Rec value="1.5" /></>],
        [<Code>intro.animation</Code>,          '"fade"',      <><span>"none" | "fade" | "zoom".</span><Rec value="fade" /></>],
        [<Code>intro.bg_color</Code>,           '"#000000"',   <><span>Overlay color composited over the video frame.</span><Rec value="#000000" /></>],
        [<Code>intro.bg_opacity</Code>,         "0.20",        <><span>Overlay opacity 0.0–1.0. Lower = more video shows through.</span><Rec value="0.20" /></>],
        [<Code>intro.text_padding_h</Code>,     "40",          <><span>Horizontal padding in px applied to all text elements.</span><Rec value="40" /></>],
        [<Code>intro.header_enabled</Code>,     "true",        <><span>Toggle header element visibility.</span><Rec value="true" /></>],
        [<Code>intro.header_text</Code>,        '""',          "Custom text; empty = ig_handle from branding."],
        [<Code>intro.header_color</Code>,       '"#ffffff"',   <><span>Header text color.</span><Rec value="#ffffff" /></>],
        [<Code>intro.header_font_size</Code>,   "52",          <><span>Header font size in px.</span><Rec value="52" /></>],
        [<Code>intro.header_order</Code>,       "0",           <><span>Vertical order (lower number = higher on screen).</span><Rec value="0 (drag to reorder in UI)" /></>],
        [<Code>intro.header_bottom_padding</Code>, "0",        <><span>Extra space below this element in px.</span><Rec value="0" /></>],
        ["subheader / tags / category / handle", "— same pattern —", "Each element has: _enabled, _text (if applicable), _color, _font, _font_size, _order, _bottom_padding."],
      ]}
    />

    <Note type="info">Cast group uses identical per-element keys but starts with <Code>cta_*</Code> instead of <Code>header_*</Code>. CTA text defaults to "Follow for more". Duration default is also 1.5 s.</Note>

    <Note type="tip">Drag-and-drop in the Design UI updates <Code>*_order</Code> values live. Order is persisted to the settings table and respected verbatim in FFmpeg text rendering — no server restart needed.</Note>

    <H3>Asset mode</H3>
    <P>Set <Code>mode</Code> to <Code>"asset"</Code> and choose an uploaded file from <Code>assets/intros/</Code> (intro) or <Code>assets/outros/</Code> (cast). The asset is crop-scaled to 1080×1920 and trimmed/padded to <Code>duration_s</Code>. Upload via <strong className="text-white">Design → Upload asset</strong> (50 MB cap, mp4/mov/m4v/jpg/png).</P>
  </div>
);

const brandingContent = (
  <div className="space-y-3">
    <P>
      The branding overlay bakes a full-width white bottom bar onto every finished reel
      and its R2 thumbnail. The bar shows the shooting location on the left and your
      Instagram @handle on the right in Playfair Display serif.
    </P>

    <H3>Layout</H3>
    <Pre>{`┌──────────────────────────────┐
│                              │
│          (video)             │
│                              │
├──────────────────────────────┤
│ Kyoto, Japan    @yourhandle  │  ← 45 px white bar
└──────────────────────────────┘`}</Pre>

    <H3>Settings</H3>
    <Table
      headers={["Key", "Default", "Description"]}
      rows={[
        [<Code>branding.overlay_enabled</Code>, "false",  <><span>Master gate — opt-in; enable only after setting your handle.</span><Rec value="true (after setting handle)" /></>],
        [<Code>branding.ig_handle</Code>,        '""',    'Your @handle (e.g. @myaccount). Empty = overlay skipped.'],
        [<Code>branding.bar_height</Code>,       "45",    <><span>Bar height in px. Font scales proportionally (~26 px at 45 px).</span><Rec value="45" /></>],
        [<Code>branding.show_on_thumbnail</Code>,"true",  <><span>Brand the R2 thumbnail too so feed cover matches the reel.</span><Rec value="true" /></>],
        [<Code>branding.bar_bg_color</Code>,     '"#ffffff"', <><span>Bar background color (CSS hex).</span><Rec value="#ffffff" /></>],
        [<Code>branding.text_color</Code>,       '"#000000"', <><span>Location and @handle text color (CSS hex).</span><Rec value="#000000" /></>],
        [<Code>branding.bar_opacity</Code>,      "1.0",   <><span>Bar opacity 0.0–1.0. Text is always fully opaque.</span><Rec value="1.0" /></>],
        [<Code>branding.bar_position</Code>,     '"bottom"', <><span>Which edge of the frame. "bottom" | "top".</span><Rec value="bottom" /></>],
        [<Code>branding.font_size</Code>,        "0",     <><span>Font size in px. 0 = auto (proportional to bar_height).</span><Rec value="0 (auto)" /></>],
      ]}
    />

    <Note type="warn">
      Requires <Code>assets/fonts/PlayfairDisplay-SemiBold.ttf</Code> on the server.
      Download it free from Google Fonts (SIL OFL 1.1 — redistribution permitted), then
      place it at <Code>/srv/social-media-cms/assets/fonts/PlayfairDisplay-SemiBold.ttf</Code> on
      the server host (the assets/ directory is bind-mounted, shadowing the Docker image copy).
      Without the font file the overlay is silently skipped and a warning is logged.
    </Note>

    <H3>How it works</H3>
    <Ul>
      <Li>After LUT + sharpen in the edit stage, a <Code>drawbox</Code> + two <Code>drawtext</Code> filters are appended last in the FFmpeg chain so the bar composites on top of the colour grade.</Li>
      <Li>Tags are rendered comma-joined (e.g. "Coastal, Nature"). If no tags are set, only the @handle is drawn on the right.</Li>
      <Li>The R2 thumbnail (authoritative feed cover image) gets the same bar applied via a second FFmpeg pass immediately before upload.</Li>
      <Li>Emoji cannot be used in the bar — the serif font file cannot render colour emoji glyphs.</Li>
    </Ul>
  </div>
);

const decaptionContent = (
  <div className="space-y-3">
    <P>
      Decaption removes burned-in Instagram captions and watermarks from a clip before it
      enters a reel. Text and logos baked into the pixels (subtitles, sticker text, the
      IG/TikTok handle stamp) are detected, masked, and inpainted away with OpenCV so the
      published reel shows clean, original-looking footage.
    </P>

    <H3>Why bother</H3>
    <P>
      Clips that still carry another platform's watermark or leftover captions read as
      reposts, which suppresses cold-audience reach and can trip originality checks. Feeding
      clean footage into the reel gives the algorithm original-looking pixels to distribute.
    </P>

    <H3>How it works</H3>
    <Ul>
      <Li>The caption region is located — <Code>auto</Code> runs YOLO11 text detection to find text anywhere in the frame, or you pin it to the <Code>bottom</Code> / <Code>top</Code> third or a fixed <Code>custom</Code> box.</Li>
      <Li>The detected mask is expanded by <Code>dilate_px</Code> so anti-aliased edges are fully covered, then OpenCV inpaints the region away.</Li>
      <Li>If inpainting fails on a region, the <Code>fallback</Code> kicks in — blur it, solid-fill it, or leave it as-is.</Li>
    </Ul>

    <Note type="warn">
      Decaption is CPU-heavy (OpenCV inpaint runs per frame). To keep the pipeline fast, each
      clip is decaptioned <strong className="text-white">once</strong> and the cleaned result is
      cached and reused on every later reel — so the cost is paid only the first time a clip is used.
    </Note>

    <H3>Settings (decaption group)</H3>
    <Table
      headers={["Key", "Default", "Description"]}
      rows={[
        [<Code>decaption.enabled</Code>,       "false",    <><span>Master gate — opt-in. Strip burned-in captions/watermarks before a clip enters a reel.</span><Rec value="false (enable only if clips have burned-in text)" /></>],
        [<Code>decaption.algorithm</Code>,     '"hybrid"', <><span>OpenCV inpaint method: <Code>hybrid</Code> (best) | <Code>telea</Code> (fastest) | <Code>ns</Code> (Navier-Stokes).</span><Rec value="hybrid" /></>],
        [<Code>decaption.detect_mode</Code>,   '"auto"',   <><span><Code>auto</Code> (YOLO11 text detection, finds text anywhere) | <Code>bottom</Code> | <Code>top</Code> | <Code>custom</Code>. Fixed regions are faster.</span><Rec value="auto" /></>],
        [<Code>decaption.custom_bbox</Code>,   '""',       <><span>Region to inpaint when <Code>detect_mode = custom</Code>, as <Code>"x,y,w,h"</Code> in px, e.g. <Code>0,1600,1080,320</Code>.</span></>],
        [<Code>decaption.min_confidence</Code>,"0.35",     <><span>YOLO11 detection confidence threshold. Higher = fewer false positives.</span><Rec value="0.35" /></>],
        [<Code>decaption.dilate_px</Code>,     "6",        <><span>Expand the detected text mask by this many px before inpaint.</span><Rec value="6" /></>],
        [<Code>decaption.fallback</Code>,      '"blur"',   <><span>On inpaint failure: <Code>blur</Code> | <Code>fill</Code> | <Code>none</Code>.</span><Rec value="blur" /></>],
      ]}
    />

    <H3>Algorithm trade-offs</H3>
    <Table
      headers={["Algorithm", "When to use"]}
      rows={[
        ["hybrid", "Best all-round quality across mixed backgrounds — the default."],
        ["telea", "Fastest. Fast-marching inpaint; good when speed matters more than perfect fills."],
        ["ns", "Navier-Stokes — best on smooth gradients (skies, walls) where you want seamless blends."],
      ]}
    />

    <Note type="info">
      Decaption needs a one-time manual setup before it can be enabled — it pulls the YOLO11
      detection weights and OpenCV inpaint dependencies. Run
      <Code>python backend/scripts/setup_decaption.py</Code> on the server once, then flip
      <Code>decaption.enabled</Code> on.
    </Note>
  </div>
);

const stockContent = (
  <div className="space-y-3">
    <P>
      Stock footage sourcing searches Pexels/Pixabay for B-roll matching a category
      keyword and indexes the results as raw media exactly like a manual upload
      (<Code>source: "stock"</Code> instead of <Code>"upload"</Code>). Once indexed, the
      existing merge_clips montage builder already blends stock clips WITH your own archive
      footage in the same category reel — no merge-side changes needed.
    </P>

    <H3>How it works</H3>
    <Ul>
      <Li>Open the <strong className="text-white">Download</strong> page's <strong className="text-white">Stock</strong> tab, pick a category (and optional tags), optionally override the search query, then <strong className="text-white">Search</strong>.</Li>
      <Li>Results are filtered server-side to <Code>stock.min_short_side</Code> / <Code>stock.min_duration_s</Code> before you ever see them.</Li>
      <Li>Pick a result to <strong className="text-white">Import</strong> — it downloads, ffprobe-verifies, and lands in the same Library as any other raw clip, tagged with your chosen category and tags.</Li>
      <Li>An <strong className="text-white">imported library</strong> sits above the search grid — total clips + on-disk size, plus a collapsible per-category breakdown down to each clip (provider, dimensions, duration, file size, tags). The archive breakdown tab shows the same per-category stock totals under the archive tree.</Li>
      <Li><strong className="text-white">No duplicate downloads</strong> — a result already in your library is badged <em>In library</em> with Import disabled, and the server refuses to re-download the same provider clip even if two tabs race.</Li>
      <Li><strong className="text-white">HD, not 4K</strong> — imports pull the ~720p rendition (never 4K) to save storage: Pexels takes the largest file ≤720p, Pixabay the 720p <Code>medium</Code> tier. HD is plenty for 9:16 reels.</Li>
      <Li><strong className="text-white">Delete to reclaim storage</strong> — each clip in the library has a trash button that hard-deletes the file <em>and</em> its media row on the spot (stock clips are always re-downloadable from the provider).</Li>
    </Ul>

    <Note type="warn">
      Requires a free <Code>PEXELS_API_KEY</Code> and/or <Code>PIXABAY_API_KEY</Code> in <Code>.env</Code> — set at least one before enabling <Code>stock.enabled</Code>.
    </Note>

    <H3>Settings (stock group)</H3>
    <Table
      headers={["Key", "Default", "Description"]}
      rows={[
        [<Code>stock.enabled</Code>,              "false",      <><span>Master gate — opt-in.</span><Rec value="false" /></>],
        [<Code>stock.source</Code>,               '"pexels"',   <><span>Provider(s) to search: <Code>pexels</Code> | <Code>pixabay</Code> | <Code>both</Code>.</span><Rec value="pexels" /></>],
        [<Code>stock.per_category_query</Code>,   "{}",         <><span>Override the built-in search phrase per category. Empty = built-in cinematic travel phrases.</span></>],
        [<Code>stock.max_clips_per_search</Code>, "5",          <><span>Results fetched per search call.</span><Rec value="5" /></>],
        [<Code>stock.min_short_side</Code>,       "720",        <><span>Reject clips below this short-edge resolution (px).</span><Rec value="720" /></>],
        [<Code>stock.min_duration_s</Code>,       "5.0",        <><span>Reject clips shorter than this many seconds.</span><Rec value="5.0" /></>],
      ]}
    />
  </div>
);

const voiceoverContent = (
  <div className="space-y-3">
    <P>
      Voiceover generates a spoken narration of a reel's caption hook line using{" "}
      <Code>edge-tts</Code> (free, MIT), muxes it as the reel's primary audio track while
      ducking the music bed underneath, and burns word-synced subtitles from the same
      synthesis pass — no separate transcription step is needed, since the narration text
      is already known before speech is generated.
    </P>

    <H3>How it works</H3>
    <Ul>
      <Li>The <Code>voiceover</Code> pipeline stage runs after <Code>caption</Code> and before <Code>edit</Code>, deriving narration text from <Code>voiceover.narration_source</Code> (the caption hook line by default).</Li>
      <Li>Audio + word-boundary timing are generated in one <Code>edge-tts</Code> call and cached on the media row (<Code>voiceover_path</Code> / <Code>voiceover_srt_path</Code>) — regenerated only if missing.</Li>
      <Li>The edit stage mixes the narration at full volume, ducking any music bed to <Code>voiceover.music_duck_volume</Code>, and burns the SRT via ffmpeg's <Code>subtitles</Code> filter styled from <Code>voiceover.subtitle_*</Code>.</Li>
    </Ul>

    <Note type="warn">
      Requires a one-time manual Supabase migration before enabling:
      <Code>ALTER TABLE media ADD COLUMN voiceover_path TEXT; ALTER TABLE media ADD COLUMN voiceover_srt_path TEXT;</Code>
    </Note>

    <H3>Settings (voiceover group)</H3>
    <Table
      headers={["Key", "Default", "Description"]}
      rows={[
        [<Code>voiceover.enabled</Code>,            "false",            <><span>Master gate — opt-in.</span><Rec value="false" /></>],
        [<Code>voiceover.voice</Code>,               '"en-US-AriaNeural"', <><span>edge-tts voice id.</span></>],
        [<Code>voiceover.rate</Code>,                '"+0%"',            <><span>edge-tts speaking-rate adjustment.</span></>],
        [<Code>voiceover.narration_source</Code>,    '"caption_hook"',   <><span><Code>caption_hook</Code> (first line of the generated caption) | <Code>manual</Code>.</span></>],
        [<Code>voiceover.subtitles_enabled</Code>,   "true",             <><span>Burn word-synced subtitles from edge-tts's own timestamps.</span></>],
        [<Code>voiceover.subtitle_position</Code>,   '"bottom"',         <><span><Code>bottom</Code> | <Code>top</Code>.</span></>],
        [<Code>voiceover.subtitle_font_size</Code>,  "28",               <><span>Subtitle font size in px.</span></>],
        [<Code>voiceover.subtitle_color</Code>,      '"#ffffff"',        <><span>Subtitle text color (CSS hex).</span></>],
        [<Code>voiceover.music_duck_volume</Code>,   "0.08",             <><span>Music bed volume while narration plays (below the normal ~0.15 default).</span></>],
      ]}
    />
  </div>
);

const editorContent = (
  <div className="space-y-3">
    <P>
      The <strong className="text-white">Reel editor</strong> at <Code>/editor/:mediaId</Code> —
      opened from the “Edit timeline” button on a reel's Preview page — turns a rendered reel back
      into an editable timeline. It is non-destructive: you edit the <em>source clips</em>, and
      exporting re-renders from them rather than re-encoding the finished MP4.
    </P>

    <H3>The two documents</H3>
    <Ul>
      <Li><strong className="text-white">EDL</strong> — your saved edit list. Asset names are library-relative, coordinates are normalized 0–1, and effects are stored as intent (“speed 0.85”, “Ken Burns on”). Versioned, reopenable.</Li>
      <Li><strong className="text-white">PLAN</strong> — what export compiles the EDL into: absolute validated paths, resolved effect decisions, pixel geometry. Discarded after the render.</Li>
    </Ul>
    <P>
      Normalized coordinates are why the browser preview and the FFmpeg render agree on where a
      text or sticker layer sits — there is no scale factor to get wrong.
    </P>

    <H3>What each part of the export renders</H3>
    <Table
      headers={["Owner", "Renders"]}
      rows={[
        [<Code>merge_clips.render()</Code>, "Geometry and time: cut order, in/out, transitions, per-cut speed and Ken Burns, the film grade, and the music bed."],
        [<Code>video_edit.edit_single()</Code>, "Everything composited on top, in one encode: the brightness/contrast/saturation adjust, the LUT, text layers, image/sticker layers, the branding bar, subtitles, and the intro/cast screens."],
      ]}
    />
    <P>
      That split is why a text- or sticker-only change is fast: it re-runs the composite pass on
      the cached merge output instead of re-merging every clip.
    </P>

    <H3>Inspector tabs</H3>
    <Ul>
      <Li><strong className="text-white">Clip</strong> — in/out, speed (slow-motion only), smooth slow-mo, Ken Burns direction and drift, and the transition into the next clip. Loop-friendly lives here too: it echoes the opening cut as the last cut and skips the music fade-out, so the reel loops seamlessly.</Li>
      <Li><strong className="text-white">Text</strong> — content, font, size, colour, position, anchor, timing and fade.</Li>
      <Li><strong className="text-white">Image</strong> — sticker/logo/watermark overlays: pick from the sticker library or upload a PNG/WebP, then set position, size, opacity, stacking order and timing.</Li>
      <Li><strong className="text-white">Colour</strong> — film-grade profile (with deband/grain/vignette), LUT, and the exposure adjust. Picking a grade clears the LUT, because a graded merge makes the export skip <Code>lut3d</Code>.</Li>
      <Li><strong className="text-white">Audio</strong> — bed vs. original clip audio, track swap, volume, fade, entry point, and the narration duck level.</Li>
    </Ul>

    <H3>Stickers</H3>
    <Ul>
      <Li>Upload PNG or WebP (10 MB cap) from the Image tab, or drop files straight into <Code>assets/stickers/</Code> on the server. The library ships empty — there is no built-in set.</Li>
      <Li>Position is the layer's <em>centre</em>, given as a fraction of the frame, so a sticker stays put regardless of output resolution. Leave height empty to preserve the source aspect ratio.</Li>
      <Li>Images composite above text layers. Stacking within the image lane follows the <Code>z</Code> value, ascending.</Li>
    </Ul>

    <H3>Versions</H3>
    <Ul>
      <Li>Autosave writes a new version every <Code>editor.autosave_seconds</Code>; history is pruned to <Code>editor.keep_versions</Code>. The <strong className="text-white">History</strong> button on the top bar lists them and loads any one back.</Li>
      <Li><strong className="text-white">Revert to original</strong> rebuilds the edit list from how the reel was actually rendered. It does not delete anything — you revert, edit, and save a new version on top.</Li>
      <Li>Undo/redo (⌘Z / ⇧⌘Z) is separate and in-memory: it is a scratch buffer for the current session, while versions are the durable history.</Li>
    </Ul>

    <Note type="warn">
      Reels merged before v2.0.0 show an <strong>approximate</strong> banner. Their per-cut
      slow-mo, Ken Burns, cleanup filters, join durations and music offset were never recorded, so
      the edit list is reconstructed from what the merge did store — re-exporting one produces a
      close, but not identical, reel. Reels merged from v2.0.0 on round-trip exactly.
    </Note>

    <Note type="info">
      Export always writes a <strong>new</strong> media row and repoints the queued post at it, so
      the post keeps its schedule, slot and caption. The reel you edited is never mutated.
    </Note>

    <H3>Preview fidelity</H3>
    <P>
      The player is an approximation, not the renderer. Transitions preview by family rather than
      by xfade's exact easing, the film grade is not previewed at all (only the LUT and the
      exposure adjust are, via a WebGL shader), and the music bed plays without the export's
      fades. Everything else — timing, layer geometry, speed, Ken Burns — matches the export.
    </P>
    <Note type="tip">
      The LUT preview samples a baked 2D texture per <Code>.cube</Code>. After adding LUTs run{" "}
      <Code>python -m backend.scripts.make_lut_previews</Code> on the server, or the editor
      previews the exposure adjust only. <Code>editor.preview_lut</Code> turns it off entirely.
    </Note>

    <H3>Settings (editor group)</H3>
    <Table
      headers={["Key", "Default", "Description"]}
      rows={[
        [<Code>editor.enabled</Code>,           "true",        <><span>Master gate for the <Code>/editor</Code> route and the <Code>/api/editor/*</Code> API.</span></>],
        [<Code>editor.proxy_height</Code>,      "480",         <><span>Short-edge px of the preview proxies re-cut per clip. Higher = sharper scrubbing, slower to open.</span><Rec value="480" /></>],
        [<Code>editor.proxy_ttl_days</Code>,    "7",           <><span>Cached proxies older than this are swept nightly at 04:00.</span></>],
        [<Code>editor.autosave_seconds</Code>,  "15",          <><span>Debounced autosave interval.</span></>],
        [<Code>editor.keep_versions</Code>,     "20",          <><span>EDL versions retained per reel; older ones are pruned on save.</span></>],
        [<Code>editor.max_text_layers</Code>,   "20",          <><span>Per-reel cap on text layers (render cost + abuse ceiling).</span></>],
        [<Code>editor.max_image_layers</Code>,  "10",          <><span>Per-reel cap on image/sticker layers.</span></>],
        [<Code>editor.max_cuts</Code>,          "40",          <><span>Per-reel cap on timeline cuts; matches the merge renderer's own limit.</span></>],
        [<Code>editor.export_mode</Code>,       '"overwrite"', <><span><Code>overwrite</Code> repoints the existing post | <Code>new_post</Code>.</span></>],
        [<Code>editor.preview_lut</Code>,       "true",        <><span>WebGL 3D-LUT preview in the browser; off = plain video (the export still applies the LUT).</span></>],
      ]}
    />

    <H3>Keyboard</H3>
    <Table
      headers={["Key", "Action"]}
      rows={[
        ["Space", "Play / pause"],
        ["J / K / L", "Shuttle back · pause · play"],
        ["← / →", "Step one frame"],
        ["S", "Split the selected clip at the playhead"],
        ["Del / ⌫", "Remove the selected clip"],
        ["⌘Z / ⇧⌘Z", "Undo / redo"],
        ["+ / −", "Zoom the timeline"],
      ]}
    />

    <Note type="warn">
      Desktop only. Under 1024 px the editor shows an “open on desktop” notice — the timeline,
      player and inspector need to be side by side to be usable.
    </Note>
  </div>
);

const assetsContent = (
  <div className="space-y-3">
    <P>
      The <strong className="text-white">Assets</strong> page is the admin surface for every
      static asset the pipeline draws from — music, fonts, LUTs, intro screens, and cast/outro
      screens — indexed into a Supabase Storage bucket + <Code>assets</Code> table on top of the
      local <Code>assets/</Code> directory the pipeline already reads from directly. The former
      standalone Audio page was folded into this page's <strong className="text-white">Music</strong> tab
      (the old <Code>/audio</Code> URL redirects here automatically).
    </P>

    <H3>How the index works</H3>
    <Ul>
      <Li>Local disk stays the fast path and the only thing the FFmpeg pipeline (merge, resize, LUT grade, intro/cast overlay) reads from directly — nothing about the pipeline changed.</Li>
      <Li>Every asset also gets a row in a Supabase <Code>assets</Code> table with a stable, public Storage URL — this is what makes tracks/LUTs/fonts playable or previewable from the admin UI without a local dev server serving files.</Li>
      <Li>Read order per asset: local file if present, else the Storage public URL.</Li>
    </Ul>

    <H3>Search / sort / filter toolbar</H3>
    <Ul>
      <Li>One toolbar above the library grid applies to whichever tab is active — a text search (matches title/name/filename plus tags and categories), a sort select (favourite first / recently used / most used / name A-Z / date added), a favourites-only toggle, and tag+category filter chips (OR-matched, derived from whatever's tagged in the currently loaded tab).</Li>
      <Li>Everything narrows client-side over the already-fetched list — no extra API calls fire while typing or toggling filters.</Li>
    </Ul>

    <H3>Sync (dry-run → confirm)</H3>
    <Ul>
      <Li>The <strong className="text-white">Sync</strong> button reconciles local disk, the Storage bucket, and existing DB rows for the active tab's asset type.</Li>
      <Li>The first click is a preview only — new/updated/removed counts, nothing written. A second <strong className="text-white">Confirm</strong> commits it.</Li>
      <Li>Sync never deletes a local file, and only prunes a DB row when the asset is missing from <strong className="text-white">both</strong> local disk and Storage — a file present on just one side is left alone.</Li>
    </Ul>

    <H3>Per-type tabs</H3>
    <Ul>
      <Li><strong className="text-white">Music</strong> — play/favourite/tag/trim/upload, with a live playhead progress bar and mm:ss counter on whichever track is currently playing; trimming uploads the trimmed clip to Storage and links it back to the source track.</Li>
      <Li><strong className="text-white">Fonts</strong>, <strong className="text-white">LUTs</strong> — read-only browse + rename/delete; new files are added by dropping them in <Code>assets/fonts/</Code> / <Code>assets/luts/</Code> (or the Storage bucket) and running Sync.</Li>
      <Li><strong className="text-white">Intros</strong>, <strong className="text-white">Outros</strong> — browse + upload + rename/delete; the Design page's intro/cast asset picker links here to upload a new screen file.</Li>
    </Ul>

    <H3>Trim (waveform editor)</H3>
    <Ul>
      <Li>The <strong className="text-white">Trim</strong> button on a music track opens a waveform editor — drag the region handles, or type exact start/end seconds (with ±0.1s nudge buttons) for frame-accurate control.</Li>
      <Li><strong className="text-white">Loop selection</strong> previews just the trimmed region on repeat instead of playing past it; a zoom slider stretches the waveform for fine-grained editing on longer tracks.</Li>
      <Li>Optional fade-in/fade-out (0–5s) are applied server-side and included with the trim, then <strong className="text-white">Save as new track</strong> creates a separate clip without touching the original.</Li>
    </Ul>

    <H3>Refresh (dry-run → confirm) — Music tab only</H3>
    <Ul>
      <Li>The <strong className="text-white">Refresh</strong> button (next to Sync, Music tab only) scans <Code>assets/music/</Code> for files dropped in outside the app — different from Sync, which reconciles the Storage bucket.</Li>
      <Li>The first click is always a <strong className="text-white">preview only</strong> — it reports new files found and duplicate groups on disk, with a count of how many files a cleanup would delete. Nothing is changed yet.</Li>
      <Li>A second explicit <strong className="text-white">Confirm cleanup</strong> action executes it — new files are indexed and duplicate files are actually deleted from disk, plus orphaned cache entries (rows pointing at files no longer on disk) are pruned. This is a deliberate two-step flow since cleanup is destructive to physical files.</Li>
    </Ul>

    <Note type="warn">
      Refresh cleanup permanently deletes duplicate files from disk — always review the preview counts before confirming.
    </Note>

    <H3>Favourite / usage scoring (music selection)</H3>
    <P>
      Favouriting a track and its historical usage both feed into automatic music selection at edit time, via three <Code>music.*</Code> settings:
      a flat score bonus for favourites, a log-scaled bonus per past use (so proven tracks get preferred without one track playing on every reel), and a cooldown window that avoids repeating the same recently-used tracks back to back.
    </P>
    <Table
      headers={["Key", "Default", "Description"]}
      rows={[
        [<Code>music.favourite_boost</Code>,     "3.0", <><span>Score bonus added to favourited tracks during auto-selection.</span><Rec value="3.0" /></>],
        [<Code>music.usage_weight</Code>,        "0.3", <><span>Score bonus scale per historical use (log-scaled), so proven tracks are preferred without dominating.</span><Rec value="0.3" /></>],
        [<Code>music.cooldown_recent_cap</Code>, "10",  <><span>How many recently-used tracks are remembered for no-repeat cooldown.</span><Rec value="10" /></>],
      ]}
    />

    <H3>Favourite / usage / tags (every type)</H3>
    <Ul>
      <Li>Every asset type — not just music — carries <Code>favourite</Code>, <Code>usage_count</Code>, <Code>last_used_at</Code>, <Code>tags</Code>, and <Code>categories</Code> as real columns on the <Code>assets</Code> table.</Li>
      <Li>The Design page's LUT and font pickers read from this unified index, with an inline favourite-star toggle and tag/category filter chips derived from whatever's currently tagged.</Li>
      <Li><Code>usage_count</Code> auto-increments the first time a LUT, font, intro, or cast screen is actually applied to a rendered reel — pure analytics, best-effort, never blocks a render if the bump fails.</Li>
      <Li>The Preview page's post-detail panel shows the resolved music track name (linking back here) with an inline favourite toggle and "used N×" badge.</Li>
    </Ul>

    <Note type="warn">
      Requires one-time manual setup before it's live: create the Supabase Storage bucket
      (public-read) and apply the <Code>014_assets_table.sql</Code> migration, then
      <Code>015_assets_metadata_columns.sql</Code> for the favourite/usage/tags columns, to the
      Supabase project. Existing files in <Code>assets/</Code> also need to be uploaded into the
      bucket by hand — this feature indexes what's there, it doesn't migrate files for you.
    </Note>
  </div>
);

// ── sections ──────────────────────────────────────────────────────────────────

const SECTIONS: Section[] = [
  { id: "overview",   label: "Overview & pipeline",   icon: Layers,      accent: "blue",    content: overviewContent },
  { id: "downloads",  label: "Downloads",              icon: Download,    accent: "sky",     content: downloadsContent },
  { id: "pipeline",   label: "Pipeline page",          icon: Terminal,    accent: "orange",  content: pipelineContent },
  { id: "enhance",    label: "Video enhancement",      icon: Wand2,       accent: "indigo",  content: enhanceContent },
  { id: "design",     label: "Design page (Intro & Cast)", icon: Monitor,   accent: "rose",    content: designContent },
  { id: "branding",   label: "Video branding",         icon: Film,        accent: "pink",    content: brandingContent },
  { id: "decaption",  label: "Decaption",              icon: Eraser,      accent: "violet",  content: decaptionContent },
  { id: "create",     label: "Create Video",           icon: Film,        accent: "purple",  content: createContent },
  { id: "editor",     label: "Reel editor",            icon: Scissors,    accent: "indigo",  content: editorContent },
  { id: "queue",      label: "Queue & approval",       icon: CalendarDays,accent: "emerald", content: queueContent },
  { id: "library",    label: "Library",                icon: Globe,       accent: "teal",    content: libraryContent },
  { id: "settings",   label: "Settings reference",     icon: Settings,    accent: "pink",    content: settingsContent },
  { id: "analytics",  label: "Analytics",              icon: BarChart3,   accent: "violet",  content: analyticsContent },
  { id: "classification", label: "Classification",     icon: ScanSearch,  accent: "teal",    content: classificationContent },
  { id: "enhancements", label: "AI enhancements",      icon: Sparkles,    accent: "emerald", content: enhancementsContent },
  { id: "telegram",   label: "Telegram bot",           icon: MessageCircle, accent: "yellow", content: telegramContent },
  { id: "stock",      label: "Stock footage",          icon: Video,       accent: "sky",     content: stockContent },
  { id: "voiceover",  label: "Voiceover",              icon: Mic,         accent: "teal",    content: voiceoverContent },
  { id: "assets",     label: "Assets (Supabase index)", icon: FolderOpen,  accent: "sky",     content: assetsContent },
];

const ACCENT: Record<string, { ring: string; icon: string }> = {
  blue:    { ring: "ring-blue-500/20 bg-blue-500/10",    icon: "text-blue-400" },
  indigo:  { ring: "ring-indigo-500/20 bg-indigo-500/10", icon: "text-indigo-400" },
  sky:     { ring: "ring-sky-500/20 bg-sky-500/10",     icon: "text-sky-400" },
  orange:  { ring: "ring-orange-500/20 bg-orange-500/10", icon: "text-orange-400" },
  purple:  { ring: "ring-purple-500/20 bg-purple-500/10", icon: "text-purple-400" },
  emerald: { ring: "ring-emerald-500/20 bg-emerald-500/10", icon: "text-emerald-400" },
  teal:    { ring: "ring-teal-500/20 bg-teal-500/10",   icon: "text-teal-400" },
  pink:    { ring: "ring-pink-500/20 bg-pink-500/10",   icon: "text-pink-400" },
  violet:  { ring: "ring-violet-500/20 bg-violet-500/10", icon: "text-violet-400" },
  yellow:  { ring: "ring-yellow-500/20 bg-yellow-500/10", icon: "text-yellow-400" },
  rose:    { ring: "ring-rose-500/20 bg-rose-500/10",    icon: "text-rose-400" },
};

// ── page ──────────────────────────────────────────────────────────────────────

export function DocsPage() {
  const [open, setOpen] = useState<Record<string, boolean>>({ overview: true });

  const toggle = (id: string) => setOpen((prev) => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white flex items-center gap-2">
          <BookOpen size={22} className="text-blue-400" />
          Documentation
        </h2>
        <p className="text-sm text-gray-500 mt-1">
          How to use every part of Travel CMS — with setting values, examples, and tips.
        </p>
      </div>

      {/* quick-start box */}
      <div className="bg-blue-950/20 border border-blue-800/40 rounded-xl p-4">
        <p className="text-xs font-semibold text-blue-300 uppercase tracking-wide mb-2">Quick start</p>
        <ol className="text-sm text-blue-200/70 space-y-1 list-none">
          {[
            "Downloads → Fetch Posts (downloads your IG archive)",
            "Pipeline → Run Index stage (registers media in DB)",
            "Pipeline → Run Classify stage (tags category / tags)",
            "Create → Best clip or Random → confirm → video is queued",
            "Queue → Approve post → publishes immediately (or auto-publishes after the 1-hour window)",
          ].map((step, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-blue-500 font-bold shrink-0">{i + 1}.</span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </div>

      {/* sections */}
      {SECTIONS.map((s) => {
        const isOpen = !!open[s.id];
        const ac = ACCENT[s.accent] ?? ACCENT.blue;
        const Icon = s.icon;

        return (
          <section key={s.id} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <header
              className="flex items-center gap-4 px-5 py-4 cursor-pointer select-none hover:bg-gray-800/40 transition-colors"
              onClick={() => toggle(s.id)}
            >
              <div className={`p-2 rounded-lg ring-1 ${ac.ring}`}>
                <Icon size={16} className={ac.icon} />
              </div>
              <span className="flex-1 text-sm font-semibold text-white">{s.label}</span>
              {isOpen
                ? <ChevronUp size={14} className="text-gray-500" />
                : <ChevronDown size={14} className="text-gray-500" />}
            </header>
            {isOpen && (
              <div className="border-t border-gray-800 px-5 py-5">
                {s.content}
              </div>
            )}
          </section>
        );
      })}

      <div className="text-xs text-gray-600 text-center pb-4">
        <a
          href="https://github.com/anthropics/claude-code/issues"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 hover:text-gray-400 transition-colors"
        >
          <ExternalLink size={10} /> Report an issue
        </a>
        <span className="mx-2">·</span>
        <span>Travel CMS — built with Claude Code</span>
      </div>
    </div>
  );
}
