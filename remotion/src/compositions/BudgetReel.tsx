import {
  AbsoluteFill,
  OffthreadVideo,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Sequence,
} from "remotion";

type Props = {
  mediaId: string;
  videoUrl: string;
  city: string;
  country: string;
  caption: string;
  pillar: string;
  hookText: string;
};

export const BudgetReel: React.FC<Props> = ({
  videoUrl,
  city,
  country,
  hookText,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const hookSlide = spring({ frame, fps, config: { damping: 10, stiffness: 80 } });
  const hookTranslateY = interpolate(hookSlide, [0, 1], [-100, 0]);
  const hookOpacity = interpolate(frame, [fps * 2 - 10, fps * 2], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const locationStart = fps * 2;
  const locationFrame = Math.max(0, frame - locationStart);
  const locationSlide = spring({ frame: locationFrame, fps, config: { damping: 12 } });
  const locationOpacity = interpolate(
    frame,
    [locationStart + fps * 3 - 10, locationStart + fps * 3],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const outroStart = durationInFrames - fps * 2;
  const outroFrame = Math.max(0, frame - outroStart);
  const outroScale = spring({ frame: outroFrame, fps, config: { damping: 8 } });

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {videoUrl && (
        <OffthreadVideo
          src={videoUrl}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      )}

      <Sequence from={0} durationInFrames={fps * 2}>
        <AbsoluteFill
          style={{
            justifyContent: "center",
            alignItems: "center",
            opacity: hookOpacity,
          }}
        >
          <div
            style={{
              color: "white",
              fontSize: 60,
              fontWeight: 800,
              textAlign: "center",
              padding: "0 50px",
              textShadow: "2px 2px 8px rgba(0,0,0,0.8)",
              transform: `translateY(${hookTranslateY}px)`,
              lineHeight: 1.2,
            }}
          >
            {hookText}
          </div>
          <div
            style={{
              color: "#FFD700",
              fontSize: 32,
              fontWeight: 600,
              marginTop: 20,
              textShadow: "1px 1px 4px rgba(0,0,0,0.6)",
              transform: `translateY(${hookTranslateY}px)`,
            }}
          >
            💰 Budget Travel
          </div>
        </AbsoluteFill>
      </Sequence>

      <Sequence from={locationStart} durationInFrames={fps * 3}>
        <AbsoluteFill
          style={{
            justifyContent: "flex-end",
            alignItems: "flex-start",
            paddingBottom: 180,
            paddingLeft: 40,
            opacity: locationOpacity,
          }}
        >
          <div
            style={{
              color: "white",
              fontSize: 44,
              fontWeight: 600,
              textShadow: "2px 2px 6px rgba(0,0,0,0.7)",
              transform: `translateX(${interpolate(locationSlide, [0, 1], [-200, 0])}px)`,
            }}
          >
            📍 {city}, {country}
          </div>
        </AbsoluteFill>
      </Sequence>

      <Sequence from={outroStart} durationInFrames={fps * 2}>
        <AbsoluteFill
          style={{
            justifyContent: "center",
            alignItems: "center",
          }}
        >
          <div
            style={{
              color: "white",
              fontSize: 44,
              fontWeight: 700,
              textAlign: "center",
              textShadow: "2px 2px 6px rgba(0,0,0,0.7)",
              transform: `scale(${outroScale})`,
            }}
          >
            Follow for more tips! ✈️
          </div>
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};
