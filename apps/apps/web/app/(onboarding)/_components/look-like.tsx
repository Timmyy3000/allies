"use client";

import { AllyLookPicker } from "@/components/ally-look-picker";
import { DEFAULT_ACCENT } from "@/components/next-button";
import {
  ALLY_COLORS,
  useOnboardingStore,
} from "../_store/onboarding-store";
import { OnboardingLayout } from "./onboarding-layout";
import { PersistentAllyAvatar } from "./persistent-ally";
import { StepHeading } from "./step-heading";

const PREVIEW_SIZE = 40;
const PREVIEW_FRAME_WIDTH = 41.06;

export function LookLikeScreen() {
  const name = useOnboardingStore((state) => state.name);
  const shape = useOnboardingStore((state) => state.shape);
  const color = useOnboardingStore((state) => state.color);
  const setShape = useOnboardingStore((state) => state.setShape);
  const markSwiped = useOnboardingStore((state) => state.markSwiped);
  const setColor = useOnboardingStore((state) => state.setColor);
  const goTo = useOnboardingStore((state) => state.goTo);
  const back = useOnboardingStore((state) => state.back);
  const accent = color ?? DEFAULT_ACCENT;

  return (
    <OnboardingLayout
      testId="look-like"
      progress={0.7}
      color={accent}
      onBack={back}
      nextActive={Boolean(color)}
      nextColor={color ?? DEFAULT_ACCENT}
      onNext={() => goTo("personality")}
    >
      <StepHeading
        lineHeight="28px"
        mark={
          <div className="onboarding-look-preview">
            <PersistentAllyAvatar
              shape={shape}
              color={color ?? undefined}
              neutral={!color}
              size={PREVIEW_SIZE}
              artworkSize="full"
              frameSize={{ width: PREVIEW_FRAME_WIDTH, height: PREVIEW_SIZE }}
              sharedLayout={false}
              layoutMode="position"
            />
          </div>
        }
      >
        How should {name.trim() || "your ally"} look?
      </StepHeading>
      <AllyLookPicker
        shape={shape}
        color={color}
        colors={ALLY_COLORS}
        dotColor={accent}
        onShapeChange={(nextShape) => {
          setShape(nextShape);
          markSwiped();
        }}
        onColorChange={setColor}
      />
    </OnboardingLayout>
  );
}
