"use client";

import { useRef, useState } from "react";
import { motion } from "motion/react";
import Image from "next/image";

import { type AllyShape } from "@/components/ally-avatar";
import { useSession } from "../../../lib/session/session-context";
import { googleSignInErrorMessage } from "../../../lib/session/sign-in-errors";
import { ONBOARDING_GOOGLE_RETURN_TO } from "../_store/onboarding-resume";
import {
  AUTH_SIGNUP_ALLY_LAYOUT_ID,
  PersistentAllyAvatar,
} from "./persistent-ally";

export function AuthOverlay({
  shape,
  color,
  onClose,
  onSignUp,
  onPrepareGoogleSignIn,
}: {
  shape: AllyShape;
  color: string;
  onClose: () => void;
  onSignUp: (provider: "chatgpt" | "google") => void;
  onPrepareGoogleSignIn: () => void;
}) {
  const { client, runCloudOperation } = useSession();
  const googleButtonRef = useRef<HTMLButtonElement>(null);
  const [googleState, setGoogleState] = useState<"idle" | "redirecting" | "error">("idle");
  const [googleError, setGoogleError] = useState<string | null>(null);
  const redirecting = googleState === "redirecting";

  const startGoogleSignIn = async () => {
    if (redirecting) return;

    onPrepareGoogleSignIn();
    setGoogleState("redirecting");
    setGoogleError(null);

    try {
      const redirectUrl = await runCloudOperation(
        (signal) => client.beginSignIn(ONBOARDING_GOOGLE_RETURN_TO, signal),
        { csrf: true },
      );
      window.location.assign(redirectUrl);
    } catch (error) {
      setGoogleState("error");
      setGoogleError(googleSignInErrorMessage(error));
      window.requestAnimationFrame(() => googleButtonRef.current?.focus());
    }
  };

  return (
    <motion.div
      key="auth-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="auth-allies-title"
      data-testid="auth-allies-2"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      className="waitlist-auth-overlay"
    >
      <motion.div
        className="waitlist-auth-card"
        initial={{ y: 28, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: 16, opacity: 0 }}
        transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="waitlist-auth-heading-block">
          <PersistentAllyAvatar
            shape={shape}
            color={color}
            state="idle"
            size={61.6}
            frameSize={{ width: 61.6, height: 60 }}
            layoutId={AUTH_SIGNUP_ALLY_LAYOUT_ID}
            layoutMode="full"
            motionMode="system"
            label="Your Ally"
          />
          <h2 id="auth-allies-title" className="waitlist-auth-title">
            Create your
            <br />
            account
          </h2>
        </div>

        <button
          type="button"
          aria-label="Close"
          data-testid="auth-overlay-close"
          onClick={onClose}
          disabled={redirecting}
          className="waitlist-auth-close"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
            <path
              d="M0.86 10.49L5.24 5.24M10.49 0.86L5.24 5.24M5.24 5.24L0.86 0.86M5.24 5.24L10.49 10.49"
              stroke="#fff"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>

        <p className="waitlist-auth-body">
          Your ally has been saved but you need to set up an account to use it.
        </p>

        <div className="waitlist-auth-actions">
          <button
            type="button"
            data-testid="signup-chatgpt"
            onClick={() => onSignUp("chatgpt")}
            disabled={redirecting}
            className="waitlist-auth-provider"
          >
            <Image src="/ally/icons/auth-chatgpt.svg" alt="" width={24} height={24} />
            <span>Sign up with ChatGPT</span>
          </button>
          <button
            ref={googleButtonRef}
            type="button"
            data-testid="signup-google"
            onClick={() => void startGoogleSignIn()}
            disabled={redirecting}
            aria-describedby={googleError ? "auth-google-error" : undefined}
            className="waitlist-auth-provider"
          >
            <Image src="/ally/icons/auth-google.svg" alt="" width={24} height={24} />
            <span>{redirecting ? "Opening Google…" : "Sign up with Google"}</span>
          </button>
        </div>

        {googleError ? (
          <p id="auth-google-error" className="waitlist-auth-error" role="alert">
            {googleError}
          </p>
        ) : null}

        <p className="waitlist-auth-legal">
          By continuing, you agree to our <span>Terms of Service</span> and have
          read our <span>Privacy Policy</span>
        </p>
      </motion.div>
    </motion.div>
  );
}
