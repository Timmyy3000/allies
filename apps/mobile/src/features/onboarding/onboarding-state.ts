export const ALLY_SHAPES = ['ghosty', 'rolly', 'boxy', 'rocky'] as const;
export type AllyShape = (typeof ALLY_SHAPES)[number];

export const ALLY_COLORS = [
  '#FF5800',
  '#FD304F',
  '#0D92FD',
  '#BE9BF5',
  '#3446E9',
  '#A3F06F',
  '#FBE65F',
] as const;
export type AllyColorValue = (typeof ALLY_COLORS)[number];

export const PERSONALITIES = ['Concise', 'Quirky', 'Analytical', 'Funny'] as const;
export type Personality = (typeof PERSONALITIES)[number];

export type OnboardingStep =
  | 'welcome'
  | 'name'
  | 'look'
  | 'job'
  | 'personality'
  | 'preview'
  | 'basics'
  | 'notifications';

export type OnboardingFlowState = {
  allyName: string;
  allyShape: AllyShape;
  hasSwipedAvatar: boolean;
  jobDescription: string;
  personalityNote: string;
  personalities: Personality[];
  selectedColor: AllyColorValue | null;
  step: OnboardingStep;
};

export const DEFAULT_ONBOARDING_ACCENT: AllyColorValue = '#FF5800';
export const MAX_NAME_LENGTH = 80;
export const MAX_JOB_DESCRIPTION_LENGTH = 200;
export const MAX_PERSONALITY_NOTE_LENGTH = 200;

export const INITIAL_ONBOARDING_FLOW: OnboardingFlowState = {
  allyName: '',
  allyShape: 'ghosty',
  hasSwipedAvatar: false,
  jobDescription: '',
  personalityNote: '',
  personalities: [],
  selectedColor: null,
  step: 'welcome',
};

const PROGRESS_BY_STEP: Record<OnboardingStep, number> = {
  job: 0.7,
  look: 0.45,
  name: 0,
  personality: 0.9,
  preview: 1,
  basics: 1,
  notifications: 1,
  welcome: 0,
};

const PREVIOUS_STEP: Record<OnboardingStep, OnboardingStep> = {
  job: 'look',
  look: 'name',
  name: 'welcome',
  personality: 'job',
  preview: 'personality',
  basics: 'preview',
  notifications: 'basics',
  welcome: 'welcome',
};

export function getOnboardingAccent(
  selectedColor: AllyColorValue | null,
): AllyColorValue {
  return selectedColor ?? DEFAULT_ONBOARDING_ACCENT;
}

export function isAllyColor(value: string): value is AllyColorValue {
  return (ALLY_COLORS as readonly string[]).includes(value);
}

export function isAllyNameReady(value: string): boolean {
  return value.trim().length > 0;
}

export function isLookReady({
  hasSwipedAvatar,
  selectedColor,
}: Pick<OnboardingFlowState, 'hasSwipedAvatar' | 'selectedColor'>): boolean {
  return hasSwipedAvatar && selectedColor !== null;
}

export function isJobDescriptionReady(value: string): boolean {
  return value.trim().length > 0;
}

export function isPersonalityReady(
  personalities: readonly Personality[],
  note: string,
): boolean {
  return personalities.length > 0 || note.trim().length > 0;
}

export function getPersonalityNoteForSelection(
  personalities: readonly Personality[],
): string {
  if (personalities.length === 0) return '';

  return `I want you to be ${personalities
    .map((personality) => personality.toLowerCase())
    .join(', ')}`;
}

export function truncateOnboardingText(value: string, maximumLength: number): string {
  return value.slice(0, maximumLength);
}

export function getOnboardingProgress(step: OnboardingStep): number {
  return PROGRESS_BY_STEP[step];
}

export function getPreviousOnboardingStep(step: OnboardingStep): OnboardingStep {
  return PREVIOUS_STEP[step];
}

export function getNextOnboardingStep(
  step: OnboardingStep,
  state: OnboardingFlowState,
): OnboardingStep {
  if (step === 'welcome') return 'name';
  if (step === 'name') return isAllyNameReady(state.allyName) ? 'look' : step;
  if (step === 'look') return isLookReady(state) ? 'job' : step;
  if (step === 'job') {
    return isJobDescriptionReady(state.jobDescription) ? 'personality' : step;
  }
  if (step === 'personality') {
    return isPersonalityReady(state.personalities, state.personalityNote) ? 'preview' : step;
  }
  if (step === 'preview') return 'basics';
  if (step === 'basics') return 'notifications';
  return 'notifications';
}
