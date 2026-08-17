"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { getAccentPalette } from "@/components/next-button";
import {
  JOB_LIMIT,
  PERSONALITIES,
  useOnboardingStore,
} from "../_store/onboarding-store";
import { OnboardingLayout } from "./onboarding-layout";
import { PersistentAllyAvatar } from "./persistent-ally";
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
  const palette = getAccentPalette(color);
  const [showHelp, setShowHelp] = useState(false);

  return (
    <OnboardingLayout
      testId="personality-page"
      progress={0.9}
      color={palette.accent}
      onBack={back}
      nextLabel={selected ? "Save" : "Next"}
      nextActive={selected}
      nextColor={palette.accent}
      onNext={() => goTo("preview")}
    >
      <StepHeading
        mark={
          <PersistentAllyAvatar
            shape={shape}
            state="thinking"
            color={palette.accent}
            size={40}
            sharedLayout={false}
          />
        }
      >
        What should my
        <br />
        personality be?
      </StepHeading>
      <div className="onboarding-editor-stack onboarding-personality-stack">
        <AnimatePresence initial={false} mode="wait">
          {showHelp ? (
            <motion.div
              key="personality-help"
              className="onboarding-personality-help"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            >
              <button
                type="button"
                aria-label="Close personality help"
                data-testid="personality-help-close"
                className="onboarding-personality-help-close"
                style={{ backgroundColor: "#f3f3f3" }}
                onClick={() => setShowHelp(false)}
              >
                <svg
                  aria-hidden="true"
                  width="20"
                  height="20"
                  viewBox="0 0 20 20"
                  fill="none"
                >
                  <path
                    d="m5 5 10 10M15 5 5 15"
                    stroke="#121212"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
              <div
                className="onboarding-personality-help-card"
                style={{ backgroundColor: palette.accent }}
              >
                <p>
                  My personality describes what it feels like to work with me. It
                  shapes how I speak, explain things, encourage you, challenge you,
                  and respond when something is unclear.
                </p>
                <p>
                  Describe the kind of ally you want me to be. It changes my style,
                  not my job or what I can access.
                </p>
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="personality-controls"
              className="onboarding-personality-controls"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            >
              <div
                data-testid="personality-chips"
                className="remove-scrollbar onboarding-horizontal-scroll onboarding-chip-row"
              >
                <button
                  type="button"
                  aria-label="Learn about personality"
                  data-testid="personality-help"
                  className="onboarding-personality-help-trigger"
                  style={{ backgroundColor: palette.softStrong }}
                  onClick={() => setShowHelp(true)}
                >
                  <svg
                    aria-hidden="true"
                    width="20"
                    height="20"
                    viewBox="0 0 19.33 19.33"
                    fill="none"
                  >
                    <circle cx="9.67" cy="9.67" r="9.67" fill={palette.muted} />
                    <circle
                      cx="9.67"
                      cy="9.67"
                      r="8.67"
                      stroke={palette.accent}
                      strokeWidth="2"
                    />
                    <path
                      d="M6.9 6.49C7.42 5.08 8.63 4.5 9.81 4.5 11 4.5 12.23 5.35 12.23 6.91 12.23 9.29 9.81 8.87 9.44 11"
                      stroke={palette.accent}
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <circle cx="9.39" cy="14.42" r="1.33" fill={palette.accent} />
                  </svg>
                </button>
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
                        backgroundColor: on ? palette.accent : palette.soft,
                        color: on ? "#fff" : palette.accent,
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
              <div className="step-stage onboarding-editor-card onboarding-editor-card--personality">
                <textarea
                  aria-label="Personality note"
                  data-testid="personality-note"
                  value={personalityNote}
                  onChange={(event) => setPersonalityNote(event.target.value)}
                  placeholder="How should I speak and respond to you?"
                  maxLength={JOB_LIMIT}
                  className="onboarding-editor-input"
                />
              </div>
              <p className="onboarding-editor-counter">
                {personalityNote.trim()
                  ? `${JOB_LIMIT - personalityNote.length} characters left`
                  : "200 character limit"}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </OnboardingLayout>
  );
}
