"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { isCloudError } from "@allies/cloud-client";

import { useSession } from "../../lib/session/session-context";

import styles from "./claim-invite.module.css";

type ClaimInviteState = "idle" | "submitting" | "success" | "error";

function claimInviteErrorMessage(error: unknown): string {
  if (isCloudError(error)) {
    if (error.code === "invite_unavailable" || error.kind === "conflict") {
      return "This invite is unavailable. Check the code or contact the person who invited you.";
    }
    if (error.kind === "validation" || error.kind === "bad-request") {
      return "Enter a valid invite code and email address.";
    }
    if (error.kind === "throttled") {
      return "Too many attempts. Wait a moment and try again.";
    }
    if (error.kind === "security") {
      return "We couldn't complete that securely. Try again.";
    }
    if (error.kind === "network" || error.kind === "timeout" || error.kind === "server") {
      return "Invite claiming is temporarily unavailable. Check your connection and try again.";
    }
  }

  return "We couldn't claim that invite. Try again.";
}

function returnLink(path: string, returnTo: string): string {
  return `${path}?returnTo=${encodeURIComponent(returnTo)}`;
}

export function ClaimInviteClient({ returnTo }: { returnTo: string }) {
  const { client, runCloudOperation } = useSession();
  const [code, setCode] = useState("");
  const [email, setEmail] = useState("");
  const [state, setState] = useState<ClaimInviteState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const requestGeneration = useRef(0);

  useEffect(() => () => {
    requestGeneration.current += 1;
    controllerRef.current?.abort();
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (state === "submitting") return;

    const normalizedCode = code.trim();
    const normalizedEmail = email.trim();
    if (!normalizedCode || normalizedCode.length > 128 || !normalizedEmail) {
      setState("error");
      setErrorMessage("Enter a valid invite code and email address.");
      return;
    }

    const controller = new AbortController();
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    controllerRef.current = controller;
    setState("submitting");
    setErrorMessage(null);

    try {
      await runCloudOperation(
        (signal) => client.claimInvite({ code: normalizedCode, email: normalizedEmail }, { signal }),
        { csrf: true, signal: controller.signal },
      );
      if (controller.signal.aborted || generation !== requestGeneration.current) return;
      setCode("");
      setState("success");
    } catch (error) {
      if (controller.signal.aborted || generation !== requestGeneration.current) return;
      setState("error");
      setErrorMessage(claimInviteErrorMessage(error));
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  };

  const signInHref = returnLink("/sign-in", returnTo);

  if (state === "success") {
    return (
      <main className={styles.page}>
        <div className={styles.shell}>
          <section className={`${styles.panel} ph-no-capture`} aria-labelledby="claim-invite-success-title">
            <div className={styles.mark} aria-hidden="true">✦</div>
            <p className={styles.eyebrow}>Invite claimed</p>
            <h1 id="claim-invite-success-title">You’re ready to continue</h1>
            <p className={styles.copy}>
              Your invite is ready for <span className={styles.privateEmail}>{email}</span>. Continue with the Google account that uses this email.
            </p>
            <Link className={styles.primaryAction} href={signInHref}>Continue with Google</Link>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <section className={`${styles.panel} ph-no-capture`} aria-labelledby="claim-invite-title">
          <div className={styles.mark} aria-hidden="true">✦</div>
          <p className={styles.eyebrow}>Beta access</p>
          <h1 id="claim-invite-title">Claim your invite</h1>
          <p className={styles.copy}>
            Enter the code you received and the email for the Google account you’ll use with Allies.
          </p>

          <form className={styles.form} onSubmit={(event) => void submit(event)}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="invite-code">Invite code</label>
              <input
                id="invite-code"
                name="code"
                className={styles.input}
                value={code}
                disabled={state === "submitting"}
                onChange={(event) => {
                  setCode(event.target.value);
                  setErrorMessage(null);
                  if (state === "error") setState("idle");
                }}
                autoComplete="off"
                spellCheck={false}
                maxLength={128}
                required
                aria-invalid={Boolean(errorMessage)}
                aria-describedby={errorMessage ? "claim-invite-error" : undefined}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="invite-email">Email for Google sign-in</label>
              <input
                id="invite-email"
                name="email"
                type="email"
                className={styles.input}
                value={email}
                disabled={state === "submitting"}
                onChange={(event) => {
                  setEmail(event.target.value);
                  setErrorMessage(null);
                  if (state === "error") setState("idle");
                }}
                autoComplete="email"
                maxLength={254}
                required
                aria-invalid={Boolean(errorMessage)}
                aria-describedby={errorMessage ? "claim-invite-error" : undefined}
              />
            </div>
            <button type="submit" className={styles.primaryAction} disabled={state === "submitting"}>
              {state === "submitting" ? "Checking your invite…" : "Claim invite"}
            </button>
            <p className={styles.status} role="status" aria-live="polite" aria-atomic="true">
              {state === "submitting" ? "Checking your invite…" : null}
            </p>
            {errorMessage ? <p id="claim-invite-error" className={styles.error} role="alert">{errorMessage}</p> : null}
          </form>

          <Link className={styles.secondaryAction} href={signInHref}>Already have an account? Sign in</Link>
        </section>
      </div>
    </main>
  );
}
