"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { InviteRequiredNotice } from "./invite-required-notice";

import Onboarding from "./(onboarding)/_components";
import {
  hasOnboardingResume,
  isOnboardingResumeQuery,
} from "./(onboarding)/_store/onboarding-resume";
import { OnboardingStateProvider } from "./(onboarding)/_store/onboarding-store";
import { getWebEnvironment } from "../lib/env";
import { pushReturnPath } from "../lib/pwa/push-navigation";
import { logoutDestination, NOTIFICATION_CLEANUP_NOTICE } from "../lib/session/logout-destination";
import { useSession } from "../lib/session/session-context";
import { WaitlistFlowProvider } from "../lib/waitlist/flow";
import { OnboardingHandoffScreen } from "../lib/allies/onboarding-handoff-screen";
import { QuietSplash } from "../components/loading-skeletons";


const subscribeToResume = (notify: () => void) => {
  window.addEventListener("storage", notify);
  return () => window.removeEventListener("storage", notify);
};

export function HomePageClient() {
  const environment = getWebEnvironment();
  const router = useRouter();
  const searchParams = useSearchParams();
  const pushTarget = pushReturnPath(searchParams.get("returnTo"));
  const logoutUnconfirmed = searchParams.get("signout") === "unconfirmed";
  const session = useSession();
  const sessionStatus = session.state.status;
  const restoreSession = session.restore;
  const restoreStarted = useRef(false);
  const homeRedirectStarted = useRef(false);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const storedResume = useSyncExternalStore(subscribeToResume, hasOnboardingResume, () => null);
  const resumeRequested =
    isOnboardingResumeQuery(searchParams.get("resume")) || storedResume === true;
  const resumeSignedIn = !logoutUnconfirmed && resumeRequested && sessionStatus === "signed-in";
  const sendSignedInHome = !logoutUnconfirmed && storedResume !== null && sessionStatus === "signed-in" && !resumeRequested;

  useEffect(() => {
    if (logoutUnconfirmed || restoreStarted.current || sessionStatus !== "unknown") return;
    restoreStarted.current = true;
    void restoreSession().catch(() => setRestoreFailed(true));
  }, [logoutUnconfirmed, restoreSession, sessionStatus]);

  useEffect(() => {
    if (resumeSignedIn) {
      homeRedirectStarted.current = true;
      return;
    }
    if (!sendSignedInHome || homeRedirectStarted.current) return;
    homeRedirectStarted.current = true;
    router.replace(pushTarget ?? "/home");
  }, [resumeSignedIn, router, sendSignedInHome, pushTarget]);

  if (logoutUnconfirmed) return <LogoutRecovery />;

  if (storedResume === null) {
    return <HomeResumeStatus message="Checking your secure session…" />;
  }

  if (resumeRequested && (sessionStatus === "unknown" || sessionStatus === "restoring") && !restoreFailed) {
    return <HomeResumeStatus message="Checking your secure session…" />;
  }

  if (sendSignedInHome) {
    return <HomeResumeStatus message="Opening your home…" />;
  }

  if (resumeSignedIn) return <OnboardingHandoffScreen />;

  return (
    <>
    {searchParams.get("notification_cleanup") === "unconfirmed" ? <p role="alert">{NOTIFICATION_CLEANUP_NOTICE}</p> : null}
    <InviteRequiredNotice visible={searchParams.get("auth_error") === "invite_required"} />
    <OnboardingStateProvider initialStep="welcome">
      <WaitlistFlowProvider
        onboarding
        featureEnabled={environment.waitlistEnabled}
        consentVersion={environment.waitlistConsentVersion}
      >
        <Onboarding
          presentation="drawer"
          waitlistEnabled={environment.waitlistEnabled}
        />
      </WaitlistFlowProvider>
    </OnboardingStateProvider>
    </>
  );
}

function LogoutRecovery() {
  const session = useSession();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const retry = async () => {
    setBusy(true);
    try {
      const result = await session.logout();
      if (result.serverConfirmed) router.replace(logoutDestination(result, "/"));
    } finally {
      setBusy(false);
    }
  };
  return <main className="onboarding-handoff">
    <h1>Let’s finish signing you out</h1>
    <p role="alert">We couldn’t confirm sign-out with the server. Your account may still be signed in on this browser.</p>
    <button type="button" disabled={busy} onClick={() => void retry().catch(() => undefined)}>{busy ? "Signing out…" : "Retry sign out"}</button>
  </main>;
}

function HomeResumeStatus({ message }: { message: string }) {
  return <QuietSplash label={message} />;
}
