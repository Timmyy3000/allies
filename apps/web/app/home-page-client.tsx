"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import Onboarding from "./(onboarding)/_components";
import {
  OnboardingAuthResumeContext,
  hasOnboardingResume,
  isOnboardingResumeQuery,
} from "./(onboarding)/_store/onboarding-resume";
import { OnboardingStateProvider } from "./(onboarding)/_store/onboarding-store";
import { getWebEnvironment } from "../lib/env";
import { useSession } from "../lib/session/session-context";
import { WaitlistFlowProvider } from "../lib/waitlist/flow";

import styles from "./page.module.css";

export function HomePageClient() {
  const environment = getWebEnvironment();
  const router = useRouter();
  const searchParams = useSearchParams();
  const session = useSession();
  const sessionStatus = session.state.status;
  const restoreSession = session.restore;
  const restoreStarted = useRef(false);
  const homeRedirectStarted = useRef(false);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [storedResume, setStoredResume] = useState<boolean | null>(null);
  const resumeRequested =
    isOnboardingResumeQuery(searchParams.get("resume")) || storedResume === true;
  const resumeSignedIn = resumeRequested && sessionStatus === "signed-in";
  const sendSignedInHome = storedResume !== null && sessionStatus === "signed-in" && !resumeRequested;

  if (storedResume === null && typeof window !== "undefined") {
    setStoredResume(hasOnboardingResume());
  }

  useEffect(() => {
    if (restoreStarted.current || sessionStatus !== "unknown") return;
    restoreStarted.current = true;
    void restoreSession().catch(() => setRestoreFailed(true));
  }, [restoreSession, sessionStatus]);

  useEffect(() => {
    if (!sendSignedInHome || homeRedirectStarted.current) return;
    homeRedirectStarted.current = true;
    router.replace("/home");
  }, [router, sendSignedInHome]);

  if (storedResume === null) {
    return <HomeResumeStatus message="Checking your secure session…" />;
  }

  if (resumeRequested && (sessionStatus === "unknown" || sessionStatus === "restoring") && !restoreFailed) {
    return <HomeResumeStatus message="Checking your secure session…" />;
  }

  if (sendSignedInHome) {
    return <HomeResumeStatus message="Opening your home…" />;
  }

  return (
    <OnboardingStateProvider initialStep={resumeSignedIn ? "preview" : "welcome"}>
      <OnboardingAuthResumeContext.Provider value={resumeSignedIn}>
        <WaitlistFlowProvider
          featureEnabled={environment.waitlistEnabled}
          consentVersion={environment.waitlistConsentVersion}
        >
          <Onboarding
            presentation="drawer"
            waitlistEnabled={environment.waitlistEnabled}
            resumeAfterAuth={resumeSignedIn}
          />
        </WaitlistFlowProvider>
      </OnboardingAuthResumeContext.Provider>
      <Link className={styles.googleSignInProbe} href="/sign-in?returnTo=%2Fhome">
        Continue with Google
      </Link>
    </OnboardingStateProvider>
  );
}

function HomeResumeStatus({ message }: { message: string }) {
  return (
    <main
      style={{
        minHeight: "100svh",
        display: "grid",
        placeItems: "center",
        padding: 24,
        color: "#121212",
        fontFamily: "var(--font-open-runde), sans-serif",
      }}
    >
      <p role="status" aria-live="polite">{message}</p>
    </main>
  );
}
