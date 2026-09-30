
import { describe, expect, it } from 'vitest';

import { JOB_SUGGESTIONS, getJobSuggestionState } from './onboarding-job';

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
  });
});
