import { describe, expect, it } from 'vitest';

import {
  ALLY_COLORS,
  ALLY_SHAPES,
  INITIAL_ONBOARDING_FLOW,
  MAX_JOB_DESCRIPTION_LENGTH,
  MAX_NAME_LENGTH,
  MAX_PERSONALITY_NOTE_LENGTH,
  PERSONALITIES,
  getNextOnboardingStep,
  getOnboardingAccent,
  getOnboardingProgress,
  getPreviousOnboardingStep,
  getPersonalityNoteForSelection,
  isAllyNameReady,
  isJobDescriptionReady,
  isLookReady,
  isPersonalityReady,
  truncateOnboardingText,
} from './onboarding-state';

describe('onboarding state', () => {
  it('rejects blank and whitespace-only Ally names', () => {
    expect(isAllyNameReady('')).toBe(false);
    expect(isAllyNameReady('   ')).toBe(false);
  });

  it('accepts a name containing at least one non-whitespace character', () => {
    expect(isAllyNameReady(' Sally ')).toBe(true);
  });

  it('derives progress from the current step', () => {
    expect(getOnboardingProgress('welcome')).toBe(0);
    expect(getOnboardingProgress('name')).toBe(0);
    expect(getOnboardingProgress('look')).toBe(0.45);
    expect(getOnboardingProgress('job')).toBe(0.7);
    expect(getOnboardingProgress('personality')).toBe(0.9);
    expect(getOnboardingProgress('preview')).toBe(1);
  });

  it('moves one step backward without storing progress separately', () => {
    expect(getPreviousOnboardingStep('notifications')).toBe('basics');
    expect(getPreviousOnboardingStep('basics')).toBe('preview');
    expect(getPreviousOnboardingStep('preview')).toBe('personality');
    expect(getPreviousOnboardingStep('personality')).toBe('job');
    expect(getPreviousOnboardingStep('job')).toBe('look');
    expect(getPreviousOnboardingStep('look')).toBe('name');
    expect(getPreviousOnboardingStep('name')).toBe('welcome');
    expect(getPreviousOnboardingStep('welcome')).toBe('welcome');
  });

  it('keeps the supported appearance and personality values bounded', () => {
    expect(ALLY_SHAPES).toEqual(['ghosty', 'rolly', 'boxy', 'rocky']);
    expect(ALLY_COLORS).toEqual([
      '#FF5800',
      '#FD304F',
      '#0D92FD',
      '#BE9BF5',
      '#3446E9',
      '#A3F06F',
      '#FBE65F',
    ]);
    expect(PERSONALITIES).toEqual(['Concise', 'Quirky', 'Analytical', 'Funny']);
    expect(getOnboardingAccent(null)).toBe('#FF5800');
    expect(getOnboardingAccent('#FD304F')).toBe('#FD304F');
    expect(INITIAL_ONBOARDING_FLOW.selectedColor).toBeNull();
  });

  it('gates each step on the smallest useful input', () => {
    expect(isLookReady({ hasSwipedAvatar: false, selectedColor: '#FD304F' })).toBe(false);
    expect(isLookReady({ hasSwipedAvatar: true, selectedColor: null })).toBe(false);
    expect(isLookReady({ hasSwipedAvatar: true, selectedColor: '#FD304F' })).toBe(true);
    expect(isJobDescriptionReady('   ')).toBe(false);
    expect(isJobDescriptionReady('Handle my calendar')).toBe(true);
    expect(isPersonalityReady([], '')).toBe(false);
    expect(isPersonalityReady(['Concise'], '')).toBe(true);
    expect(isPersonalityReady([], 'Be concise')).toBe(true);
  });

  it('bounds editable onboarding fields at their product limits', () => {
    expect(MAX_NAME_LENGTH).toBe(80);
    expect(MAX_JOB_DESCRIPTION_LENGTH).toBe(200);
    expect(MAX_PERSONALITY_NOTE_LENGTH).toBe(200);
    expect(truncateOnboardingText('12345', 3)).toBe('123');
  });

  it('keeps forward navigation derived from the current state', () => {
    expect(getNextOnboardingStep('welcome', INITIAL_ONBOARDING_FLOW)).toBe('name');
    expect(getNextOnboardingStep('name', INITIAL_ONBOARDING_FLOW)).toBe('name');
    expect(
      getNextOnboardingStep('name', { ...INITIAL_ONBOARDING_FLOW, allyName: 'Sally' }),
    ).toBe('look');
    expect(
      getNextOnboardingStep('look', {
        ...INITIAL_ONBOARDING_FLOW,
        hasSwipedAvatar: true,
        selectedColor: '#FD304F',
      }),
    ).toBe('job');
    expect(
      getNextOnboardingStep('job', {
        ...INITIAL_ONBOARDING_FLOW,
        jobDescription: 'Handle my calendar',
      }),
    ).toBe('personality');
    expect(
      getNextOnboardingStep('personality', {
        ...INITIAL_ONBOARDING_FLOW,
        personalities: ['Concise'],
      }),
    ).toBe('preview');
    expect(
      getNextOnboardingStep('preview', INITIAL_ONBOARDING_FLOW),
    ).toBe('basics');
    expect(
      getNextOnboardingStep('basics', INITIAL_ONBOARDING_FLOW),
    ).toBe('notifications');
    expect(
      getNextOnboardingStep('notifications', INITIAL_ONBOARDING_FLOW),
    ).toBe('notifications');
  });

  it('builds the personality note from the selected traits in selection order', () => {
    expect(getPersonalityNoteForSelection([])).toBe('');
    expect(getPersonalityNoteForSelection(['Concise'])).toBe(
      'I want you to be concise',
    );
    expect(getPersonalityNoteForSelection(['Concise', 'Quirky'])).toBe(
      'I want you to be concise, quirky',
    );
  });
});
