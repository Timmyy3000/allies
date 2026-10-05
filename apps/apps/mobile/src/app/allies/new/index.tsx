import OnboardingFlow from '@/features/onboarding/onboarding-flow';
import { useRouter } from 'expo-router';

export default function NewAllyScreen() {
  const router = useRouter();
  return <OnboardingFlow initialStep="name" onExit={() => router.back()} />;
}
