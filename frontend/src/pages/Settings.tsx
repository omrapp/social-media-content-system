import { useEffect, useState } from "react";
import {
  Save, AlertCircle, CheckCircle2, ChevronDown, ChevronUp,
} from "lucide-react";
import { useSettings, type SettingsGroup } from "@/lib/settings";
import { api } from "@/lib/api";
import {
  GROUP_META, GROUP_ORDER, ACCENT_CLASSES, FIELD_HINTS,
  SecretsStatus, DeploymentCard, ApprovalSection, Field, TimeSlotField,
  type VersionInfo,
} from "@/components/settings";

export function SettingsPage() {
  const { data, loading, error, saving, save } = useSettings();
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [savedFlash, setSavedFlash] = useState<string | null>(null);
  const [versionInfo, setVersionInfo] = useState<VersionInfo | null>(null);

  useEffect(() => {
    if (data) setDrafts({});
  }, [data]);

  useEffect(() => {
    api.get<VersionInfo>("/version").then(setVersionInfo).catch(() => null);
  }, []);

  if (loading && !data) {
    return (
      <div className="flex items-center gap-3 text-gray-400 text-sm p-4">
        <div className="w-4 h-4 border-2 border-gray-600 border-t-blue-500 rounded-full animate-spin" />
        Loading settings…
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-950/40 border border-red-900 text-red-300 text-sm rounded-xl p-4 flex items-center gap-2">
        <AlertCircle size={16} />
        {error}
      </div>
    );
  }

  if (!data) return null;

  const setDraft = (group: string, key: string, value: unknown) => {
    setDrafts((prev) => ({
      ...prev,
      [group]: { ...(prev[group] ?? {}), [key]: value },
    }));
  };

  const currentValue = (group: string, key: string): unknown => {
    const draft = drafts[group]?.[key];
    if (draft !== undefined) return draft;
    return data.settings[group]?.[key];
  };

  const onSave = async (group: string) => {
    const patch = drafts[group];
    if (!patch || Object.keys(patch).length === 0) return;
    await save(group as SettingsGroup, patch);
    setDrafts((prev) => ({ ...prev, [group]: {} }));
    setSavedFlash(group);
    setTimeout(() => setSavedFlash(null), 2000);
  };

  const toggleCollapse = (group: string) => {
    setCollapsed((prev) => ({ ...prev, [group]: !prev[group] }));
  };

  const visibleGroups = GROUP_ORDER.filter((g) => data.settings[g] !== undefined);

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold text-white">Settings</h2>
        <p className="text-sm text-gray-500 mt-1">
          Runtime configuration. Secrets stay in <code className="text-gray-400 bg-gray-800 px-1 rounded">.env</code> — only their presence is shown below.
        </p>
      </div>

      <SecretsStatus secrets={data.secrets_set} />

      <DeploymentCard versionInfo={versionInfo} />

      {visibleGroups.map((group) => {
        const meta = GROUP_META[group];
        if (!meta) return null;
        const value = data.settings[group] ?? {};
        const dirty = drafts[group] && Object.keys(drafts[group] ?? {}).length > 0;
        const isCollapsed = collapsed[group];
        const accent = ACCENT_CLASSES[meta.accent] ?? ACCENT_CLASSES.blue;
        const Icon = meta.icon;
        const isSaved = savedFlash === group;

        return (
          <section
            key={group}
            className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden transition-all"
          >
            <header
              className="flex items-center gap-4 px-5 py-4 cursor-pointer select-none hover:bg-gray-800/40 transition-colors"
              onClick={() => toggleCollapse(group)}
            >
              <div className={`p-2 rounded-lg ring-1 ${accent.ring}`}>
                <Icon size={16} className={accent.icon} />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-sm font-semibold text-white">{meta.label}</h3>
                <p className="text-xs text-gray-500 mt-0.5 truncate">{meta.help}</p>
              </div>
              <div className="flex items-center gap-2">
                {dirty && !isCollapsed && (
                  <span className="text-xs text-amber-400 font-medium px-2 py-0.5 bg-amber-400/10 rounded-full">
                    unsaved
                  </span>
                )}
                {isCollapsed ? <ChevronDown size={14} className="text-gray-500" /> : <ChevronUp size={14} className="text-gray-500" />}
              </div>
            </header>

            {!isCollapsed && (
              <div className="border-t border-gray-800 px-5 py-4 space-y-4">
                <div className="space-y-3">
                  {group === "approval" ? (
                    <ApprovalSection
                      getValue={(key) => currentValue(group, key)}
                      getOriginal={(key) => (data.settings[group] ?? {})[key as string]}
                      onChange={(key, val) => setDraft(group, key, val)}
                    />
                  ) : (
                    Object.entries(value).map(([key, val]) => {
                      if (group === "schedule" && key === "daily_slots") {
                        return (
                          <TimeSlotField
                            key={key}
                            value={currentValue(group, key)}
                            original={val}
                            hint={FIELD_HINTS[`${group}.${key}`]}
                            onChange={(next) => setDraft(group, key, next)}
                          />
                        );
                      }
                      return (
                        <Field
                          key={key}
                          group={group}
                          label={key}
                          value={currentValue(group, key)}
                          original={val}
                          onChange={(next) => setDraft(group, key, next)}
                        />
                      );
                    })
                  )}
                </div>
                <div className="flex justify-end pt-2 border-t border-gray-800/50">
                  <button
                    onClick={() => onSave(group)}
                    disabled={!dirty || saving === group}
                    className={`flex items-center gap-2 px-4 py-2 text-sm rounded-lg font-medium transition-all ${
                      isSaved
                        ? "bg-green-600/20 text-green-400 ring-1 ring-green-500/30"
                        : dirty
                        ? "bg-blue-600 hover:bg-blue-700 text-white"
                        : "bg-gray-800 text-gray-500 cursor-not-allowed"
                    }`}
                  >
                    {isSaved ? (
                      <><CheckCircle2 size={14} /> Saved</>
                    ) : saving === group ? (
                      <><div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Saving…</>
                    ) : (
                      <><Save size={14} /> Save {meta.label}</>
                    )}
                  </button>
                </div>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
