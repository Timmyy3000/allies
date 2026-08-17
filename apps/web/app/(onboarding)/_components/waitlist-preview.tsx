"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import Image from "next/image";
import { useEffect, useMemo, useRef, useState } from "react";

import { Artboard } from "@/components/artboard";
import { AllyAvatar } from "@/components/ally-avatar";
import { getAccentPalette, ONBOARDING_CTA } from "@/components/next-button";
import { ParticleText } from "@/components/text-animations/particle-text";
import { ShinyText } from "@/components/text-animations/shiny-text";
import { useOnboardingStore } from "../_store/onboarding-store";
import { WaitlistMappingError } from "../../../lib/waitlist/catalog";
import {
  serializeOnboardingConfiguration,
  useWaitlistFlow,
  waitlistGreetingFingerprint,
} from "../../../lib/waitlist/flow";
import {
  ONBOARDING_ALLY_LAYOUT_ID,
  PersistentAllyAvatar,
} from "./persistent-ally";

const HERO_SHELL_SIZE = 164.2;
const PREVIEW_SHELL_SIZE = 24;
const THINKING_SHELL_SIZE = 28;
const SURFACE_INSET = 20;

type PreviewPhase = "coming-alive" | "thinking" | "ready";

function MailboxIcon({ color }: { color: string }) {
  return (
    <svg
      aria-hidden="true"
      width="22"
      height="23"
      viewBox="0 0 22 23"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M7.33309 6.33337C7.33309 5.78109 5.11415 5.33337 5.66643 5.33337H15.6664C18.796 5.33337 21.3331 7.87043 21.3331 11V17.6667C21.3331 18.955 20.288 20 18.9998 20H5.66643C5.11415 20 7.33309 19.5523 7.33309 19V6.33337Z"
        fill={color}
        fillOpacity="0.4"
      />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M13.6665 0C13.1142 0 12.6665 0.447715 12.6665 1V2.66667V3V8.33333C12.6665 8.88561 13.1142 9.33333 13.6665 9.33333C14.2188 9.33333 14.6665 8.88561 14.6665 8.33333V4H17.6665C18.2188 4 18.6665 3.55228 18.6665 3V1C18.6665 0.447715 18.2188 0 17.6665 0H13.6665Z"
        fill={color}
      />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M5.66667 5.33337C2.53839 5.33337 0 7.87176 0 11V17.6667C0 18.955 1.04505 20 2.33333 20H9C9.11317 20 9.22447 19.992 9.33333 19.9764V21.6667C9.33333 22.219 9.78105 22.6667 10.3333 22.6667C10.8856 22.6667 11.3333 22.219 11.3333 21.6667V17.6667V17.3334V11C11.3333 7.87176 8.79495 5.33337 5.66667 5.33337ZM6.66667 11C6.66667 10.4478 6.21895 10 5.66667 10C5.11439 10 4.66667 10.4478 4.66667 11V13C4.66667 13.5523 5.11439 14 5.66667 14C6.21895 14 6.66667 13.5523 6.66667 13V11Z"
        fill={color}
      />
    </svg>
  );
}

function errorMessage(
  error: { fieldIssues?: Array<{ message?: string }>; code?: string } | null,
): string | null {
  if (!error) return null;
  return (
    error.fieldIssues?.find((issue) => issue.message)?.message ??
    "Something went wrong. Try again."
  );
}

export function WaitlistPreviewScreen() {
  const name = useOnboardingStore((state) => state.name);
  const shape = useOnboardingStore((state) => state.shape);
  const color = useOnboardingStore((state) => state.color);
  const job = useOnboardingStore((state) => state.job);
  const personalities = useOnboardingStore((state) => state.personalities);
  const personalityNote = useOnboardingStore((state) => state.personalityNote);
  const personalityRaw = useOnboardingStore((state) => state.personalityRaw);
  const [phase, setPhase] = useState<PreviewPhase>("coming-alive");
  const [replyDraft, setReplyDraft] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [showSaveModal, setShowSaveModal] = useState(false);
  const prefersReducedMotion = useReducedMotion() ?? false;
  const savedConfigurationRef = useRef<string | null>(null);
  const failedConfigurationRef = useRef<string | null>(null);
  const {
    snapshot,
    status,
    error,
    pendingAction,
    lastAction,
    saveConfiguration,
    recordReply,
    join,
    consentVersion,
    retry,
  } = useWaitlistFlow();

  const configuration = useMemo(() => {
    try {
      return {
        payload: serializeOnboardingConfiguration({
          name,
          shape,
          color,
          job,
          personalities,
          personalityNote,
          personalityOverride: personalityRaw ?? undefined,
        }),
        mappingError: null,
      };
    } catch (candidate) {
      const mappingError =
        candidate instanceof WaitlistMappingError
          ? candidate
          : new WaitlistMappingError(
              "configuration_invalid",
              "Check your Ally details and try again.",
            );
      return { payload: null, mappingError };
    }
  }, [color, job, name, personalities, personalityNote, personalityRaw, shape]);

  const localGreetingFingerprint = useMemo(
    () =>
      waitlistGreetingFingerprint(
        name,
        job,
        configuration.payload?.personality ?? null,
      ),
    [configuration.payload?.personality, job, name],
  );

  const configurationMatches = Boolean(
    snapshot &&
      configuration.payload &&
      snapshot.configuration.name === configuration.payload.name &&
      snapshot.configuration.appearanceCatalogVersion ===
        configuration.payload.appearance_catalog_version &&
      snapshot.configuration.appearanceKey === configuration.payload.appearance_key &&
      snapshot.configuration.job === configuration.payload.job &&
      (snapshot.configuration.personality ?? undefined) ===
        (configuration.payload.personality ?? undefined),
  );
  const greetingIsCurrent = Boolean(
    snapshot?.greeting &&
      waitlistGreetingFingerprint(
        snapshot.configuration.name ?? "",
        snapshot.configuration.job ?? "",
        snapshot.configuration.personality,
      ) === localGreetingFingerprint,
  );

  useEffect(() => {
    const delay = prefersReducedMotion ? 0 : 2_400;
    const timer = window.setTimeout(() => setPhase("thinking"), delay);
    return () => window.clearTimeout(timer);
  }, [prefersReducedMotion]);

  useEffect(() => {
    if (status !== "ready" || !snapshot || !configuration.payload || pendingAction) {
      return;
    }

    const configurationKey = JSON.stringify(configuration.payload);
    if (configurationMatches) {
      savedConfigurationRef.current = configurationKey;
      failedConfigurationRef.current = null;
    }

    if (
      !configurationMatches &&
      savedConfigurationRef.current !== configurationKey &&
      failedConfigurationRef.current !== configurationKey
    ) {
      void saveConfiguration(configuration.payload)
        .then(() => {
          savedConfigurationRef.current = configurationKey;
          failedConfigurationRef.current = null;
        })
        .catch(() => {
          failedConfigurationRef.current = configurationKey;
        });
      return;
    }

  }, [
    configuration.payload,
    configurationMatches,
    greetingIsCurrent,
    localGreetingFingerprint,
    pendingAction,
    saveConfiguration,
    snapshot,
    status,
  ]);

  const replyText = replyDraft ?? snapshot?.reply?.text ?? "";
  const isBusy = pendingAction !== null;
  const message =
    errorMessage(error) ?? configuration.mappingError?.message ?? null;
  const displayPhase = phase === "thinking" && greetingIsCurrent ? "ready" : phase;
  const shouldShowGreeting = displayPhase === "ready" && greetingIsCurrent;
  const joinedEmail = snapshot?.join?.email ?? null;
  const palette = getAccentPalette(color);
  const { accent } = palette;

  if (phase === "coming-alive") {
    return (
      <Artboard>
        <div
          data-testid="coming-alive"
          className="onboarding-page onboarding-coming-alive-page"
        >
          <motion.div
            className="onboarding-coming-alive-content"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.46, ease: [0.22, 1, 0.36, 1] }}
          >
            <PersistentAllyAvatar
              shape={shape}
              color={accent}
              size={HERO_SHELL_SIZE}
              layoutMode="full"
              pulse={!prefersReducedMotion}
              motionMode="system"
              label={`${name || "Your"} Ally`}
            />
            <ParticleText
              text="Coming alive...."
              color="#121212"
              className="onboarding-coming-alive-text"
            />
          </motion.div>
        </div>
      </Artboard>
    );
  }

  if (joinedEmail) {
    const friends = [
      { shape: "rocky" as const, color: "#12c25b", offset: 12 },
      { shape: "boxy" as const, color: "#3446e9", offset: 28 },
      { shape: "ghosty" as const, color: "#fd304f", offset: 0 },
    ];

    return (
      <Artboard>
        <motion.main
          data-testid="waitlist-complete"
          className="onboarding-page waitlist-complete-page"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
        >
          <div className="waitlist-complete-content">
            <div className="waitlist-complete-friends" aria-hidden="true">
              {friends.map((ally, index) => (
                <motion.div
                  key={ally.shape}
                  animate={
                    prefersReducedMotion
                      ? undefined
                      : { y: [ally.offset, ally.offset - 5, ally.offset] }
                  }
                  transition={{
                    duration: 2.4,
                    repeat: Infinity,
                    delay: index * 0.16,
                    ease: "easeInOut",
                  }}
                >
                  <AllyAvatar
                    shape={ally.shape}
                    color={ally.color}
                    size={44}
                    motion="reduced"
                  />
                </motion.div>
              ))}
            </div>
            <h1>See you soon</h1>
            <a
              className="waitlist-complete-follow"
              href="https://x.com/allies_ai"
              target="_blank"
              rel="noreferrer"
              style={{ backgroundColor: accent }}
            >
              <span>Follow us on</span>
              <Image src="/ally/icons/x-social.svg" alt="X" width={18} height={18} />
            </a>
          </div>
        </motion.main>
      </Artboard>
    );
  }

  return (
    <Artboard>
      <div
        data-testid="waitlist-preview"
        className="onboarding-page onboarding-overlay-host"
      >
        <header
          className="waitlist-preview-header"
        >
          <AnimatePresence initial={false}>
            {shouldShowGreeting ? (
              <motion.div
                key="conversation-identity"
                className="waitlist-preview-identity"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
              >
                <PersistentAllyAvatar
                  shape={shape}
                  color={accent}
                  state="idle"
                  size={PREVIEW_SHELL_SIZE}
                  layoutId={ONBOARDING_ALLY_LAYOUT_ID}
                  layoutMode="full"
                  motionMode="system"
                  label={`${name || "Your"} Ally`}
                />
                <motion.h1
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.08, duration: 0.2, ease: "easeOut" }}
                  style={{
                    margin: 0,
                    color: "#121212",
                    fontSize: 14,
                    fontWeight: 600,
                    letterSpacing: -0.45,
                    lineHeight: "18px",
                  }}
                >
                  {name || "Your Ally"}
                </motion.h1>
              </motion.div>
            ) : null}
          </AnimatePresence>
        </header>

        <main
          className="waitlist-preview-main"
        >
          <AnimatePresence initial={false} mode="wait">
            {shouldShowGreeting ? (
              <motion.article
                key="greeting"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                style={{
                  color: "#121212",
                  fontSize: 16,
                  fontWeight: 500,
                  letterSpacing: -0.48,
                  lineHeight: "22px",
                  whiteSpace: "pre-wrap",
                }}
              >
                {snapshot?.greeting?.text}
              </motion.article>
            ) : (
              <motion.div
                key="thinking-copy"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                style={{ minHeight: 90 }}
              />
            )}
          </AnimatePresence>

          {message ? (
            <p
              role="status"
              style={{
                margin: "18px 0 0",
                color: "#b8203d",
                fontSize: 14,
                lineHeight: "20px",
              }}
            >
              {message}
            </p>
          ) : null}
        </main>

        <div
          className="waitlist-preview-footer"
        >
          <div
            className="waitlist-preview-status-row"
          >
            <AnimatePresence initial={false} mode="popLayout">
              {!shouldShowGreeting ? (
                <motion.div
                  key="thinking-status"
                  data-testid="thinking-status"
                  aria-live="polite"
                  className="waitlist-preview-status"
                  initial={{ opacity: 1 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.18, ease: "easeOut" }}
                  style={{ color: accent }}
                >
                  <PersistentAllyAvatar
                    shape={shape}
                    color={accent}
                    state="thinking"
                    size={THINKING_SHELL_SIZE}
                    layoutId={ONBOARDING_ALLY_LAYOUT_ID}
                    layoutMode="full"
                    motionMode="system"
                  />
                  <ShinyText color={accent} shineColor="#ffffff">
                    Thinking
                  </ShinyText>
                </motion.div>
              ) : null}
            </AnimatePresence>
            {lastAction ? (
              <button
                type="button"
                onClick={() => void retry()}
                disabled={isBusy}
            style={{
              color: accent,
            }}
            className="waitlist-preview-retry"
              >
                Try again
              </button>
            ) : null}
          </div>

          <form
            className="waitlist-preview-composer"
            onSubmit={(event) => {
              event.preventDefault();
              if (
                !isBusy &&
                status === "ready" &&
                configurationMatches &&
                replyText.trim() &&
                !snapshot?.reply
              ) {
                const reply = replyText.trim();
                void recordReply(reply)
                  .then(() => setShowSaveModal(true))
                  .catch(() => undefined);
              }
            }}
          >
          <input
            aria-label="Reply to your Ally"
            data-testid="waitlist-reply"
            value={replyText}
            onChange={(event) => setReplyDraft(event.target.value)}
            placeholder={`Reply ${name || "your Ally"}`}
            maxLength={4000}
            disabled={isBusy || Boolean(snapshot?.reply)}
            className="waitlist-preview-composer-input"
          />
          <button
            type="submit"
            aria-label="Send reply"
            disabled={
              isBusy ||
              status !== "ready" ||
              !configurationMatches ||
              !replyText.trim() ||
              !snapshot ||
              Boolean(snapshot.reply)
            }
            className="waitlist-preview-send"
            style={{
              background: replyText.trim() ? accent : "#a8a8a8",
              cursor: replyText.trim() ? "pointer" : "default",
            }}
          >
            <Image src="/ally/icons/send.svg" alt="" width={18} height={18} />
          </button>
          </form>
        </div>

        <AnimatePresence initial={false}>
          {showSaveModal ? (
            <motion.div
              key="save-modal"
              role="dialog"
              aria-modal="true"
              aria-label="Save your ally"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              style={{
                position: "absolute",
                inset: 0,
                zIndex: 5,
                display: "flex",
                alignItems: "flex-end",
                boxSizing: "border-box",
                padding: SURFACE_INSET,
                background: "rgba(0, 0, 0, 0.24)",
              }}
            >
              <motion.div
                initial={{ y: 36, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                exit={{ y: 24, opacity: 0 }}
                transition={{ type: "spring", stiffness: 260, damping: 26 }}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  width: "100%",
                  minHeight: 300,
                  maxHeight: "100%",
                  overflowY: "auto",
                  padding: "24px 20px 28px",
                  borderRadius: 24,
                  background: "#fff",
                  boxSizing: "border-box",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    minHeight: 32,
                    alignItems: "center",
                    justifyContent: "flex-end",
                    marginBottom: 8,
                  }}
                >
                  <button
                    type="button"
                    aria-label="Close save Ally dialog"
                    onClick={() => setShowSaveModal(false)}
                    style={{
                      width: 32,
                      height: 32,
                      display: "grid",
                      placeItems: "center",
                      border: 0,
                      borderRadius: "50%",
                      padding: 0,
                      background: "#121212",
                      cursor: "pointer",
                    }}
                  >
                    <Image src="/ally/icons/x.svg" alt="" width={24} height={24} />
                  </button>
                </div>

                <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      if (
                        !isBusy &&
                        status === "ready" &&
                        configurationMatches &&
                        email.trim() &&
                        consentVersion
                      ) {
                        void join(email.trim())
                          .then(() => {
                            setReplyDraft(null);
                          })
                          .catch(() => undefined);
                      }
                    }}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 12,
                    }}
                  >
                    <div
                      aria-hidden="true"
                      style={{
                        width: 40,
                        height: 40,
                        display: "grid",
                        placeItems: "center",
                        borderRadius: "50%",
                        background: palette.softStrong,
                      }}
                    >
                      <MailboxIcon color={accent} />
                    </div>
                    <h2
                      style={{
                        margin: 0,
                        color: "#121212",
                        fontSize: 24,
                        fontWeight: 700,
                        letterSpacing: -1,
                        lineHeight: "100%",
                      }}
                    >
                      Save
                      <br />
                      your ally
                    </h2>
                    <p
                      style={{
                        margin: 0,
                        color: "#121212",
                        fontSize: 14,
                        fontWeight: 500,
                        letterSpacing: -0.35,
                        lineHeight: "19px",
                      }}
                    >
                      allies isn&apos;t live yet. Enter your email to save the ally you&apos;ve shaped and its first message.
                    </p>
                    <input
                      data-testid="waitlist-email"
                      aria-label="Email address"
                      type="email"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      placeholder="Email address"
                      style={{
                        width: "100%",
                        height: ONBOARDING_CTA.height,
                        boxSizing: "border-box",
                        border: 0,
                        borderRadius: 999,
                        padding: "0 16px",
                        background: "#f3f3f3",
                        outline: "none",
                        color: "#121212",
                        font: "inherit",
                        fontSize: 14,
                      }}
                    />
                    <button
                      type="submit"
                      data-testid="waitlist-submit"
                      disabled={
                        isBusy ||
                        status !== "ready" ||
                        !configurationMatches ||
                        !email.trim() ||
                        !consentVersion
                      }
                      style={{
                        width: "100%",
                        height: ONBOARDING_CTA.height,
                        border: 0,
                        borderRadius: 60,
                        boxSizing: "border-box",
                        padding: ONBOARDING_CTA.padding,
                        background: email.trim() && consentVersion ? accent : "#d9d9d9",
                        color: "#fff",
                        font: "inherit",
                        fontSize: 18,
                        fontWeight: 600,
                        letterSpacing: -0.7,
                        cursor: email.trim() && consentVersion ? "pointer" : "default",
                      }}
                    >
                      {pendingAction === "join" ? "Saving…" : "Submit"}
                    </button>
                    <p
                      style={{
                        margin: 0,
                        color: "#a0a0a0",
                        fontSize: 11,
                        lineHeight: "15px",
                        textAlign: "center",
                      }}
                    >
                      By joining the waitlist, you consent to us contacting you about our release and availability.
                    </p>
                </form>
              </motion.div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </Artboard>
  );
}
