"use client";

import { Artboard } from "@/components/artboard";
import { BackButton } from "@/components/back-button";
import { DEFAULT_ACCENT, NextButton } from "@/components/next-button";
import { ProgressRing } from "@/components/progress-ring";
import { JOB_LIMIT, useOnboardingStore } from "../_store/onboarding-store";
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
    <Artboard>
      <div data-testid="job-description" style={{ position: "absolute", inset: 0 }}>
        <BackButton onClick={back} />
        <ProgressRing progress={0.7} color={accent} />
        <StepHeading
          mark={
            <PersistentAllyAvatar
              shape={shape}
              state="thinking"
              color={accent}
              size={40}
            />
          }
        >
          What is my
          <br />
          job description?
        </StepHeading>
        <div
          className="step-stage"
          style={{
            borderRadius: 20,
            backgroundColor: "#f3f3f3",
            left: 20,
            right: 20,
            top: 403,
            height: 250,
            position: "absolute",
            overflow: "hidden",
          }}
        >
         <textarea
           aria-label="Ally job"
            data-testid="job-input"
            value={job}
            onChange={(event) => setJob(event.target.value)}
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
          data-testid="job-counter"
          style={{
            left: "50%",
            top: 671,
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
          {filled ? `${remaining} characters left` : "200 character limit"}
        </p>
        <NextButton
          label="Next"
          active={filled}
          color={accent}
          onClick={() => goTo("personality")}
        />
      </div>
    </Artboard>
  );
}
