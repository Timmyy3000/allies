"use client";

import { Artboard } from "@/components/artboard";
import { BackButton } from "@/components/back-button";
import { NextButton } from "@/components/next-button";
import { ProgressRing } from "@/components/progress-ring";
import { NAME_LIMIT, useOnboardingStore } from "../_store/onboarding-store";
import { HEADING_STYLE } from "./step-heading";

export function NameAllyScreen() {
  const name = useOnboardingStore((state) => state.name);
  const setName = useOnboardingStore((state) => state.setName);
  const goTo = useOnboardingStore((state) => state.goTo);
  const back = useOnboardingStore((state) => state.back);
  const filled = name.trim().length > 0;

  return (
    <Artboard>
      <div data-testid="name-ally" style={{ position: "absolute", inset: 0 }}>
        <BackButton onClick={back} />
        <ProgressRing progress={0.2} />
        <h1
          className="step-title"
          style={{
            ...HEADING_STYLE,
            left: 20,
            top: 88,
            width: 247,
            position: "absolute",
            letterSpacing: -0.94,
          }}
        >
          What do you want
          <br />
          to name your ally?
        </h1>
       <input
          className="onboarding-field step-stage"
          aria-label="Ally name"
         data-testid="ally-name-input"
         value={name}
         onChange={(event) => setName(event.target.value)}
          placeholder="give it a name"
          maxLength={NAME_LIMIT}
          style={{
            position: "absolute",
            left: 20,
            top: "calc(-17px + 50%)",
            width: 335,
            border: 0,
            outline: "none",
            background: "transparent",
            textAlign: "center",
            fontSize: 28,
            fontWeight: 600,
            letterSpacing: -0.92,
            lineHeight: "36px",
            color: filled ? "#ff5800" : "#d9d9d9",
          }}
        />
        <NextButton label="Next" active={filled} onClick={() => goTo("look")} />
      </div>
    </Artboard>
  );
}
