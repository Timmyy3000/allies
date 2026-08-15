"use client";

import { Artboard } from "@/components/artboard";
import { AllyAvatar } from "@/components/ally-avatar";
import { BackButton } from "@/components/back-button";
import { DEFAULT_ACCENT, NextButton } from "@/components/next-button";
import { ProgressRing } from "@/components/progress-ring";
import {
  JOB_LIMIT,
  PERSONALITIES,
  useOnboardingStore,
} from "../_store/onboarding-store";
import { StepHeading } from "./step-heading";

export function PersonalityScreen() {
  const personalities = useOnboardingStore((state) => state.personalities);
  const personalityNote = useOnboardingStore((state) => state.personalityNote);
  const shape = useOnboardingStore((state) => state.shape);
  const color = useOnboardingStore((state) => state.color);
 const togglePersonality = useOnboardingStore((state) => state.togglePersonality);
  const setPersonalityNote = useOnboardingStore((state) => state.setPersonalityNote);
 const goTo = useOnboardingStore((state) => state.goTo);
  const back = useOnboardingStore((state) => state.back);
  const selected = personalities.length > 0 || personalityNote.trim().length > 0;

  return (
    <Artboard>
      <div data-testid="personality-page" style={{ position: "absolute", inset: 0 }}>
        <BackButton onClick={back} />
        <ProgressRing progress={0.9} />
        <StepHeading
          mark={
            <AllyAvatar
              shape={shape}
              state="thinking"
              color={color ?? "#fd304f"}
              size={40}
            />
          }
        >
          What should my
          <br />
          personality be?
        </StepHeading>
        <div
          data-testid="personality-chips"
          className="remove-scrollbar"
          style={{
            left: 0,
            bottom: 388,
            width: 375,
            position: "absolute",
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            columnGap: 12,
            overflowX: "auto",
            paddingLeft: 20,
            paddingRight: 20,
          }}
        >
          <div
            aria-hidden
            style={{
              borderRadius: 100,
              backgroundColor: "#f3f3f3",
              width: 36,
              height: 36,
              flexShrink: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg width="20" height="20" viewBox="0 0 19.33 19.33" fill="none">
              <circle cx="9.67" cy="9.67" r="9.67" fill="rgba(255,45,85,0.4)" />
              <circle
                cx="9.67"
                cy="9.67"
                r="8.67"
                stroke="#ff2d55"
                strokeWidth="2"
              />
              <path
                d="M6.9 6.49C7.42 5.08 8.63 4.5 9.81 4.5 11 4.5 12.23 5.35 12.23 6.91 12.23 9.29 9.81 8.87 9.44 11"
                stroke="#ff2d55"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <circle cx="9.39" cy="14.42" r="1.33" fill="#ff2d55" />
            </svg>
          </div>
          {PERSONALITIES.map((trait) => {
            const on = personalities.includes(trait);
            return (
             <button
                key={trait}
                type="button"
               data-testid={`trait-${trait}`}
               onClick={() => togglePersonality(trait)}
               aria-pressed={on}
                className="onboarding-chip"
                data-selected={on ? "true" : "false"}
                style={{
                  borderRadius: 100,
                  backgroundColor: on ? "#ff2d55" : "rgba(255,45,85,0.1)",
                  color: on ? "#fff" : "#ff2d55",
                  border: 0,
                  height: 36,
                  padding: "8px 24px",
                  fontSize: 16,
                  fontWeight: 600,
                  letterSpacing: -0.43,
                  lineHeight: "20px",
                  flexShrink: 0,
                  cursor: "pointer",
                }}
              >
                {trait}
              </button>
            );
          })}
        </div>
        <div
          className="step-stage"
          style={{
            borderRadius: 20,
            backgroundColor: "#f3f3f3",
            left: 20,
            bottom: 126,
            width: 335,
            height: 250,
            position: "absolute",
            overflow: "hidden",
          }}
         >
          <textarea
            aria-label="Personality note"
           data-testid="personality-note"
            value={personalityNote}
            onChange={(event) => setPersonalityNote(event.target.value)}
            placeholder="What do I handle for you?"
            maxLength={JOB_LIMIT}
            style={{
              position: "absolute",
              left: 14,
              top: 18,
              right: 14,
              bottom: 14,
              border: 0,
              resize: "none",
              outline: "none",
              background: "transparent",
              fontSize: 16,
              fontWeight: 600,
              letterSpacing: -0.48,
              lineHeight: "22px",
              color: "#121212",
            }}
          />
        </div>
        <p
          style={{
            left: "50%",
            bottom: 90,
            transform: "translateX(-50%)",
            position: "absolute",
            margin: 0,
            fontSize: 14,
            fontWeight: 600,
            letterSpacing: -0.48,
            lineHeight: "18px",
            color: "#121212",
            width: "max-content",
            textAlign: "center",
          }}
        >
          {personalityNote.trim()
            ? `${JOB_LIMIT - personalityNote.length} characters left`
            : "200 character limit"}
        </p>
        <NextButton
         label="Next"
          active={selected}
          color={color ?? DEFAULT_ACCENT}
          onClick={() => goTo("preview")}
        />
      </div>
    </Artboard>
  );
}
