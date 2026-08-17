import Onboarding from "./(onboarding)/_components";
import { OnboardingStateProvider } from "./(onboarding)/_store/onboarding-store";
import { getWebEnvironment } from "../lib/env";
import { WaitlistFlowProvider } from "../lib/waitlist/flow";

export default function Home() {
  const environment = getWebEnvironment();

  return (
    <OnboardingStateProvider>
      <WaitlistFlowProvider
        featureEnabled={environment.waitlistEnabled}
        consentVersion={environment.waitlistConsentVersion}
      >
        <Onboarding
          presentation="drawer"
          waitlistEnabled={environment.waitlistEnabled}
        />
      </WaitlistFlowProvider>
    </OnboardingStateProvider>
  );
}
