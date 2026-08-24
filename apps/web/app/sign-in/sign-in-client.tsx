"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { isCloudError } from "@allies/cloud-client";
import { AllyAvatar } from "../../components/ally-avatar";
import { useSession } from "../../lib/session/session-context";

import styles from "./sign-in.module.css";

type SignInState = "idle" | "redirecting" | "error";

function signInErrorMessage(error: unknown): string {
  if (isCloudError(error)) {
    if (error.code === "provider_unavailable" || error.kind === "not-found") {
      return "Google sign-in is temporarily unavailable. Try again.";
    }
    if (error.kind === "security") {
      return "We couldn't start sign-in securely. Try again.";
    }
    if (error.kind === "network" || error.kind === "server" || error.kind === "timeout") {
      return "Allies couldn't reach sign-in. Check your connection and try again.";
    }
  }

  return "We couldn't start sign-in. Try again.";
}

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

function SignInArtwork() {
  return (
    <div className={styles.artwork} aria-hidden="true">
      <div className={`${styles.orbit} ${styles.orbitBlue}`}>
        <AllyAvatar shape="ghosty" color="#0d92fd" size={52} motion="system" />
      </div>
      <div className={`${styles.orbit} ${styles.orbitYellow}`}>
        <AllyAvatar shape="rolly" color="#f5700a" size={44} motion="system" />
      </div>
      <div className={`${styles.orbit} ${styles.orbitRed}`}>
        <AllyAvatar shape="rocky" color="#fd304f" size={50} motion="system" />
      </div>
      <div className={styles.heroAlly}>
        <AllyAvatar shape="ghosty" color="#ff5800" size="clamp(132px, 20vw, 196px)" motion="system" />
      </div>
      <span className={styles.artworkCaption}>A little help, right when you need it.</span>
    </div>
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
      setErrorMessage(signInErrorMessage(error));
      window.requestAnimationFrame(() => buttonRef.current?.focus());
    }
  };

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <SignInArtwork />
        <section className={styles.panel} aria-labelledby="sign-in-title">
          <Link className={styles.backLink} href="/">
            <span aria-hidden="true">←</span> Back to Allies
          </Link>
          <div className={styles.panelCopy}>
            <p className={styles.eyebrow}>Your personal allies</p>
            <h1 id="sign-in-title">Sign in to continue</h1>
            <p className={styles.description}>
              Pick up where you left off with the helpers built around what matters to you.
            </p>
          </div>
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
          <p className={styles.privacyNote}>Google is the only sign-in option for Allies.</p>
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
