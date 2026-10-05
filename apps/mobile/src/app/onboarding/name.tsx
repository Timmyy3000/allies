import { Stack, useRouter } from 'expo-router';
import { useReducedMotion } from 'react-native-reanimated';

import OnboardingFlow from '@/features/onboarding/onboarding-flow';

export default function OnboardingNameScreen() {
  const router = useRouter();
  const reducedMotion = Boolean(useReducedMotion());

  const returnToWelcome = () => {
    if (router.canGoBack()) {
      router.back();
      return;
    }
    router.replace('/');
  };

  return (
    <>
      <Stack.Screen
        options={{
          animation: reducedMotion ? 'none' : 'default',
          gestureEnabled: false,
        }}
      />
      <OnboardingFlow initialStep="name" onExit={returnToWelcome} />
    </>
  );
}
