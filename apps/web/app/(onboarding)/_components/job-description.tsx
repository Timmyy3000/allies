"use client";

import { DEFAULT_ACCENT } from "@/components/next-button";
import { JOB_LIMIT, useOnboardingStore } from "../_store/onboarding-store";
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
  const filled = job.trim().length > 0;
  const remaining = JOB_LIMIT - job.length;

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
      <div className="onboarding-editor-stack">
        <div className="step-stage onboarding-editor-card">
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
        <p
          data-testid="job-counter"
          className="onboarding-editor-counter"
        >
          {filled ? `${remaining} characters left` : "200 character limit"}
        </p>
      </div>
    </OnboardingLayout>
  );
}
