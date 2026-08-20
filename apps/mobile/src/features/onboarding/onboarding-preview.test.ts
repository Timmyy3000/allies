import { describe, expect, it } from 'vitest';

import {
  ONBOARDING_PREVIEW_ENTRANCE_DELAY_MS,
  ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS,
  ONBOARDING_PREVIEW_THINKING_DELAY_MS,
  getNextOnboardingPreviewPhase,
  getOnboardingGreeting,
  getVisibleOnboardingGreeting,
} from './onboarding-preview';

describe('onboarding preview flow', () => {
  it('keeps the handoff timing short and deliberate', () => {
    expect(ONBOARDING_PREVIEW_ENTRANCE_DELAY_MS).toBe(2400);
    expect(ONBOARDING_PREVIEW_THINKING_DELAY_MS).toBe(900);
    expect(ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS).toBe(18);
  });

  it('advances through coming alive, thinking, and ready in order', () => {
    expect(getNextOnboardingPreviewPhase('coming-alive')).toBe('thinking');
    expect(getNextOnboardingPreviewPhase('thinking')).toBe('ready');
    expect(getNextOnboardingPreviewPhase('ready')).toBe('ready');
  });

  it('builds the first Ally greeting and reveals it incrementally', () => {
    const greeting = getOnboardingGreeting('Sally Morano');

    expect(greeting).toContain('Welcome! I am your ally');
    expect(greeting).toContain('✨ What We Can Do Together');
    expect(greeting).toContain('• Chat Freely:');
    expect(getVisibleOnboardingGreeting(greeting, 7)).toBe(greeting.slice(0, 7));
    expect(getVisibleOnboardingGreeting(greeting, -1)).toBe('');
    expect(getVisibleOnboardingGreeting(greeting, greeting.length + 10)).toBe(greeting);
  });
});
