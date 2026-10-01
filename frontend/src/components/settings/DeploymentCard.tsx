import { Terminal, GitBranch, Package, RefreshCw } from "lucide-react";
import type { VersionInfo } from "./types";

declare const __APP_VERSION__: string;
declare const __APP_COMMIT__: string;
declare const __APP_BRANCH__: string;
declare const __APP_TAG__: string;
declare const __APP_BUILD_TIME__: string;
declare const __REACT_VERSION__: string;

export function DeploymentCard({ versionInfo }: { versionInfo: VersionInfo | null }) {
  const fe = {
    version: __APP_VERSION__,
    commit:  __APP_COMMIT__,
    branch:  __APP_BRANCH__,
    tag:     __APP_TAG__,
    built:   __APP_BUILD_TIME__,
    react:   __REACT_VERSION__,
  };

  const badge = (label: string, val: string, mono = false) => (
    <div key={label} className="flex items-center justify-between py-0.5">
      <span className="text-xs text-gray-500">{label}</span>
      <span className={`text-xs ${mono ? "font-mono" : ""} text-gray-300`}>{val || "—"}</span>
    </div>
  );

  const formatBuildTime = (iso: string) => {
    if (!iso || iso === "unknown") return "unknown";
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  };

  return (
    <section className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="flex items-center gap-4 px-5 py-4 border-b border-gray-800">
        <div className="p-2 rounded-lg ring-1 ring-gray-500/20 bg-gray-500/10">
          <Terminal size={16} className="text-gray-400" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-white">Deployment</h3>
          <p className="text-xs text-gray-500 mt-0.5">Build info, git refs, and runtime versions.</p>
        </div>
        {!versionInfo && (
          <div className="w-3.5 h-3.5 border-2 border-gray-600 border-t-gray-400 rounded-full animate-spin" />
        )}
      </div>

      <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-3 gap-5">
        {/* Frontend */}
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <Package size={12} className="text-blue-400" />
            <span className="text-xs font-semibold text-blue-400 uppercase tracking-wide">Frontend</span>
          </div>
          <div className="space-y-0.5">
            {badge("version", fe.tag || `v${fe.version}`)}
            {badge("commit", fe.commit, true)}
            {badge("branch", fe.branch, true)}
            {badge("built", formatBuildTime(fe.built))}
            {badge("react", fe.react, true)}
          </div>
        </div>

        {/* Backend */}
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <GitBranch size={12} className="text-purple-400" />
            <span className="text-xs font-semibold text-purple-400 uppercase tracking-wide">Backend</span>
          </div>
          {versionInfo ? (
            <div className="space-y-0.5">
              {badge("tag", versionInfo.backend.tag)}
              {badge("commit", versionInfo.backend.commit, true)}
              {badge("branch", versionInfo.backend.branch, true)}
              {badge("built", formatBuildTime(versionInfo.backend.build_time))}
            </div>
          ) : (
            <p className="text-xs text-gray-600">Loading…</p>
          )}
        </div>

        {/* Runtime */}
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <RefreshCw size={12} className="text-emerald-400" />
            <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wide">Runtime</span>
          </div>
          {versionInfo?.runtime ? (
            <div className="space-y-0.5">
              {badge("python", versionInfo.runtime.python, true)}
              {badge("fastapi", versionInfo.runtime.fastapi, true)}
              {badge("uvicorn", versionInfo.runtime.uvicorn, true)}
              {badge("supabase", versionInfo.runtime.supabase, true)}
              {badge("openrouter", versionInfo.runtime.openrouter, true)}
              {badge("groq", versionInfo.runtime.groq, true)}
            </div>
          ) : versionInfo ? (
            <p className="text-xs text-gray-600">Not available.</p>
          ) : (
            <p className="text-xs text-gray-600">Loading…</p>
          )}
        </div>
      </div>
    </section>
  );
}
