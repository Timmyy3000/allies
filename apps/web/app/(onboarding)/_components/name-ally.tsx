"use client";

import { useRef } from "react";

import { useCreationWake } from "../../../lib/allies/authenticated-onboarding-flow";
import { NAME_LIMIT, useOnboardingStore } from "../_store/onboarding-store";
import { OnboardingLayout } from "./onboarding-layout";
import { StepHeading } from "./step-heading";

export function NameAllyScreen({ onBack }: { onBack?: () => void }) {
  const name = useOnboardingStore((state) => state.name);
  const setName = useOnboardingStore((state) => state.setName);
  const goTo = useOnboardingStore((state) => state.goTo);
  const back = useOnboardingStore((state) => state.back);
  const creationWake = useCreationWake();
  const composingRef = useRef(false);
  const filled = name.trim().length > 0;

  const commitNameEdit = (value: string) => {
    setName(value);
    if (!composingRef.current && value.trim()) void creationWake?.requestCreationWake(value);
  };

  return (
    <OnboardingLayout
      testId="name-ally"
      progress={0.5}
      onBack={onBack ?? back}
      nextActive={filled}
      onNext={() => goTo("look")}
    >
      <StepHeading>
        Let’s give your
        <br />
        ally a name.
      </StepHeading>
      <div className="onboarding-name-input-area">
        <input
          className="onboarding-field"
          aria-label="Ally name"
          placeholder="Samantha"
          data-testid="ally-name-input"
          value={name}
          onChange={(event) => commitNameEdit(event.currentTarget.value)}
          onCompositionStart={() => { composingRef.current = true; }}
          onCompositionEnd={(event) => {
            composingRef.current = false;
            commitNameEdit(event.currentTarget.value);
          }}
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
            color: filled ? "#ff5800" : "var(--text-muted)",
          }}
        />
      </div>
    </OnboardingLayout>
  );
}
