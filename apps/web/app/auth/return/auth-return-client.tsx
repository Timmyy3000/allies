"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

import { resolvePostAuthPath } from "../../(onboarding)/_store/onboarding-resume";
import { useSession } from "../../../lib/session/session-context";
import type { AuthReturnErrorCode } from "../../../lib/session/auth-route-query";

import styles from "./auth-return.module.css";

function authReturnErrorMessage(errorCode?: AuthReturnErrorCode): string | null {
  switch (errorCode) {
    case "access_denied":
    case "provider_denied":
      return "Google sign-in was cancelled.";
    case "provider_unavailable":
      return "Google sign-in is temporarily unavailable. Try again.";
    case "invalid_state":
      return "That sign-in attempt expired. Start again to continue.";
    case "origin_rejected":
    case "csrf_rejected":
      return "We couldn't complete sign-in securely. Try again.";
    default:
      return null;
  }
}

function ReturnShell({ children }: { children: React.ReactNode }) {
  return (
    <main className={styles.page}>
      <section className={styles.card} aria-labelledby="return-title">
        <div className={styles.mark} aria-hidden="true">✦</div>
        {children}
      </section>
    </main>
  );
}

function InviteRequiredRecovery({ returnTo }: { returnTo: string }) {
  const claimHref = `/claim-invite?returnTo=${encodeURIComponent(returnTo)}`;
  const signInHref = `/sign-in?returnTo=${encodeURIComponent(returnTo)}`;

  return (
    <ReturnShell>
      <p id="return-title" className={styles.eyebrow}>Invite required</p>
      <h1>You’ll need a beta invite</h1>
      <p className={styles.copy} role="alert">
        You’ll need a beta invite to create an account. Claim it using the email for your Google account.
      </p>
      <div className={styles.actions}>
        <Link className={styles.retryButton} href={claimHref}>Claim an invite</Link>
        <Link className={styles.signInLink} href={signInHref}>Sign in again</Link>
      </div>
    </ReturnShell>
  );
}

export function AuthReturnClient({
  returnTo,
  errorCode,
}: {
  returnTo: string;
  errorCode?: AuthReturnErrorCode;
}) {
  const { state, restore } = useSession();
  const router = useRouter();
  const initialRestoreStarted = useRef(false);
  const redirectStarted = useRef(false);
  const callbackError = authReturnErrorMessage(errorCode);

  useEffect(() => {
    if (initialRestoreStarted.current) return;
    initialRestoreStarted.current = true;
    void restore();
  }, [restore]);

  useEffect(() => {
    if (state.status !== "signed-in" || redirectStarted.current) return;
    redirectStarted.current = true;
    router.replace(resolvePostAuthPath(returnTo));
  }, [returnTo, router, state.status]);

  if (state.status === "unknown" || state.status === "restoring") {
    return (
      <ReturnShell>
        <p id="return-title" className={styles.eyebrow}>One moment</p>
        <h1>Returning you to Allies</h1>
        <p className={styles.copy}>We’re checking your secure session before opening your account.</p>
        <p className={styles.status} role="status" aria-live="polite">Restoring your session…</p>
      </ReturnShell>
    );
  }

  if (state.status === "signed-in") {
    return (
      <ReturnShell>
        <p id="return-title" className={styles.eyebrow}>Ready</p>
        <h1>Opening your account</h1>
        <p className={styles.copy} role="status" aria-live="polite">Taking you there now…</p>
      </ReturnShell>
    );
  }

  if (errorCode === "invite_required") {
    return <InviteRequiredRecovery returnTo={returnTo} />;
  }

  const settledMessage = callbackError ?? (
    state.status === "unavailable"
      ? "We couldn’t restore your session right now. Try again when you’re ready."
      : "We couldn’t complete sign-in. Start again to continue."
  );

  return (
    <ReturnShell>
      <p id="return-title" className={styles.eyebrow}>Sign-in didn’t finish</p>
      <h1>Let’s try that again</h1>
      <p className={styles.copy} role="alert">{settledMessage}</p>
      <div className={styles.actions}>
        <button type="button" className={styles.retryButton} onClick={() => void restore()}>
          Try again
        </button>
        <Link className={styles.signInLink} href={`/sign-in?returnTo=${encodeURIComponent(returnTo)}`}>
          Sign in again
        </Link>
      </div>
    </ReturnShell>
  );
}
