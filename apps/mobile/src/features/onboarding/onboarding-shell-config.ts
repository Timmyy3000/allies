import { getOnboardingProgress, type OnboardingStep } from './onboarding-state';

export type OnboardingChromeConfig = {
  progress: number;
  title: string;
};

export type OnboardingHeaderAllyVariant = 'none' | 'placeholder' | 'selected';

export function getOnboardingChrome(
  step: Exclude<OnboardingStep, 'welcome'>,
): OnboardingChromeConfig {
  const titles: Record<Exclude<OnboardingStep, 'welcome'>, string> = {
    job: 'What is my\njob description?',
    look: 'What should I\nlook like?',
    name: 'What do you want\nto name your ally?',
    personality: 'What should my\npersonality be?',
    preview: 'Your Ally is ready',
  };

  return {
    progress: getOnboardingProgress(step),
    title: titles[step],
  };
}

export function getOnboardingHeaderAllyVariant(
  step: Exclude<OnboardingStep, 'welcome'>,
): OnboardingHeaderAllyVariant {
  if (step === 'name') return 'none';
  if (step === 'look') return 'placeholder';
  return 'selected';
}

export function isOnboardingFooterDisabled(
  step: OnboardingStep,
  canContinue: boolean,
  personalityHelpOpen: boolean,
) {
  return !canContinue || (step === 'personality' && personalityHelpOpen);
}
