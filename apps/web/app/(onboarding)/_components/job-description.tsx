"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { DEFAULT_ACCENT, getAccentPalette } from "@/components/next-button";
import {
  JOB_LIMIT,
  JOB_SUGGESTIONS,
  useOnboardingStore,
} from "../_store/onboarding-store";
import {
  OnboardingHelpTrigger,
  useOnboardingHelpFocus,
} from "./onboarding-help";
import { OnboardingLayout } from "./onboarding-layout";
import { PersistentAllyAvatar } from "./persistent-ally";
import { StepHeading } from "./step-heading";

export function JobDescriptionScreen() {
  const job = useOnboardingStore((state) => state.job);
  const shape = useOnboardingStore((state) => state.shape);
  const color = useOnboardingStore((state) => state.color);
  const setJob = useOnboardingStore((state) => state.setJob);
  const goTo = useOnboardingStore((state) => state.goTo);
  const back = useOnboardingStore((state) => state.back);
  const accent = color ?? DEFAULT_ACCENT;
  const palette = getAccentPalette(color);
  const filled = job.trim().length > 0;
  const remaining = JOB_LIMIT - job.length;
  const [showHelp, setShowHelp] = useState(false);
  const { triggerRef, closeRef, requestRestoreFocus, onExitComplete } =
    useOnboardingHelpFocus();

  return (
    <OnboardingLayout
      testId="job-description"
      progress={0.7}
      color={accent}
      onBack={back}
      nextActive={filled}
      nextColor={accent}
      onNext={() => goTo("personality")}
    >
      <StepHeading
        mark={
          <PersistentAllyAvatar
            shape={shape}
            state="thinking"
            color={accent}
            size={40}
            sharedLayout={false}
          />
        }
      >
        What is my
        <br />
        job description?
      </StepHeading>
      <div className="onboarding-editor-stack onboarding-job-stack">
        <AnimatePresence initial={false} mode="wait" onExitComplete={onExitComplete}>
          {showHelp ? (
            <motion.div
              key="job-help"
              id="job-help-panel"
              className="onboarding-help"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            >
              <button
                type="button"
                ref={closeRef}
                autoFocus
                aria-label="Close job help"
                data-testid="job-help-close"
                className="onboarding-help-close"
                style={{ backgroundColor: "#f3f3f3" }}
                onClick={() => {
                  requestRestoreFocus();
                  setShowHelp(false);
                }}
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
                className="onboarding-help-card"
                style={{
                  backgroundColor: palette.accent,
                  color: "#fff",
                }}
              >
                <p>
                  My job is what I handle for you. It tells me where to focus,
                  what kind of work to take on, and what helpful looks like.
                </p>
                <p>
                  Choose a starting point below, then edit it in your own words.
                </p>
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="job-controls"
              className="onboarding-job-controls"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            >
              <div
                data-testid="job-suggestions"
                className="remove-scrollbar onboarding-horizontal-scroll onboarding-chip-row"
              >
                <OnboardingHelpTrigger
                  ref={triggerRef}
                  accent={palette.accent}
                  muted={palette.muted}
                  softStrong={palette.softStrong}
                  ariaLabel="Learn about job descriptions"
                  expanded={showHelp}
                  controls="job-help-panel"
                  testId="job-help"
                  onClick={() => setShowHelp(true)}
                />
                {JOB_SUGGESTIONS.map((suggestion) => {
                  const selected = job.trim() === suggestion;
                  const testId = suggestion.toLowerCase().replace(/[^a-z0-9]+/g, "-");

                  return (
                    <button
                      key={suggestion}
                      type="button"
                      data-testid={`job-suggestion-${testId}`}
                      aria-pressed={selected}
                      className="onboarding-chip"
                      data-selected={selected ? "true" : "false"}
                      onClick={() => setJob(suggestion)}
                      style={{
                        borderRadius: 100,
                        backgroundColor: selected ? palette.accent : palette.soft,
                        color: selected ? "#fff" : palette.accent,
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
                      {suggestion}
                    </button>
                  );
                })}
              </div>
              <div className="step-stage onboarding-editor-card onboarding-editor-card--job">
                <textarea
                  aria-label="Ally job"
                  data-testid="job-input"
                  value={job}
                  onChange={(event) => setJob(event.target.value)}
                  placeholder="What do I handle for you?"
                  maxLength={JOB_LIMIT}
                  className="onboarding-editor-input"
                />
              </div>
              <p data-testid="job-counter" className="onboarding-editor-counter">
                {filled ? `${remaining} characters left` : "200 character limit"}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </OnboardingLayout>
  );
}
