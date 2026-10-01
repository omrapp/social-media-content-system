import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import { execSync } from "child_process";
import { readFileSync } from "fs";

function git(cmd: string, fallback = "unknown"): string {
  try { return execSync(cmd, { encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }).trim(); }
  catch { return fallback; }
}

const pkg = JSON.parse(readFileSync(path.resolve(__dirname, "package.json"), "utf8"));
const reactVer = pkg.dependencies?.["react"] ?? "unknown";

export default defineConfig({
  define: {
    __APP_VERSION__:    JSON.stringify(pkg.version ?? "0.0.0"),
    __APP_COMMIT__:     JSON.stringify(git("git rev-parse --short HEAD")),
    __APP_BRANCH__:     JSON.stringify(git("git rev-parse --abbrev-ref HEAD")),
    __APP_TAG__:        JSON.stringify(git("git describe --tags --abbrev=0", "")),
    __APP_BUILD_TIME__: JSON.stringify(new Date().toISOString()),
    __REACT_VERSION__:  JSON.stringify(reactVer),
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/static": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
