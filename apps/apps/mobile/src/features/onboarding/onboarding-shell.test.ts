
import { describe, expect, it } from 'vitest';

import {
  getOnboardingChrome,
  getOnboardingHeaderAllyVariant,
  isOnboardingFooterDisabled,
} from './onboarding-shell-config';

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

  it('uses the neutral placeholder until the selected Ally enters the job step', () => {
    expect(getOnboardingHeaderAllyVariant('name')).toBe('none');
    expect(getOnboardingHeaderAllyVariant('look')).toBe('placeholder');
    expect(getOnboardingHeaderAllyVariant('job')).toBe('selected');
    expect(getOnboardingHeaderAllyVariant('personality')).toBe('selected');
  });

  it('disables the personality footer while help is open', () => {
    expect(isOnboardingFooterDisabled('personality', true, true)).toBe(true);
    expect(isOnboardingFooterDisabled('personality', true, false)).toBe(false);
    expect(isOnboardingFooterDisabled('personality', false, false)).toBe(true);
  });

  it('disables the job footer while help is open', () => {
    expect(isOnboardingFooterDisabled('job', true, true)).toBe(true);
    expect(isOnboardingFooterDisabled('job', true, false)).toBe(false);
  });
});
