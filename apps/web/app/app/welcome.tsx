"use client";

import Image from "next/image";
import Link from "next/link";

import styles from "./app.module.css";

const FACE_ARTWORK = {
  blue: { color: "#3446E9", src: "/ally/idle/idle_rolly.reduced.svg" },
  yellow: { color: "#FBE65F", src: "/ally/idle/idle_boxy.reduced.svg" },
  green: { color: "#12C25B", src: "/ally/idle/idle_rocky.reduced.svg" },
  red: { color: "#FD304F", src: "/ally/idle/idle_ghosty.reduced.svg" },
} as const;

export function Welcome({
  onSignIn,
  signInBusy = false,
  signInError = null,
}: {
  onSignIn: () => void;
  signInBusy?: boolean;
  signInError?: string | null;
}) {
  return (
    <main className={styles.page} aria-labelledby="app-welcome-title">
      <div className={styles.artboard}>
        <h1 id="app-welcome-title" className={styles.visuallyHidden}>
          Welcome to Allies
        </h1>
        <WelcomeArtwork />
        <div className={styles.actions}>
          <Link href="/onboarding" className={styles.primaryCta}>
            Make your first ally
          </Link>
          <p className={styles.signInPrompt}>
            <button
              type="button"
              className={styles.signInButton}
              onClick={onSignIn}
              disabled={signInBusy}
              aria-busy={signInBusy}
              aria-label="Continue with Google"
              aria-describedby={signInError ? "app-sign-in-error" : undefined}
              title={signInBusy ? "Opening Google…" : "Continue with Google"}
            >
              {signInBusy ? "Opening Google…" : "Continue with Google"}
            </button>
          </p>
          {signInError ? (
            <p id="app-sign-in-error" className={styles.signInError} role="alert">
              {signInError}
            </p>
          ) : null}
        </div>
      </div>
    </main>
  );
}

function WelcomeArtwork() {
  return (
    <div className={styles.artwork} aria-hidden="true">
      <AllyBadge kind="yellow" className={styles.yellowAlly} />
      <AllyBadge kind="blue" className={styles.blueAlly} />
      <AllyBadge kind="green" className={styles.greenAlly} flippedCursor />
      <AllyBadge kind="red" className={styles.redAlly} />
      <Image
        src="/allies-icon.svg"
        alt=""
        width={89}
        height={86}
        className={styles.centralIcon}
        priority
      />
    </div>
  );
}

function AllyBadge({
  kind,
  className,
  flippedCursor = false,
}: {
  kind: keyof typeof FACE_ARTWORK;
  className: string;
  flippedCursor?: boolean;
}) {
  const artwork = FACE_ARTWORK[kind];

  return (
    <div className={`${styles.ally} ${className}`}>
      <div className={styles.face} style={{ backgroundColor: artwork.color }}>
        <Image
          src={artwork.src}
          alt=""
          width={470}
          height={470}
          className={styles.faceArtwork}
          draggable={false}
        />
      </div>
      <CursorMark color={artwork.color} flipped={flippedCursor} />
    </div>
  );
}

function CursorMark({ color, flipped }: { color: string; flipped: boolean }) {
  return (
    <div className={`${styles.cursor} ${flipped ? styles.flippedCursor : ""}`}>
      <div className={styles.cursorInner}>
        <svg
          width="28.0348114601603"
          height="28.03479203818092"
          viewBox="0 0 28.0348114601603 28.03479203818092"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          preserveAspectRatio="none"
          className={styles.cursorSvg}
        >
          <path
            d="M25.8723 8.1633C28.7683 9.2356 28.7523 13.3397 25.8445 14.3857L17.6873 17.3219C17.5143 17.3847 17.3813 17.5195 17.3221 17.6847L14.3844 25.8445C13.3383 28.7519 9.2337 28.7685 8.1614 25.8727L0.2632 4.6066C0.225 4.5034 0.1859 4.4006 0.1532 4.2955-0.639 1.755 1.7753-0.6558 4.3218 0.1625 4.4342 0.1986 4.5445 0.2414 4.6553 0.2824L25.8723 8.1633Z"
            transform=" translate(0 3.2018006024259194e-9)"
            fill={color}
            fillRule="nonzero"
          />
        </svg>
      </div>
    </div>
  );
}
