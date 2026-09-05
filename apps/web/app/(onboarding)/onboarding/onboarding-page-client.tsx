"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import Onboarding from "../_components";
import {
  OnboardingAuthResumeContext,
  isOnboardingResumeQuery,
  readOnboardingResume,
} from "../_store/onboarding-resume";
import { OnboardingStateProvider, useOnboardingStore } from "../_store/onboarding-store";
import { getWebEnvironment } from "../../../lib/env";
import { useSession } from "../../../lib/session/session-context";
import { WaitlistFlowProvider } from "../../../lib/waitlist/flow";

export function OnboardingPageClient() {
  const environment = getWebEnvironment();
  const session = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionStatus = session.state.status;
  const restoreSession = session.restore;
  const restoreStarted = useRef(false);
  const redirectStarted = useRef(false);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const resumeAfterGoogle = isOnboardingResumeQuery(searchParams.get("resume"));

  useEffect(() => {
    if (restoreStarted.current || sessionStatus !== "unknown") return;
    restoreStarted.current = true;
    void restoreSession().catch(() => setRestoreFailed(true));
  }, [restoreSession, sessionStatus]);

  useEffect(() => {
    if (sessionStatus !== "signed-in" || resumeAfterGoogle || redirectStarted.current) {
      return;
    }
    redirectStarted.current = true;
    router.replace("/home/new");
  }, [resumeAfterGoogle, router, sessionStatus]);

  const retryRestore = () => {
    setRestoreFailed(false);
    void restoreSession().catch(() => setRestoreFailed(true));
  };

  const stayOnPublicFlow =
    sessionStatus === "signed-out" ||
    restoreFailed ||
    (sessionStatus === "signed-in" && resumeAfterGoogle);
  const resumeSignedIn = resumeAfterGoogle && sessionStatus === "signed-in";

  return (
    <OnboardingStateProvider initialStep={resumeSignedIn ? "preview" : "name"}>
      {sessionStatus === "signed-in" && !resumeAfterGoogle ? (
        <OnboardingStatus message="Opening your Ally space…" />
      ) : sessionStatus === "unavailable" ? (
        <OnboardingStatus
          message="We couldn't reach your Allies. Try again when you're ready."
          action={{ label: "Try again", onClick: retryRestore }}
        />
      ) : (sessionStatus === "unknown" || sessionStatus === "restoring") && !restoreFailed ? (
        <OnboardingStatus message="Checking your secure session…" />
      ) : stayOnPublicFlow ? (
        <WaitlistFlowProvider
          featureEnabled={environment.waitlistEnabled}
          consentVersion={environment.waitlistConsentVersion}
        >
          <OnboardingAuthResumeContext.Provider value={resumeSignedIn}>
            {resumeSignedIn ? <OnboardingResumeHydrator /> : null}
            <Onboarding waitlistEnabled={environment.waitlistEnabled} />
          </OnboardingAuthResumeContext.Provider>
        </WaitlistFlowProvider>
      ) : (
        <OnboardingStatus message="Checking your secure session…" />
      )}
    </OnboardingStateProvider>
  );
}

function OnboardingResumeHydrator() {
  const hydrate = useOnboardingStore((state) => state.hydrate);
  const goTo = useOnboardingStore((state) => state.goTo);
  const applied = useRef(false);

  useLayoutEffect(() => {
    if (applied.current) return;
    applied.current = true;
    const snapshot = readOnboardingResume();
    if (snapshot) hydrate(snapshot);
    goTo("preview");
  }, [goTo, hydrate]);

  return null;
}

function OnboardingStatus({
  message,
  action,
}: {
  message: string;
  action?: { label: string; onClick: () => void };
}) {
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
      <div style={{ textAlign: "center" }}>
        <p role="status" aria-live="polite">{message}</p>
        {action ? (
          <button type="button" onClick={action.onClick}>
            {action.label}
          </button>
        ) : null}
      </div>
    </main>
  );
}
