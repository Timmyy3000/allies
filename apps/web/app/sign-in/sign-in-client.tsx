"use client";

import { useRef, useState } from "react";

import { useSession } from "../../lib/session/session-context";
import { googleSignInErrorMessage } from "../../lib/session/sign-in-errors";

import styles from "./sign-in.module.css";

type SignInState = "idle" | "redirecting" | "error";

function GoogleMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" className={styles.googleMark}>
      <path fill="#4285F4" d="M23.49 12.27c0-.79-.07-1.55-.2-2.27H12v4.3h6.44a5.5 5.5 0 0 1-2.39 3.61v3h3.87c2.27-2.09 3.57-5.17 3.57-8.64Z" />
      <path fill="#34A853" d="M12 24c3.24 0 5.95-1.07 7.93-2.91l-3.87-3A7.18 7.18 0 0 1 12 19.2a7.2 7.2 0 0 1-6.77-4.98H1.23v3.1A12 12 0 0 0 12 24Z" />
      <path fill="#FBBC05" d="M5.23 14.22a7.2 7.2 0 0 1 0-4.44v-3.1H1.23a12 12 0 0 0 0 10.64l4-3.1Z" />
      <path fill="#EA4335" d="M12 4.8a6.52 6.52 0 0 1 4.6 1.8l3.45-3.45A12 12 0 0 0 1.23 6.68l4 3.1A7.2 7.2 0 0 1 12 4.8Z" />
    </svg>
  );
}

export function SignInClient({ returnTo }: { returnTo: string }) {
  const { client, runCloudOperation } = useSession();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [state, setState] = useState<SignInState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const startSignIn = async () => {
    if (state === "redirecting") return;

    setState("redirecting");
    setErrorMessage(null);

    try {
      const redirectUrl = await runCloudOperation(
        (signal) => client.beginSignIn(returnTo, signal),
        { csrf: true },
      );
      window.location.assign(redirectUrl);
    } catch (error) {
      setState("error");
      setErrorMessage(googleSignInErrorMessage(error));
      window.requestAnimationFrame(() => buttonRef.current?.focus());
    }
  };

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <section className={styles.panel} aria-label="Google sign-in">
          <button
            ref={buttonRef}
            type="button"
            className={styles.googleButton}
            onClick={() => void startSignIn()}
            disabled={state === "redirecting"}
            aria-describedby={errorMessage ? "sign-in-error" : undefined}
          >
            <GoogleMark />
            <span>{state === "redirecting" ? "Opening Google…" : "Continue with Google"}</span>
          </button>
          <div className={styles.statusRegion} aria-live="polite" aria-atomic="true">
            {state === "redirecting" ? "Opening a secure Google sign-in…" : null}
          </div>
          {errorMessage ? (
            <p id="sign-in-error" className={styles.error} role="alert">
              {errorMessage}
            </p>
          ) : null}
        </section>
      </div>
    </main>
  );
}
