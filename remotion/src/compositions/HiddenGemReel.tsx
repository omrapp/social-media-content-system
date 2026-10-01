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

export const HiddenGemReel: React.FC<Props> = ({
  videoUrl,
  city,
  country,
  hookText,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const hookOpacity = interpolate(frame, [0, 15, fps * 2 - 15, fps * 2], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const hookScale = spring({ frame, fps, config: { damping: 12 } });

  const locationStart = fps * 2;
  const locationOpacity = interpolate(
    frame,
    [locationStart, locationStart + 15, locationStart + fps * 3 - 15, locationStart + fps * 3],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const outroStart = durationInFrames - fps * 2;
  const outroOpacity = interpolate(frame, [outroStart, outroStart + 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const kenBurnsScale = interpolate(frame, [0, durationInFrames], [1.0, 1.3], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {videoUrl && (
        <OffthreadVideo
          src={videoUrl}
          style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${kenBurnsScale})` }}
        />
      )}

      <Sequence from={0} durationInFrames={fps * 2}>
        <AbsoluteFill
          style={{
            justifyContent: "center",
            alignItems: "center",
            opacity: hookOpacity,
            transform: `scale(${hookScale})`,
          }}
        >
          <div
            style={{
              color: "white",
              fontSize: 64,
              fontWeight: 800,
              textAlign: "center",
              padding: "0 60px",
              textShadow: "2px 2px 8px rgba(0,0,0,0.8)",
              lineHeight: 1.2,
            }}
          >
            {hookText}
          </div>
        </AbsoluteFill>
      </Sequence>

      <Sequence from={locationStart} durationInFrames={fps * 3}>
        <AbsoluteFill
          style={{
            justifyContent: "flex-end",
            alignItems: "center",
            paddingBottom: 200,
            opacity: locationOpacity,
          }}
        >
          <div
            style={{
              color: "white",
              fontSize: 48,
              fontWeight: 600,
              textShadow: "2px 2px 6px rgba(0,0,0,0.7)",
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
            opacity: outroOpacity,
          }}
        >
          <div
            style={{
              color: "white",
              fontSize: 48,
              fontWeight: 700,
              textAlign: "center",
              textShadow: "2px 2px 6px rgba(0,0,0,0.7)",
            }}
          >
            Save for later ❤️
          </div>
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};
