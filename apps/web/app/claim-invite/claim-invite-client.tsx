"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { OTPInput } from "input-otp";
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
    if (
      error.kind === "network" ||
      error.kind === "timeout" ||
      error.kind === "server"
    ) {
      return "Invite claiming is temporarily unavailable. Check your connection and try again.";
    }
  }

  return "We couldn't claim that invite. Try again.";
}

export function ClaimInviteClient() {
  const router = useRouter();
  const reducedMotion = useReducedMotion();
  const { client, runCloudOperation } = useSession();
  const [code, setCode] = useState("");
  const [email, setEmail] = useState("");
  const [state, setState] = useState<ClaimInviteState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const requestGeneration = useRef(0);

  useEffect(() => {
    if (state !== "success") return;
    const timeout = window.setTimeout(() => router.replace("/"), 1800);
    return () => window.clearTimeout(timeout);
  }, [state, router]);

  useEffect(
    () => () => {
      requestGeneration.current += 1;
      controllerRef.current?.abort();
    },
    [],
  );

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (state === "submitting" || state === "success") return;

    const normalizedCode = code.trim();
    const normalizedEmail = email.trim();
    if (!/^[A-Z2-7]{8}$/.test(normalizedCode) || !normalizedEmail) {
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
        (signal) =>
          client.claimInvite(
            { code: normalizedCode, email: normalizedEmail },
            { signal },
          ),
        { csrf: true, signal: controller.signal },
      );
      if (controller.signal.aborted || generation !== requestGeneration.current)
        return;
      setCode("");
      setState("success");
    } catch (error) {
      if (controller.signal.aborted || generation !== requestGeneration.current)
        return;
      setState("error");
      setErrorMessage(claimInviteErrorMessage(error));
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  };

  const completeCode = /^[A-Z2-7]{8}$/.test(code);
  const currentStep = state === "success" ? "success" : "claim";
  const transition = {
    duration: reducedMotion ? 0 : 0.22,
    ease: [0.22, 1, 0.36, 1] as const,
  };
  const successInitial = reducedMotion ? { opacity: 0 } : { opacity: 0, y: 6, scale: 0.98 };
  const successTransition = reducedMotion
    ? { duration: 0.2 }
    : { type: "spring" as const, duration: 0.45, bounce: 0.15 };

  return (
    <main className={styles.page}>
      <motion.section
        layout={!reducedMotion}
        transition={transition}
        className={`${styles.panel} ph-no-capture`}
        aria-labelledby="claim-invite-title"
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={currentStep}
            initial={currentStep === "success" ? successInitial : { opacity: 0, y: reducedMotion ? 0 : 8 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: reducedMotion ? 0 : -6 }}
            transition={currentStep === "success" ? successTransition : transition}
          >
            <h1 id="claim-invite-title">
              {currentStep === "success" ? "You're in" : "Claim your invite"}
            </h1>
            <p className={styles.copy}>
              {currentStep === "success"
                ? "Invite claimed. Taking you home…"
                : "Enter your invite code to get started."}
            </p>
            {currentStep === "success" ? (
              <motion.div
                className={styles.successAction}
                initial={successInitial}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ ...successTransition, delay: 0.06 }}
              >
                <Link href="/" className={styles.primaryAction}>
                  Go home
                </Link>
              </motion.div>
            ) : (
              <form
                className={styles.form}
                onSubmit={(event) => void submit(event)}
              >
                <label className={styles.status} htmlFor="invite-code">
                  Invite code
                </label>
                <OTPInput
                  id="invite-code"
                  value={code}
                  maxLength={8}
                  inputMode="text"
                  autoComplete="one-time-code"
                  pattern="^[a-zA-Z2-7]*$"
                  containerClassName={styles.codeInput}
                  onChange={(value) => {
                    setCode(value.toUpperCase());
                    setErrorMessage(null);
                  }}
                  disabled={state === "submitting"}
                  render={({ slots }) => (
                    <div className={styles.slots} aria-hidden="true">
                      {slots.map((slot, index) => (
                        <div
                          key={index}
                          className={styles.slot}
                          data-active={slot.isActive}
                          data-filled={Boolean(slot.char)}
                        >
                          {slot.char}
                          {slot.hasFakeCaret && (
                            <span className={styles.caret} />
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                />
                {errorMessage && (
                  <p
                    id="claim-invite-error"
                    className={styles.error}
                    role="alert"
                  >
                    {errorMessage}
                  </p>
                )}
                <AnimatePresence initial={false}>
                  {completeCode && (
                    <motion.div
                      className={styles.claimFields}
                      key="claim-fields"
                      initial={{
                        height: 0,
                        opacity: 0,
                        y: reducedMotion ? 0 : 12,
                      }}
                      animate={{ height: "auto", opacity: 1, y: 0 }}
                      exit={{
                        height: 0,
                        opacity: 0,
                        y: reducedMotion ? 0 : 12,
                      }}
                      transition={transition}
                      style={{ overflow: "hidden" }}
                    >
                      <div className={styles.field}>
                        <label className={styles.label} htmlFor="invite-email">
                          Email for Google sign-in
                        </label>
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
                          aria-describedby={
                            errorMessage ? "claim-invite-error" : undefined
                          }
                        />
                      </div>
                      <div className={styles.actions}>
                        <Link href="/" className={styles.secondaryAction}>
                          Home
                        </Link>
                        <button
                          type="submit"
                          className={styles.primaryAction}
                          disabled={state === "submitting" || !completeCode}
                        >
                          {state === "submitting"
                            ? "Claiming…"
                            : "Claim invite"}
                        </button>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </form>
            )}
          </motion.div>
        </AnimatePresence>
        <p className={styles.status} role="status" aria-live="polite">
          {state === "submitting"
            ? "Claiming your invite…"
            : state === "success"
              ? "Invite claimed. Taking you home."
              : null}
        </p>
      </motion.section>
    </main>
  );
}
