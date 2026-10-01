import { useState } from "react";
import { useSettings, type SettingsGroup } from "@/lib/settings";
import { AlertCircle } from "lucide-react";
import { BrandingSection, ColorGradeSection } from "@/components/settings";
import { IntroSection, INTRO_ELEMENTS, PREVIEW_LABELS as INTRO_PREVIEW_LABELS } from "@/components/settings/IntroSection";
import { CastSection, CAST_ELEMENTS, CAST_PREVIEW_LABELS } from "@/components/settings/CastSection";
import { ScreenPreview } from "@/components/settings/ScreenPreview";
import { BrandingPreview } from "@/components/settings/BrandingPreview";

type Tab = "branding" | "intro" | "cast" | "color";

const TABS: { id: Tab; label: string }[] = [
  { id: "branding", label: "Video Branding" },
  { id: "intro",    label: "Intro Screen" },
  { id: "cast",     label: "Cast Screen" },
  { id: "color",    label: "Color Grade" },
];

export function DesignPage() {
  const { data, loading, error, save } = useSettings();
  const [activeTab, setActiveTab] = useState<Tab>("branding");
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});

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

  function currentValue(group: string, key: string): unknown {
    const draft = drafts[group]?.[key];
    if (draft !== undefined) return draft;
    return (data!.settings[group] ?? {})[key];
  }

  function setDraft(group: string, key: string, val: unknown) {
    setDrafts((prev) => ({ ...prev, [group]: { ...(prev[group] ?? {}), [key]: val } }));
  }

  async function onSave(group: string) {
    const patch = drafts[group];
    if (!patch || Object.keys(patch).length === 0) return;
    await save(group as SettingsGroup, patch);
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[group];
      return next;
    });
  }

  const hasDraft = (group: string) =>
    Boolean(drafts[group] && Object.keys(drafts[group]).length > 0);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Design</h2>
          <p className="text-sm text-gray-500 mt-1">Video branding, intro and cast screens</p>
        </div>
        {hasDraft(activeTab) && (
          <button
            onClick={() => onSave(activeTab)}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Save {TABS.find((t) => t.id === activeTab)?.label}
          </button>
        )}
      </div>

      {/* Tab strip */}
      <div className="flex gap-1 border-b border-gray-800">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors border-b-2 -mb-px ${
              activeTab === tab.id
                ? "border-blue-500 text-blue-400 bg-gray-800/50"
                : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-gray-800/30"
            }`}
          >
            {tab.label}
            {hasDraft(tab.id) && (
              <span className="ml-1.5 w-1.5 h-1.5 rounded-full bg-amber-400 inline-block align-middle" />
            )}
          </button>
        ))}
      </div>

      {/* Two-column grid: controls left, sticky preview right */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
        {/* Left: controls */}
        <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-6">
          {activeTab === "branding" && (
            <BrandingSection
              getValue={(k) => currentValue("branding", k)}
              getOriginal={(k) => (data.settings["branding"] ?? {})[k]}
              onChange={(k, v) => setDraft("branding", k, v)}
            />
          )}
          {activeTab === "intro" && (
            <IntroSection
              getValue={(k) => currentValue("intro", k)}
              getOriginal={(k) => (data.settings["intro"] ?? {})[k]}
              onChange={(k, v) => setDraft("intro", k, v)}
            />
          )}
          {activeTab === "cast" && (
            <CastSection
              getValue={(k) => currentValue("cast", k)}
              getOriginal={(k) => (data.settings["cast"] ?? {})[k]}
              onChange={(k, v) => setDraft("cast", k, v)}
            />
          )}
          {activeTab === "color" && (
            <ColorGradeSection
              getValue={(k) => currentValue("color", k)}
              getOriginal={(k) => (data.settings["color"] ?? {})[k]}
              onChange={(k, v) => setDraft("color", k, v)}
            />
          )}
        </div>

        {/* Right: sticky live preview */}
        <div className="lg:sticky lg:top-6 space-y-3">
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Live Preview</p>
          {activeTab === "branding" && (
            <BrandingPreview getValue={(k) => currentValue("branding", k)} />
          )}
          {activeTab === "intro" && (
            <ScreenPreview
              kind="intro"
              elements={INTRO_ELEMENTS}
              previewLabels={INTRO_PREVIEW_LABELS}
              getValue={(k) => currentValue("intro", k)}
            />
          )}
          {activeTab === "cast" && (
            <ScreenPreview
              kind="cast"
              elements={CAST_ELEMENTS}
              previewLabels={CAST_PREVIEW_LABELS}
              getValue={(k) => currentValue("cast", k)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
