import { describe, expect, it } from 'vitest';

import { getOnboardingChrome } from './onboarding-shell-config';

describe('onboarding chrome', () => {
  it('keeps header metadata stable and step-driven', () => {
    expect(getOnboardingChrome('name')).toEqual({
      progress: 0,
      title: 'What do you want\nto name your ally?',
    });
    expect(getOnboardingChrome('look')).toEqual({
      progress: 0.45,
      title: 'What should I\nlook like?',
    });
    expect(getOnboardingChrome('job')).toEqual({
      progress: 0.7,
      title: 'What is my\njob description?',
    });
    expect(getOnboardingChrome('personality')).toEqual({
      progress: 0.9,
      title: 'What should my\npersonality be?',
    });
    expect(getOnboardingChrome('preview')).toEqual({
      progress: 1,
      title: 'Your Ally is ready',
    });
  });
});
