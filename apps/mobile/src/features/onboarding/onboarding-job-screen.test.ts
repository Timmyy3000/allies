import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { JOB_SUGGESTIONS, getJobSuggestionState } from './onboarding-job';

const source = readFileSync(
  fileURLToPath(new URL('./onboarding-job-screen.tsx', import.meta.url)),
  'utf8',
);

describe('job suggestion selector', () => {
  it('uses the approved labels and replaces the draft when selected', () => {
    expect(JOB_SUGGESTIONS).toEqual([
      'Teach me a language',
      'Track my finances',
      'Manage my calendar',
    ]);
    expect(getJobSuggestionState('  Teach me a language  ', JOB_SUGGESTIONS[0])).toEqual({
      selected: true,
      replacement: 'Teach me a language',
    });
    expect(getJobSuggestionState('Teach me a language for work', JOB_SUGGESTIONS[0])).toEqual({
      selected: false,
      replacement: 'Teach me a language',
    });
    expect(source).toContain('onJobDescriptionChange(suggestion.replacement)');
    expect(source).toContain('selected={suggestion.selected}');
  });

  it('matches the personality selector layout, motion, and help copy', () => {
    expect(source).toContain('<Animated.ScrollView');
    expect(source).toContain('getOnboardingEdgeToEdgeStyle');
    expect(source).toContain('keyboardProgress');
    expect(source).toContain('getOnboardingPersonalitySelectorOffset(keyboardProgress.value)');
    expect(source).toContain('<OnboardingSelectorChip');
    expect(source).toContain('onHelpVisibilityChange');
    expect(source).toContain('My job is what I handle for you. It tells me where to focus, what kind of work to take on, and what helpful looks like.');
    expect(source).toContain('Choose a starting point below, then edit it in your own words.');
    expect(source).toContain('paddingHorizontal: ONBOARDING_PERSONALITY_ROW_INSET');
    expect(source).toMatch(/editorRegion:\s*\{[\s\S]*?marginTop: 12,/);
  });
});
