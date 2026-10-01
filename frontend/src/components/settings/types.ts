export type FieldHint = { desc: string; example?: string; recommended?: string };

export type VersionInfo = {
  backend: { commit: string; branch: string; tag: string; build_time: string };
  runtime: { python: string; fastapi: string; uvicorn: string; supabase: string; openrouter: string; groq: string };
};
