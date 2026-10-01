import { Composition } from "remotion";
import { HiddenGemReel } from "./compositions/HiddenGemReel";
import { BudgetReel } from "./compositions/BudgetReel";
import { CultureReel } from "./compositions/CultureReel";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="HiddenGemReel"
        component={HiddenGemReel}
        durationInFrames={450}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          mediaId: "",
          videoUrl: "",
          city: "Chefchaouen",
          country: "Morocco",
          caption: "",
          pillar: "hidden_gem",
          hookText: "You've never seen this place before",
        }}
      />
      <Composition
        id="BudgetReel"
        component={BudgetReel}
        durationInFrames={450}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          mediaId: "",
          videoUrl: "",
          city: "Bangkok",
          country: "Thailand",
          caption: "",
          pillar: "budget",
          hookText: "Under $30/day in this city",
        }}
      />
      <Composition
        id="CultureReel"
        component={CultureReel}
        durationInFrames={540}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          mediaId: "",
          videoUrl: "",
          city: "Kyoto",
          country: "Japan",
          caption: "",
          pillar: "culture",
          hookText: "This tradition is 1000 years old",
        }}
      />
    </>
  );
};
