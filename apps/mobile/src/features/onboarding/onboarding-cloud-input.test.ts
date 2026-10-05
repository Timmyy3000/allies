import { describe, expect, it } from 'vitest';

import { toCreateAllyInput, toOnboardingAttemptInput } from './onboarding-cloud-input';
import type { OnboardingFlowState } from './onboarding-state';

const flow: OnboardingFlowState = {
  allyName: ' Maya ',
  allyShape: 'ghosty',
  hasSwipedAvatar: true,
  jobDescription: ' Study partner ',
  personalityNote: 'I want you to be analytical',
  personalities: ['Analytical'],
  selectedColor: '#FD304F',
  step: 'preview',
};

describe('onboarding Cloud input', () => {
  it('maps the existing onboarding state to the v1 appearance and stable config', () => {
    expect(toOnboardingAttemptInput(flow)).toEqual({
      name: 'Maya',
      job: 'Study partner',
      personality: 'I want you to be analytical',
      appearanceCatalogVersion: 'v1',
      appearanceKey: 'ghosty:fd304f',
    });
  });

  it('keeps the final reply as the exact create input', () => {
    expect(toCreateAllyInput(flow, 'a'.repeat(32), ' Keep this reply. ')).toEqual({
      ...toOnboardingAttemptInput(flow),
      onboardingAttempt: 'a'.repeat(32),
      reply: ' Keep this reply. ',
    });
  });
});
