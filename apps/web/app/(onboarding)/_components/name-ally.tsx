"use client";

import { NAME_LIMIT, useOnboardingStore } from "../_store/onboarding-store";
import { OnboardingLayout } from "./onboarding-layout";
import { StepHeading } from "./step-heading";

export function NameAllyScreen({ onBack }: { onBack?: () => void }) {
  const name = useOnboardingStore((state) => state.name);
  const setName = useOnboardingStore((state) => state.setName);
  const goTo = useOnboardingStore((state) => state.goTo);
  const back = useOnboardingStore((state) => state.back);
  const filled = name.trim().length > 0;

  return (
    <OnboardingLayout
      testId="name-ally"
      progress={0.2}
      onBack={onBack ?? back}
      nextActive={filled}
      onNext={() => goTo("look")}
    >
      <StepHeading>
        What do you want
        <br />
        to name your ally?
      </StepHeading>
      <div className="onboarding-name-input-area">
        <input
          className="onboarding-field"
          aria-label="Ally name"
          data-testid="ally-name-input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="give it a name"
          maxLength={NAME_LIMIT}
          style={{
            width: "100%",
            border: 0,
            outline: "none",
            background: "transparent",
            padding: 0,
            textAlign: "center",
            fontFamily: "var(--font-open-runde), sans-serif",
            fontSize: 28,
            fontWeight: 600,
            letterSpacing: -1,
            lineHeight: "100%",
            color: filled ? "#ff5800" : "#d9d9d9",
          }}
        />
      </div>
    </OnboardingLayout>
  );
}
