import type { CreateAllyInput, OnboardingAttemptInput } from '@allies/cloud-client';

import { getOnboardingAccent, type OnboardingFlowState } from './onboarding-state';

const ONBOARDING_CATALOG_VERSION = 'v1';

export function toOnboardingAttemptInput(flow: OnboardingFlowState): OnboardingAttemptInput {
  const accent = getOnboardingAccent(flow.selectedColor);
  const personality = flow.personalityNote || flow.personalities.join(', ');

  return {
    name: flow.allyName.trim(),
    job: flow.jobDescription.trim(),
    personality: personality.trim(),
    appearance: {
      catalogVersion: ONBOARDING_CATALOG_VERSION,
      key: `${flow.allyShape}:${accent.slice(1).toLowerCase()}`,
    },
  };
}

export function toCreateAllyInput(
  flow: OnboardingFlowState,
  onboardingAttempt: string,
  reply: string,
): CreateAllyInput {
  return {
    ...toOnboardingAttemptInput(flow),
    onboardingAttempt,
    reply,
  };
}
