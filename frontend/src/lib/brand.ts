// Public-facing branding (landing / privacy / terms). Set via VITE_* env vars
// at build time so each deployment carries its own name, contact and links.
const env = import.meta.env;

export const APP_NAME: string = env.VITE_APP_NAME || "Social Media CMS";
export const OPERATOR_NAME: string = env.VITE_OPERATOR_NAME || "the operator";
export const CONTACT_EMAIL: string = env.VITE_CONTACT_EMAIL || "contact@example.com";

export const SOCIAL_URLS = {
  instagram: env.VITE_INSTAGRAM_URL || "",
  youtube: env.VITE_YOUTUBE_URL || "",
  tiktok: env.VITE_TIKTOK_URL || "",
};

/** "https://youtube.com/@name" → "@name"; falls back to the last path segment. */
export function handleFromUrl(url: string): string {
  const last = url.replace(/\/+$/, "").split("/").pop() ?? "";
  return last.startsWith("@") ? last : `@${last}`;
}
