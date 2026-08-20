import { getOnboardingProgress, type OnboardingStep } from './onboarding-state';

export type OnboardingChromeConfig = {
  progress: number;
  title: string;
};

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
