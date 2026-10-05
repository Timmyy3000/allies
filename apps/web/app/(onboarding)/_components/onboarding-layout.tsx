import type { ReactNode } from "react";

import { Artboard } from "@/components/artboard";
import { BackButton } from "@/components/back-button";
import { NextButton } from "@/components/next-button";
import { ProgressRing } from "@/components/progress-ring";

export function OnboardingLayout({
  testId,
  progress,
  color,
  onBack,
  children,
  nextLabel = "Next",
  nextActive,
  nextColor,
  onNext,
}: {
  testId: string;
  progress: number;
  color?: string;
  onBack: () => void;
  children: ReactNode;
  nextLabel?: string;
  nextActive: boolean;
  nextColor?: string;
  onNext: () => void;
}) {
  return (
    <Artboard>
      <div data-testid={testId} className="onboarding-page">
        <div className="onboarding-header">
          <BackButton onClick={onBack} />
          <ProgressRing progress={progress} color={color} />
        </div>
        <div className="onboarding-content">
          {children}
        </div>
        <div className="onboarding-footer">
          <NextButton
            label={nextLabel}
            active={nextActive}
            color={nextColor}
            onClick={onNext}
          />
        </div>
      </div>
    </Artboard>
  );
}
