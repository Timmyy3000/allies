"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import Onboarding from "../_components";
import {
  isOnboardingResumeQuery,
} from "../_store/onboarding-resume";
import { OnboardingStateProvider } from "../_store/onboarding-store";
import { getWebEnvironment } from "../../../lib/env";
import { useSession } from "../../../lib/session/session-context";
import { WaitlistFlowProvider } from "../../../lib/waitlist/flow";
import { OnboardingHandoffScreen } from "../../../lib/allies/onboarding-handoff-screen";

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

  if (resumeSignedIn) return <OnboardingHandoffScreen />;

  return (
    <OnboardingStateProvider initialStep="intro">
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
          onboarding
          featureEnabled={environment.waitlistEnabled}
          consentVersion={environment.waitlistConsentVersion}
        >
            <Onboarding waitlistEnabled={environment.waitlistEnabled} />
        </WaitlistFlowProvider>
      ) : (
        <OnboardingStatus message="Checking your secure session…" />
      )}
    </OnboardingStateProvider>
  );
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
        color: "var(--text-primary)",
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
