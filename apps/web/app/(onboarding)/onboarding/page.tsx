import Onboarding from "../_components";
import { OnboardingStateProvider } from "../_store/onboarding-store";
import { getWebEnvironment } from "../../../lib/env";
import { WaitlistFlowProvider } from "../../../lib/waitlist/flow";

export default function OnboardingPage() {
  const environment = getWebEnvironment();
  return (
    <OnboardingStateProvider>
      <WaitlistFlowProvider
        featureEnabled={environment.waitlistEnabled}
        consentVersion={environment.waitlistConsentVersion}
      >
        <Onboarding waitlistEnabled={environment.waitlistEnabled} />
      </WaitlistFlowProvider>
    </OnboardingStateProvider>
  );
}
