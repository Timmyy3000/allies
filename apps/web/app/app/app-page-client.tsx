"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { OnboardingHandoffScreen } from "../../lib/allies/onboarding-handoff-screen";
import { isStandalonePwa } from "../../lib/pwa/pwa-install";
import { googleSignInErrorMessage } from "../../lib/session/sign-in-errors";
import { useSession } from "../../lib/session/session-context";
import {
  hasOnboardingResume,
  isOnboardingResumeQuery,
} from "../(onboarding)/_store/onboarding-resume";

import { Welcome } from "./welcome";
import styles from "./app.module.css";

const subscribeToResume = (notify: () => void) => {
  window.addEventListener("storage", notify);
  return () => window.removeEventListener("storage", notify);
};

type SignInState = "idle" | "redirecting" | "error";

export function AppPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const session = useSession();
  const sessionStatus = session.state.status;
  const logoutUnconfirmed = searchParams.get("signout") === "unconfirmed";
  const restoreSession = session.restore;
  const restoreStarted = useRef(false);
  const homeRedirectStarted = useRef(false);
  const signInStarted = useRef(false);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [signInState, setSignInState] = useState<SignInState>("idle");
  const [signInError, setSignInError] = useState<string | null>(null);
  const storedResume = useSyncExternalStore(
    subscribeToResume,
    hasOnboardingResume,
    () => null,
  );
  const resumeRequested =
    isOnboardingResumeQuery(searchParams.get("resume")) || storedResume === true;
  const resumeSignedIn = resumeRequested && sessionStatus === "signed-in";
  const sendSignedInHome =
    storedResume !== null && sessionStatus === "signed-in" && !resumeRequested;

  useEffect(() => {
    if (logoutUnconfirmed || restoreStarted.current || sessionStatus !== "unknown") return;
    restoreStarted.current = true;
    void restoreSession().catch(() => setRestoreFailed(true));
  }, [logoutUnconfirmed, restoreSession, sessionStatus]);

  useEffect(() => {
    if (!sendSignedInHome || homeRedirectStarted.current) return;
    homeRedirectStarted.current = true;
    router.replace("/home");
  }, [router, sendSignedInHome]);

  const retryRestore = () => {
    setRestoreFailed(false);
    void restoreSession().catch(() => setRestoreFailed(true));
  };

  const startSignIn = async () => {
    if (signInStarted.current) return;

    signInStarted.current = true;
    setSignInState("redirecting");
    setSignInError(null);

    try {
      const redirectUrl = await session.runCloudOperation(
        (signal) => session.client.beginSignIn("/home", signal),
        { csrf: true },
      );
      window.location.assign(redirectUrl);
    } catch (error) {
      signInStarted.current = false;
      setSignInState("error");
      setSignInError(googleSignInErrorMessage(error));
    }
  };

  if (logoutUnconfirmed) {
    return <LogoutRecovery session={session} />;
  }

  if (restoreFailed || sessionStatus === "unavailable") {
    return (
      <AppStatus
        message="We couldn't reach your Allies. Try again when you're ready."
        action={{ label: "Try again", onClick: retryRestore }}
      />
    );
  }

  if (storedResume === null || sessionStatus === "unknown" || sessionStatus === "restoring") {
    return <AppStatus message="Checking your secure session…" />;
  }

  if (resumeSignedIn) return <OnboardingHandoffScreen />;

  if (sendSignedInHome) return <AppStatus message="Opening your home…" />;

  if (sessionStatus === "signed-out") {
    return (
      <Welcome
        onSignIn={() => void startSignIn()}
        signInBusy={signInState === "redirecting"}
        signInError={signInError}
      />
    );
  }

  return <AppStatus message="Checking your secure session…" />;
}

function LogoutRecovery({ session }: { session: ReturnType<typeof useSession> }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const retry = async () => {
    setBusy(true);
    try {
      const result = await session.logout();
      if (result.serverConfirmed) router.replace(isStandalonePwa() ? "/app" : "/");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="onboarding-handoff">
      <h1>Let’s finish signing you out</h1>
      <p role="alert">We couldn’t confirm sign-out with the server. Your account may still be signed in on this browser.</p>
      <button type="button" disabled={busy} onClick={() => void retry().catch(() => undefined)}>
        {busy ? "Signing out…" : "Retry sign out"}
      </button>
    </main>
  );
}

function AppStatus({
  message,
  action,
}: {
  message: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <main className={styles.statusPage}>
      <div className={styles.statusContent}>
        <p role="status" aria-live="polite">
          {message}
        </p>
        {action ? (
          <button type="button" onClick={action.onClick}>
            {action.label}
          </button>
        ) : null}
      </div>
    </main>
  );
}
