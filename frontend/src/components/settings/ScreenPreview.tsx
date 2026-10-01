import { useRef } from "react";
import type { CSSProperties } from "react";
import previewBg from "@/assets/preview-bg.svg";
import { hexToRgba } from "./BrandingSection";

const ALLOWED_ANIMATIONS = new Set([
  "none", "fade", "zoom", "slide", "blur", "wipe", "ken_burns", "random",
]);

// Animations shown in the Design preview when "random" is selected — excludes
// zoom/ken_burns to keep the preview snappy (they're still used by the pipeline).
const RANDOM_PREVIEW_POOL = ["fade", "slide", "blur", "wipe"] as const;

export interface PreviewElementDef {
  id: string;
  enabledKey: string;
  textKey?: string;
  colorKey: string;
  fontSizeKey: string;
  orderKey: string;
  defaultFontSize: number;
  bottomPaddingKey?: string;
}

interface ScreenPreviewProps {
  kind: "intro" | "cast";
  elements: PreviewElementDef[];
  previewLabels: Record<string, string>;
  getValue: (key: string) => unknown;
}

const ANIM_ID_PREFIX = "screen-preview-anim-";

export function ScreenPreview({ kind, elements, previewLabels, getValue }: ScreenPreviewProps) {
  const bgColor   = String(getValue("bg_color") || "#000000");
  const bgOpacity = Number(getValue("bg_opacity") ?? 0.20);
  const animation = String(getValue("animation") || "fade");
  const duration  = Number(getValue("duration_s") ?? 2.0);
  const textPad   = Number(getValue("text_padding_h") ?? 40);

  // Pick a stable random animation once per mount
  const randomPick = useRef(
    RANDOM_PREVIEW_POOL[Math.floor(Math.random() * RANDOM_PREVIEW_POOL.length)],
  );

  const previewW = 270;
  const previewH = 480; // 9:16

  const scaledPad = Math.round((textPad / 1920) * previewW * 1.5);

  const rawAnim = ALLOWED_ANIMATIONS.has(animation) ? animation : "none";
  const safeAnimation = rawAnim === "random" ? randomPick.current : rawAnim;
  const isRandom = rawAnim === "random";

  const bgCss = hexToRgba(bgColor, bgOpacity);

  const sortedElements = [...elements]
    .sort(
      (a, b) =>
        Number(getValue(a.orderKey) ?? elements.indexOf(a)) -
        Number(getValue(b.orderKey) ?? elements.indexOf(b))
    )
    .filter((el) => Boolean(getValue(el.enabledKey) ?? true));

  const animId = `${ANIM_ID_PREFIX}${kind}`;
  const dur = duration * 2; // loop period in CSS (double so hold is visible)
  let keyframes = "";
  let animationStyle: CSSProperties = {};

  if (safeAnimation === "fade") {
    keyframes = `
      @keyframes ${animId} {
        0%   { opacity: 0; }
        20%  { opacity: 1; }
        80%  { opacity: 1; }
        100% { opacity: 0; }
      }
    `;
    animationStyle = { animation: `${animId} ${dur}s ease-in-out infinite` };

  } else if (safeAnimation === "zoom") {
    keyframes = `
      @keyframes ${animId} {
        0%   { transform: scale(1);    opacity: 0; }
        15%  { transform: scale(1.02); opacity: 1; }
        85%  { transform: scale(1.08); opacity: 1; }
        100% { transform: scale(1.06); opacity: 0; }
      }
    `;
    animationStyle = { animation: `${animId} ${dur}s ease-in-out infinite` };

  } else if (safeAnimation === "slide") {
    keyframes = `
      @keyframes ${animId} {
        0%   { transform: translateY(100%); opacity: 0; }
        20%  { transform: translateY(0);    opacity: 1; }
        80%  { transform: translateY(0);    opacity: 1; }
        100% { transform: translateY(100%); opacity: 0; }
      }
    `;
    animationStyle = { animation: `${animId} ${dur}s ease-in-out infinite` };

  } else if (safeAnimation === "blur") {
    keyframes = `
      @keyframes ${animId} {
        0%   { filter: blur(12px); opacity: 0; }
        20%  { filter: blur(0px);  opacity: 1; }
        80%  { filter: blur(0px);  opacity: 1; }
        100% { filter: blur(12px); opacity: 0; }
      }
    `;
    animationStyle = { animation: `${animId} ${dur}s ease-in-out infinite` };

  } else if (safeAnimation === "wipe") {
    keyframes = `
      @keyframes ${animId} {
        0%   { clip-path: inset(0 100% 0 0); }
        20%  { clip-path: inset(0 0%   0 0); }
        80%  { clip-path: inset(0 0%   0 0); }
        100% { clip-path: inset(0 100% 0 0); }
      }
    `;
    animationStyle = { animation: `${animId} ${dur}s ease-in-out infinite` };

  } else if (safeAnimation === "ken_burns") {
    keyframes = `
      @keyframes ${animId} {
        0%   { transform: scale(1)    translate(0,    0);    opacity: 0; }
        15%  { transform: scale(1.02) translate(-1%, -0.5%); opacity: 1; }
        85%  { transform: scale(1.10) translate(-3%, -1.5%); opacity: 1; }
        100% { transform: scale(1.08) translate(-2%, -1%);   opacity: 0; }
      }
    `;
    animationStyle = { animation: `${animId} ${dur}s ease-in-out infinite` };
  }

  const label = kind === "intro" ? "Intro" : "Cast";

  return (
    <div className="space-y-2">
      {keyframes && (
        <style dangerouslySetInnerHTML={{ __html: keyframes }} />
      )}

      <div
        aria-hidden="true"
        className="relative rounded-xl overflow-hidden border border-gray-700 mx-auto"
        style={{
          width: previewW,
          height: previewH,
          backgroundImage: `url(${previewBg})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        {/* Colour overlay */}
        <div className="absolute inset-0" style={{ background: bgCss }} />

        {/* Text container — animated */}
        <div
          className="absolute inset-0 flex flex-col items-center justify-center"
          style={{ padding: `0 ${scaledPad}px`, ...animationStyle }}
        >
          {sortedElements.length === 0 ? (
            <span style={{ fontSize: "10px", color: "#ffffff", opacity: 0.3 }}>
              {label.toLowerCase()}
            </span>
          ) : (
            sortedElements.map((el) => {
              const color     = String(getValue(el.colorKey) || "#ffffff");
              const fs        = Number(getValue(el.fontSizeKey) || el.defaultFontSize);
              const previewFs = Math.max(7, Math.round((fs / 1920) * 480 * 1.5));
              const bottomPad = el.bottomPaddingKey
                ? Math.round((Number(getValue(el.bottomPaddingKey) ?? 0) / 1920) * 480 * 1.5)
                : 0;
              const rawText = el.textKey
                ? String(getValue(el.textKey) || "") || previewLabels[el.id] || el.id
                : previewLabels[el.id] || el.id;
              const lines = rawText.split("\n");

              return (
                <div
                  key={el.id}
                  className="text-center w-full"
                  style={{ marginBottom: bottomPad }}
                >
                  {lines.map((line, i) => (
                    <span
                      key={i}
                      className="leading-snug"
                      style={{ display: "block", color, fontSize: `${previewFs}px` }}
                    >
                      {line || " "}
                    </span>
                  ))}
                </div>
              );
            })
          )}
        </div>

        {/* Footer labels */}
        <div className="absolute bottom-2 left-0 right-0 flex justify-center gap-1.5">
          <span
            className="bg-black/50 rounded px-1.5 py-0.5"
            style={{ fontSize: "8px", color: "#ffffff", opacity: 0.7 }}
          >
            {label}
          </span>
          {rawAnim !== "none" && (
            <span
              className="bg-black/50 rounded px-1.5 py-0.5"
              style={{ fontSize: "8px", color: "#ffffff", opacity: 0.7 }}
            >
              {isRandom ? `random → ${safeAnimation}` : safeAnimation}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
