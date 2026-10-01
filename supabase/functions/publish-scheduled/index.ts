import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const IG_TOKEN = Deno.env.get("IG_TOKEN")!;
const IG_USER_ID = Deno.env.get("IG_USER_ID")!;
const IG_API = `https://graph.facebook.com/v20.0`;
const MAX_RETRIES = 3;

const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

async function createContainer(mediaUrl: string, caption: string): Promise<string> {
  const resp = await fetch(`${IG_API}/${IG_USER_ID}/media`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      media_type: "REELS",
      video_url: mediaUrl,
      caption,
      access_token: IG_TOKEN,
    }),
  });
  const data = await resp.json();
  if (data.error) throw new Error(data.error.message);
  return data.id;
}

async function pollContainer(containerId: string): Promise<void> {
  for (let i = 0; i < 30; i++) {
    const resp = await fetch(
      `${IG_API}/${containerId}?fields=status_code&access_token=${IG_TOKEN}`
    );
    const data = await resp.json();
    if (data.status_code === "FINISHED") return;
    if (data.status_code === "ERROR") throw new Error(`Container error: ${JSON.stringify(data)}`);
    await new Promise((r) => setTimeout(r, 10000));
  }
  throw new Error("Container polling timeout");
}

async function publishContainer(containerId: string): Promise<string> {
  const resp = await fetch(`${IG_API}/${IG_USER_ID}/media_publish`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      creation_id: containerId,
      access_token: IG_TOKEN,
    }),
  });
  const data = await resp.json();
  if (data.error) throw new Error(data.error.message);
  return data.id;
}

async function notify(type: string, title: string, message: string) {
  await supabase.from("notifications").insert({ type, title, message });
}

Deno.serve(async () => {
  try {
    // Fetch posts ready to publish: scheduled posts past their time, or preview posts past their window
    const { data: posts, error } = await supabase
      .from("posts")
      .select("*, media!inner(r2_url)")
      .or(
        `and(status.eq.scheduled,scheduled_at.lte.${new Date().toISOString()}),` +
        `and(status.eq.preview,publish_after.lte.${new Date().toISOString()})`
      )
      .limit(10);

    if (error) throw error;
    if (!posts?.length) return new Response(JSON.stringify({ published: 0 }));

    let published = 0;
    for (const post of posts) {
      if (post.retry_count >= MAX_RETRIES) {
        await supabase
          .from("posts")
          .update({ status: "error", error_message: "Max retries exceeded" })
          .eq("id", post.id);
        await notify("error", "Publish failed", `Post ${post.id} exceeded max retries`);
        continue;
      }

      try {
        await supabase
          .from("posts")
          .update({ status: "publishing" })
          .eq("id", post.id);

        const hashtagsEn = (post.hashtags_en || []).map((t: string) => `#${t}`).join(" ");
        const hashtagsAr = (post.hashtags_ar || []).map((t: string) => `#${t}`).join(" ");
        const fullCaption = [post.caption, hashtagsEn, hashtagsAr].filter(Boolean).join("\n\n");

        const containerId = await createContainer(post.media.r2_url, fullCaption);
        await supabase
          .from("posts")
          .update({ ig_container_id: containerId })
          .eq("id", post.id);

        await pollContainer(containerId);
        const igMediaId = await publishContainer(containerId);

        await supabase
          .from("posts")
          .update({
            status: "posted",
            ig_media_id: igMediaId,
            published_at: new Date().toISOString(),
          })
          .eq("id", post.id);

        await supabase
          .from("media")
          .update({ status: "posted" })
          .eq("id", post.media_id);

        published++;
        await notify("success", "Post published", `Successfully posted to Instagram: ${igMediaId}`);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        await supabase
          .from("posts")
          .update({
            status: "error",
            error_message: msg,
            retry_count: post.retry_count + 1,
          })
          .eq("id", post.id);
        await notify("error", "Publish error", msg);
      }
    }

    return new Response(JSON.stringify({ published }));
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return new Response(JSON.stringify({ error: msg }), { status: 500 });
  }
});
