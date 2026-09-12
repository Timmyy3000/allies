"use client";

import type { ReactNode } from "react";
import { useOnboardingStore } from "../_store/onboarding-store";
import { IntroductionScreen } from "./introduction";
import { JobDescriptionScreen } from "./job-description";
import { LookLikeScreen } from "./look-like";
import { NameAllyScreen } from "./name-ally";
import { PersonalityScreen } from "./personality";
import { WaitlistPreviewScreen } from "./waitlist-preview";

export default function OnboardingFlow({ onExit, introductionAllies }: { onExit: () => void; introductionAllies: ReactNode[] }) {
  const step = useOnboardingStore((state) => state.step);

  if (step === "intro") return <IntroductionScreen onBack={onExit} allies={introductionAllies} />;
  if (step === "look") return <LookLikeScreen />;
  if (step === "job") return <JobDescriptionScreen onExit={onExit} />;
  if (step === "personality") return <PersonalityScreen />;
  if (step === "preview") return <WaitlistPreviewScreen />;
  return <NameAllyScreen />;
}
