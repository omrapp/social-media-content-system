import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const IG_TOKEN = Deno.env.get("IG_TOKEN")!;
const IG_API = `https://graph.facebook.com/v20.0`;

const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

const METRICS = "impressions,reach,likes,comments,shares,saved,plays";

async function fetchInsights(igMediaId: string) {
  const resp = await fetch(
    `${IG_API}/${igMediaId}/insights?metric=${METRICS}&access_token=${IG_TOKEN}`
  );
  const data = await resp.json();
  if (data.error) return null;

  const metrics: Record<string, number> = {};
  for (const item of data.data || []) {
    metrics[item.name] = item.values?.[0]?.value ?? 0;
  }
  return metrics;
}

Deno.serve(async () => {
  try {
    // Fetch posts published in last 30 days
    const thirtyDaysAgo = new Date(Date.now() - 30 * 86400000).toISOString();
    const { data: posts, error } = await supabase
      .from("posts")
      .select("id, ig_media_id")
      .eq("status", "posted")
      .not("ig_media_id", "is", null)
      .gte("published_at", thirtyDaysAgo);

    if (error) throw error;
    if (!posts?.length) return new Response(JSON.stringify({ fetched: 0 }));

    let fetched = 0;
    for (const post of posts) {
      const metrics = await fetchInsights(post.ig_media_id);
      if (!metrics) continue;

      const totalEngagement = (metrics.likes || 0) + (metrics.comments || 0) +
        (metrics.shares || 0) + (metrics.saved || 0);
      const engagementRate = metrics.reach ? totalEngagement / metrics.reach : 0;

      await supabase.from("analytics").insert({
        post_id: post.id,
        ig_media_id: post.ig_media_id,
        impressions: metrics.impressions || 0,
        reach: metrics.reach || 0,
        likes: metrics.likes || 0,
        comments: metrics.comments || 0,
        shares: metrics.shares || 0,
        saves: metrics.saved || 0,
        plays: metrics.plays || 0,
        engagement_rate: engagementRate,
      });
      fetched++;
    }

    return new Response(JSON.stringify({ fetched }));
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return new Response(JSON.stringify({ error: msg }), { status: 500 });
  }
});
