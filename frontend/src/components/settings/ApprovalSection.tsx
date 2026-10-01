import { Instagram, Youtube, Music2, Info } from "lucide-react";
import { Field } from "./Field";

const PLATFORMS = [
  { key: "instagram", label: "Instagram", Icon: Instagram, color: "text-pink-400" },
  { key: "tiktok",    label: "TikTok",    Icon: Music2,    color: "text-sky-400" },
  { key: "youtube",   label: "YouTube",   Icon: Youtube,   color: "text-red-400" },
] as const;

export function ApprovalSection({
  getValue,
  getOriginal,
  onChange,
}: {
  getValue: (key: string) => unknown;
  getOriginal: (key: string) => unknown;
  onChange: (key: string, val: unknown) => void;
}) {
  return (
    <div className="space-y-4">
      {/* Per-platform table */}
      <div>
        <p className="text-xs text-gray-500 mb-3">
          When auto-post is <span className="text-green-400 font-medium">on</span>, the daemon publishes to that platform after the delay window. When <span className="text-gray-400 font-medium">off</span>, the post stays in preview and you must approve manually.
        </p>
        <div className="overflow-hidden rounded-lg border border-gray-700">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 bg-gray-800/60">
                <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-400 w-1/3">Platform</th>
                <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-400 w-1/3">Auto-post</th>
                <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-400 w-1/3">
                  Delay (minutes)
                  <span className="ml-1 text-gray-600 font-normal">before publish</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {PLATFORMS.map(({ key, label, Icon, color }, idx) => {
                const enabledKey = `${key}_auto_enabled`;
                const minutesKey = `${key}_auto_minutes`;
                const isEnabled = getValue(enabledKey) as boolean ?? true;

                return (
                  <tr
                    key={key}
                    className={`${idx < PLATFORMS.length - 1 ? "border-b border-gray-700/60" : ""} ${
                      isEnabled ? "" : "opacity-60"
                    } transition-opacity`}
                  >
                    {/* Platform */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Icon size={15} className={color} />
                        <span className="text-white font-medium">{label}</span>
                      </div>
                    </td>

                    {/* Toggle */}
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => onChange(enabledKey, !isEnabled)}
                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                          isEnabled ? "bg-blue-600" : "bg-gray-600"
                        }`}
                        aria-label={`Toggle auto-post for ${label}`}
                      >
                        <span
                          className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
                            isEnabled ? "translate-x-4.5" : "translate-x-0.5"
                          }`}
                        />
                      </button>
                      <span className={`ml-2 text-xs ${isEnabled ? "text-green-400" : "text-gray-500"}`}>
                        {isEnabled ? "auto" : "manual"}
                      </span>
                    </td>

                    {/* Minutes input */}
                    <td className="px-4 py-3">
                      <input
                        type="number"
                        min={1}
                        max={10080}
                        disabled={!isEnabled}
                        value={(getValue(minutesKey) as number) ?? 60}
                        onChange={(e) => {
                          const v = parseInt(e.target.value, 10);
                          if (!isNaN(v) && v >= 1) onChange(minutesKey, v);
                        }}
                        className={`w-20 bg-gray-800 border rounded px-2 py-1 text-sm text-white text-center
                          focus:outline-none focus:ring-1 focus:ring-blue-500 transition-colors
                          ${
                            (getValue(minutesKey) as number) !== (getOriginal(minutesKey) as number)
                              ? "border-amber-500/60"
                              : "border-gray-600"
                          }
                          disabled:opacity-40 disabled:cursor-not-allowed`}
                      />
                      {isEnabled && (
                        <span className="ml-2 text-xs text-gray-500">
                          ≈ {Math.round(((getValue(minutesKey) as number) ?? 60) / 60 * 10) / 10}h
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Info about publish_after behaviour */}
        <div className="flex items-start gap-2 mt-2.5 text-xs text-gray-500">
          <Info size={12} className="mt-0.5 shrink-0" />
          <span>
            The publish window is set to the <em>longest</em> delay across auto-enabled platforms,
            so all auto-enabled platforms post together. Disabled platforms are skipped by the daemon —
            use the Approve button to publish them manually.
          </span>
        </div>
      </div>

      {/* require_manual_for_categories — rendered via generic Field */}
      <Field
        group="approval"
        label="require_manual_for_categories"
        value={getValue("require_manual_for_categories")}
        original={getOriginal("require_manual_for_categories")}
        onChange={(v) => onChange("require_manual_for_categories", v)}
      />
    </div>
  );
}
