import { Film } from "lucide-react";
import { hexToRgba } from "./BrandingSection";
import previewBg from "@/assets/preview-bg.svg";

export function BrandingPreview({ getValue }: { getValue: (key: string) => unknown }) {
  const enabled       = Boolean(getValue("overlay_enabled"));
  const handle        = String(getValue("ig_handle") || "");
  const customText    = String(getValue("custom_text") || "");
  const barH          = Number(getValue("bar_height") || 45);
  const bgColor       = String(getValue("bar_bg_color") || "#ffffff");
  const textColor     = String(getValue("text_color") || "#000000");
  const opacity       = Number(getValue("bar_opacity") ?? 1.0);
  const position      = String(getValue("bar_position") || "bottom");
  const locationSide  = String(getValue("location_side") || "left");
  const handleSide    = String(getValue("handle_side") || "right");

  const previewH = 480; // 9:16 height (width fixed at 270px in style below)
  const scaledBarH = Math.max(18, Math.round((barH / 45) * 28));

  const barBgCss = bgColor.startsWith("#") && bgColor.length === 7
    ? hexToRgba(bgColor, opacity)
    : bgColor;

  const displayLocation = "Kyoto, Japan";
  const displayHandle = handle || "";
  const displayCustom = customText || "";
  const hasCustom = displayCustom.length > 0;

  const previewFontSize = hasCustom ? "8px" : "9px";
  const previewCustomFontSize = "7px";

  return (
    <div
      aria-hidden="true"
      className="relative rounded-xl overflow-hidden border border-gray-700 mx-auto"
      style={{
        width: 270,
        height: previewH,
        backgroundImage: `url(${previewBg})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
      {/* Landscape placeholder overlay */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 opacity-20">
        <Film size={32} className="text-gray-300" />
        <div className="w-16 h-0.5 bg-gray-300 rounded" />
        <div className="w-10 h-0.5 bg-gray-300 rounded" />
      </div>

      {/* Branding bar */}
      {enabled ? (
        <div
          className="absolute left-0 right-0 px-3"
          style={{
            [position === "bottom" ? "bottom" : "top"]: 0,
            height: scaledBarH,
            backgroundColor: barBgCss,
            display: "flex",
            flexDirection: "column",
            justifyContent: hasCustom ? "flex-start" : "center",
            paddingTop: hasCustom ? 3 : 0,
          }}
        >
          {/* Main row: location + handle */}
          <div className="flex items-center w-full gap-1">
            <span
              className="truncate leading-none"
              style={{
                color: textColor,
                fontSize: previewFontSize,
                flex: locationSide === "left" ? 1 : "none",
              }}
            >
              {locationSide === "left" ? displayLocation : (handleSide === "left" ? displayHandle : "")}
            </span>
            {locationSide !== handleSide && <div className="flex-1" />}
            <span
              className="truncate leading-none text-right"
              style={{ color: textColor, fontSize: previewFontSize }}
            >
              {locationSide === "right" ? displayLocation : (handleSide === "right" ? displayHandle : "")}
            </span>
          </div>
          {/* Custom text second line */}
          {hasCustom && (
            <span
              className="truncate leading-none mt-0.5"
              style={{
                color: textColor,
                fontSize: previewCustomFontSize,
                alignSelf: locationSide === "right" ? "flex-end" : "flex-start",
              }}
            >
              {displayCustom}
            </span>
          )}
        </div>
      ) : (
        <div
          className="absolute left-0 right-0 flex items-center justify-center"
          style={{
            [position === "bottom" ? "bottom" : "top"]: 0,
            height: 22,
            backgroundColor: "rgba(0,0,0,0.4)",
          }}
        >
          <span style={{ fontSize: "8px", color: "#9ca3af" }}>overlay off</span>
        </div>
      )}
    </div>
  );
}
