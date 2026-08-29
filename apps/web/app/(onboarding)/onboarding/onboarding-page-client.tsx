"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import Onboarding from "../_components";
import { OnboardingStateProvider } from "../_store/onboarding-store";
import { getWebEnvironment } from "../../../lib/env";
import { useSession } from "../../../lib/session/session-context";
import { WaitlistFlowProvider } from "../../../lib/waitlist/flow";

export function OnboardingPageClient() {
  const environment = getWebEnvironment();
  const session = useSession();
  const router = useRouter();
  const sessionStatus = session.state.status;
  const restoreSession = session.restore;
  const restoreStarted = useRef(false);
  const redirectStarted = useRef(false);
  const [restoreFailed, setRestoreFailed] = useState(false);

  useEffect(() => {
    if (restoreStarted.current || sessionStatus !== "unknown") return;
    restoreStarted.current = true;
    void restoreSession().catch(() => setRestoreFailed(true));
  }, [restoreSession, sessionStatus]);

  useEffect(() => {
    if (sessionStatus !== "signed-in" || redirectStarted.current) return;
    redirectStarted.current = true;
    router.replace("/home/new");
  }, [router, sessionStatus]);

  const retryRestore = () => {
    setRestoreFailed(false);
    void restoreSession().catch(() => setRestoreFailed(true));
  };

  return (
    <OnboardingStateProvider initialStep="name">
      {sessionStatus === "signed-in" ? (
        <OnboardingStatus message="Opening your Ally space…" />
      ) : sessionStatus === "unavailable" ? (
        <OnboardingStatus
          message="We couldn't reach your Allies. Try again when you're ready."
          action={{ label: "Try again", onClick: retryRestore }}
        />
      ) : (sessionStatus === "unknown" || sessionStatus === "restoring") && !restoreFailed ? (
        <OnboardingStatus message="Checking your secure session…" />
      ) : (
        <WaitlistFlowProvider
          featureEnabled={environment.waitlistEnabled}
          consentVersion={environment.waitlistConsentVersion}
        >
          <Onboarding waitlistEnabled={environment.waitlistEnabled} />
        </WaitlistFlowProvider>
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
