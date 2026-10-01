import { createClient } from "@supabase/supabase-js";

const isDemo = import.meta.env.VITE_DEMO_MODE === "true";
// Demo mode never talks to Supabase; placeholders keep createClient happy.
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || (isDemo ? "https://demo.supabase.co" : "");
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || (isDemo ? "demo-anon-key" : "");

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error("Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY env vars");
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
