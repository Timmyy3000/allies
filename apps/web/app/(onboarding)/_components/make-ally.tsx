"use client";

import { useOnboardingStore } from "../_store/onboarding-store";
import { JobDescriptionScreen } from "./job-description";
import { LookLikeScreen } from "./look-like";
import { NameAllyScreen } from "./name-ally";
import { PersonalityScreen } from "./personality";
import { WaitlistPreviewScreen } from "./waitlist-preview";

export default function OnboardingFlow() {
  const step = useOnboardingStore((state) => state.step);

  if (step === "look") return <LookLikeScreen />;
  if (step === "job") return <JobDescriptionScreen />;
  if (step === "personality") return <PersonalityScreen />;
  if (step === "preview") return <WaitlistPreviewScreen />;
  return <NameAllyScreen />;
}
