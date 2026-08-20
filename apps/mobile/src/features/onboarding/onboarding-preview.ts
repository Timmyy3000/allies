export type OnboardingPreviewPhase = 'coming-alive' | 'thinking' | 'ready';

export const ONBOARDING_PREVIEW_ENTRANCE_DELAY_MS = 2400;
export const ONBOARDING_PREVIEW_THINKING_DELAY_MS = 900;
export const ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS = 18;

const FIRST_ALLY_GREETING = [
  'Welcome! I am your ally, and I am thrilled to help you make your day easier, more productive, and fun. Think of me as your always-available partner for brainstorming, writing, learning, and organising.',
  'No task is too big or too small, and I am constantly learning new ways to assist you better. Let us collaborate and build something great together.',
  '✨ What We Can Do Together',
  '• Chat Freely: Ask me questions about history, science, pop culture, or everyday facts.',
  '• Brainstorm Ideas: Outline your next big business project, travel itinerary, or workout plan.',
].join('\n\n');

export function getNextOnboardingPreviewPhase(
  phase: OnboardingPreviewPhase,
): OnboardingPreviewPhase {
  if (phase === 'coming-alive') return 'thinking';
  return 'ready';
}

export function getOnboardingGreeting(_allyName: string): string {
  return FIRST_ALLY_GREETING;
}

export function getVisibleOnboardingGreeting(
  greeting: string,
  characterCount: number,
): string {
  return greeting.slice(0, Math.max(0, characterCount));
}
