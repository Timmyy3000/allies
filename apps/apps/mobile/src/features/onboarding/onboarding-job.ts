export const JOB_SUGGESTIONS = [
  'Teach me a language',
  'Track my finances',
  'Manage my calendar',
] as const;

export function getJobSuggestionState(draft: string, suggestion: string) {
  return {
    replacement: suggestion,
    selected: draft.trim() === suggestion,
  };
}
