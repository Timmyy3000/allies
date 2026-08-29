import Onboarding from "./(onboarding)/_components";
import { OnboardingStateProvider } from "./(onboarding)/_store/onboarding-store";
import { getWebEnvironment } from "../lib/env";
import { WaitlistFlowProvider } from "../lib/waitlist/flow";
import Link from "next/link";

import styles from "./page.module.css";

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
      <Link className={styles.googleSignInProbe} href="/sign-in?returnTo=%2Fhome">
        Continue with Google
      </Link>
    </OnboardingStateProvider>
  );
}
