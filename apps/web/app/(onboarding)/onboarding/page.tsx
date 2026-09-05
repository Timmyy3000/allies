import { Suspense } from "react";

import { OnboardingPageClient } from "./onboarding-page-client";

export default function OnboardingPage() {
  return (
    <Suspense>
      <OnboardingPageClient />
    </Suspense>
  );
}
