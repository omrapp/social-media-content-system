import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const IG_TOKEN = Deno.env.get("IG_TOKEN")!;

const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

async function notify(type: string, title: string, message: string) {
  await supabase.from("notifications").insert({ type, title, message });
}

Deno.serve(async () => {
  try {
    const resp = await fetch(
      `https://graph.facebook.com/v20.0/oauth/access_token?` +
        new URLSearchParams({
          grant_type: "ig_exchange_token",
          client_secret: Deno.env.get("IG_APP_SECRET") || "",
          access_token: IG_TOKEN,
        })
    );
    const data = await resp.json();

    if (data.error) {
      await notify("error", "Token refresh failed", data.error.message);
      return new Response(JSON.stringify({ error: data.error.message }), { status: 500 });
    }

    // Store new token — update your secrets/vault as needed
    // For now, log success and notify
    await notify(
      "success",
      "Token refreshed",
      `New token expires in ${Math.floor(data.expires_in / 86400)} days`
    );

    return new Response(
      JSON.stringify({
        success: true,
        expires_in_days: Math.floor(data.expires_in / 86400),
      })
    );
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    await notify("error", "Token refresh error", msg);
    return new Response(JSON.stringify({ error: msg }), { status: 500 });
  }
});
