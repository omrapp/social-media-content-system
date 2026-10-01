// Demo mode (VITE_DEMO_MODE=true): the UI runs with no backend and no Supabase.
// A fetch interceptor answers every /api/* call from in-memory fixtures, auth is
// faked and the WebSocket is skipped. Powers the GitHub Pages live preview and
// the README screenshots.
export const IS_DEMO = import.meta.env.VITE_DEMO_MODE === "true";

/** Prefix a public/ asset with the deploy base (e.g. GitHub Pages sub-path). */
export const demoAsset = (p: string) => `${import.meta.env.BASE_URL}demo/${p}`;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body ?? {}), {
    status,
    headers: { "Content-Type": "application/json" },
  });

/** First path segments of the backend API, for when the base URL is empty. */
const API_ROOTS =
  /^\/(health|version|settings|taxonomy|series|media|posts|captions|analytics|statistics|classification|notifications|pipeline|scheduler|downloads|assets|audio|editor|edit)(\/|$)/;

export function installDemoFetch() {
  // Lazy chunk: fixtures are only downloaded when demo mode is on.
  const handlers = import("./handlers");
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    const i = url.pathname.indexOf("/api/");
    let path: string;
    if (i !== -1) {
      path = url.pathname.slice(i + 4); // keep leading "/"
    } else if (url.origin === window.location.origin && API_ROOTS.test(url.pathname)) {
      // An empty VITE_API_BASE_URL drops the /api prefix from request paths.
      path = url.pathname;
    } else {
      return realFetch(input, init);
    }

    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = undefined;
    if (typeof init?.body === "string") {
      try { body = JSON.parse(init.body); } catch { body = init.body; }
    }
    // Small latency so loading states look real.
    await new Promise((r) => setTimeout(r, 120));
    const { handleDemoRequest } = await handlers;
    const result = handleDemoRequest(method, path, url.searchParams, body);
    return result === undefined ? json({ detail: "Not available in demo" }, 404) : json(result);
  };
}
