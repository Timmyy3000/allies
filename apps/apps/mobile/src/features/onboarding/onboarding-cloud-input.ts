import type { AllySeedInput, CreateAllyInput } from '@allies/cloud-client';

import { getOnboardingAccent, type OnboardingFlowState } from './onboarding-state';

const ONBOARDING_CATALOG_VERSION = 'v1';

export function toOnboardingAttemptInput(flow: OnboardingFlowState): AllySeedInput {
  const accent = getOnboardingAccent(flow.selectedColor);
  const personality = flow.personalityNote || flow.personalities.join(', ');

  return {
    name: flow.allyName.trim(),
    job: flow.jobDescription.trim(),
    personality: personality.trim(),
    appearanceCatalogVersion: ONBOARDING_CATALOG_VERSION,
    appearanceKey: `${flow.allyShape}:${accent.slice(1).toLowerCase()}`,
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
