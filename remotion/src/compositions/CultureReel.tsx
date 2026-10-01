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

export const CultureReel: React.FC<Props> = ({
  videoUrl,
  city,
  country,
  hookText,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const hookFade = interpolate(frame, [0, 20, fps * 3 - 20, fps * 3], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const hookLetterSpacing = interpolate(frame, [0, fps], [10, 0], {
    extrapolateRight: "clamp",
  });

  const locationStart = fps * 3;
  const locationFrame = Math.max(0, frame - locationStart);
  const locationSpring = spring({ frame: locationFrame, fps, config: { damping: 14 } });
  const locationOpacity = interpolate(
    frame,
    [locationStart + fps * 4 - 15, locationStart + fps * 4],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const outroStart = durationInFrames - fps * 2;
  const outroOpacity = interpolate(frame, [outroStart, outroStart + 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const kenBurnsScale = interpolate(frame, [0, durationInFrames], [1.0, 1.2], {
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

      <AbsoluteFill
        style={{
          background: "linear-gradient(to bottom, rgba(0,0,0,0.4) 0%, transparent 30%, transparent 70%, rgba(0,0,0,0.5) 100%)",
        }}
      />

      <Sequence from={0} durationInFrames={fps * 3}>
        <AbsoluteFill
          style={{
            justifyContent: "center",
            alignItems: "center",
            opacity: hookFade,
          }}
        >
          <div
            style={{
              color: "white",
              fontSize: 56,
              fontWeight: 700,
              textAlign: "center",
              padding: "0 50px",
              textShadow: "2px 2px 10px rgba(0,0,0,0.9)",
              letterSpacing: hookLetterSpacing,
              lineHeight: 1.3,
              fontStyle: "italic",
            }}
          >
            {hookText}
          </div>
          <div
            style={{
              width: 60,
              height: 3,
              backgroundColor: "#C9A961",
              marginTop: 20,
              opacity: hookFade,
            }}
          />
        </AbsoluteFill>
      </Sequence>

      <Sequence from={locationStart} durationInFrames={fps * 4}>
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
              fontSize: 42,
              fontWeight: 500,
              textShadow: "2px 2px 8px rgba(0,0,0,0.8)",
              transform: `scale(${locationSpring})`,
              letterSpacing: 2,
            }}
          >
            🏛️ {city}, {country}
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
              fontSize: 40,
              fontWeight: 600,
              textAlign: "center",
              textShadow: "2px 2px 8px rgba(0,0,0,0.8)",
              letterSpacing: 1,
            }}
          >
            Share this with someone who loves culture
          </div>
          <div
            style={{
              width: 40,
              height: 2,
              backgroundColor: "#C9A961",
              marginTop: 16,
            }}
          />
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};
