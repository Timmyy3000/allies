"use client";

import {
  AnimatePresence,
  motion,
  useAnimationFrame,
  useMotionValue,
  useReducedMotion,
} from "motion/react";
import Image from "next/image";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import { Artboard } from "@/components/artboard";
import { AllyAvatar, type AllyShape } from "@/components/ally-avatar";
import { getAccentPalette } from "@/components/next-button";
import { ShinyText } from "@/components/text-animations/shiny-text";
import { captureWaitlistEvent } from "@/lib/analytics/waitlist";
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
const THINKING_HOLD_MS = 900;
const GREETING_CHAR_INTERVAL_MS = 18;
const COMPLETION_BUTTON_COLOR = "#fd304f";
const COMPLETION_CURSOR_EASE_MS = 1000;
const COMPLETION_CURSOR_MAX_SPEED_DEG_PER_SEC = 90;

type CompletionAllyConfig = {
  shape: AllyShape;
  color: string;
  positionClass: string;
  movement: {
    waypoints: ReadonlyArray<readonly [number, number]>;
    durationMs: number;
    phase: number;
    wiggle: number;
  };
};

const COMPLETION_ALLIES: CompletionAllyConfig[] = [
  {
    shape: "rocky",
    color: "#12c25b",
    positionClass: "waitlist-complete-ally-green",
    movement: {
      waypoints: [
        [0, 0],
        [22, -16],
        [34, 8],
        [12, 28],
        [-20, 18],
        [-12, -4],
      ],
      durationMs: 9800,
      phase: 0.04,
      wiggle: 4,
    },
  },
  {
    shape: "ghosty",
    color: "#fd304f",
    positionClass: "waitlist-complete-ally-red",
    movement: {
      waypoints: [
        [0, 0],
        [-24, -17],
        [-31, 7],
        [-8, 30],
        [25, 20],
        [17, -6],
      ],
      durationMs: 11200,
      phase: 0.28,
      wiggle: 4,
    },
  },
  {
    shape: "boxy",
    color: "#fbe65f",
    positionClass: "waitlist-complete-ally-yellow",
    movement: {
      waypoints: [
        [0, 0],
        [-19, -19],
        [10, -28],
        [29, -5],
        [8, 25],
        [-24, 16],
      ],
      durationMs: 10300,
      phase: 0.53,
      wiggle: 3.5,
    },
  },
  {
    shape: "rolly",
    color: "#3446e9",
    positionClass: "waitlist-complete-ally-blue",
    movement: {
      waypoints: [
        [0, 0],
        [24, -12],
        [30, 17],
        [2, 32],
        [-27, 14],
        [-19, -11],
      ],
      durationMs: 9000,
      phase: 0.71,
      wiggle: 4,
    },
  },
];

function getCompletionPathPoint(
  waypoints: ReadonlyArray<readonly [number, number]>,
  progress: number,
  wiggle: number,
) {
  const pointCount = waypoints.length;
  const scaledProgress = progress * pointCount;
  const segmentIndex = Math.floor(scaledProgress) % pointCount;
  const segmentProgress = scaledProgress - Math.floor(scaledProgress);
  const p0 = waypoints[(segmentIndex - 1 + pointCount) % pointCount];
  const p1 = waypoints[segmentIndex];
  const p2 = waypoints[(segmentIndex + 1) % pointCount];
  const p3 = waypoints[(segmentIndex + 2) % pointCount];
  const t2 = segmentProgress * segmentProgress;
  const t3 = t2 * segmentProgress;
  const x =
    0.5 *
    (2 * p1[0] +
      (-p0[0] + p2[0]) * segmentProgress +
      (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
      (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3);
  const y =
    0.5 *
    (2 * p1[1] +
      (-p0[1] + p2[1]) * segmentProgress +
      (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
      (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3);
  const segmentX = p2[0] - p1[0];
  const segmentY = p2[1] - p1[1];
  const segmentLength = Math.hypot(segmentX, segmentY) || 1;
  const wiggleEnvelope = Math.sin(segmentProgress * Math.PI);
  const wiggleOffset =
    Math.sin(segmentProgress * Math.PI * 2 + segmentIndex * 1.35) *
    wiggle *
    wiggleEnvelope;

  return {
    x: x - (segmentY / segmentLength) * wiggleOffset,
    y: y + (segmentX / segmentLength) * wiggleOffset,
  };
}

type PreviewPhase = "coming-alive" | "thinking" | "ready";

function MailboxIcon({ color }: { color: string }) {
  return (
    <svg
      aria-hidden="true"
      width="24"
      height="24"
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

function CompletionCursor({ fill }: { fill: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 28.0348 28.0348"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M25.8723 8.1633C28.7683 9.2356 28.7523 13.3397 25.8445 14.3857L17.6873 17.3219C17.5143 17.3847 17.3813 17.519 17.3221 17.6847L14.3844 25.8445C13.3383 28.7519 9.2337 28.7685 8.1614 25.8727L0.2632 4.6066C0.225 4.5034 0.1859 4.4006 0.1532 4.2955C-0.639 1.755 1.7753 -0.6558 4.3218 0.1625C4.4342 0.1986 4.5445 0.2414 4.6553 0.2824L25.8723 8.1633Z"
        fill={fill}
      />
    </svg>
  );
}

function CompletionLogo() {
  return (
    <div className="waitlist-complete-logo" aria-label="allies">
      <Image
        src="/allies-icon.svg"
        alt=""
        aria-hidden="true"
        width={25}
        height={24}
      />
      <span>allies</span>
    </div>
  );
}

function CompletionAlly({
  ally,
  prefersReducedMotion,
}: {
  ally: CompletionAllyConfig;
  prefersReducedMotion: boolean;
}) {
  const translateX = useMotionValue(0);
  const translateY = useMotionValue(0);
  const cursorRotation = useMotionValue(0);
  const previousDirection = useRef(0);
  const smoothedDirection = useRef(0);
  const previousFrameTime = useRef(0);

  useAnimationFrame((elapsed) => {
    if (prefersReducedMotion) return;

    const { movement } = ally;
    const progress =
      (elapsed / movement.durationMs + movement.phase) % 1;
    const previousProgress = (progress - 0.006 + 1) % 1;
    const nextProgress = (progress + 0.006) % 1;
    const point = getCompletionPathPoint(
      movement.waypoints,
      progress,
      movement.wiggle,
    );
    const previousPoint = getCompletionPathPoint(
      movement.waypoints,
      previousProgress,
      movement.wiggle,
    );
    const nextPoint = getCompletionPathPoint(
      movement.waypoints,
      nextProgress,
      movement.wiggle,
    );
    const dx = nextPoint.x - previousPoint.x;
    const dy = nextPoint.y - previousPoint.y;
    const rawDirection = (Math.atan2(dy, dx) * 180) / Math.PI;
    const directionDelta =
      ((rawDirection - previousDirection.current + 540) % 360) - 180;
    const direction = previousDirection.current + directionDelta;
    const frameDelta = previousFrameTime.current
      ? Math.min(64, Math.max(0, elapsed - previousFrameTime.current))
      : 16;
    if (!previousFrameTime.current) {
      smoothedDirection.current = direction;
    } else {
      const ease = 1 - Math.exp(-frameDelta / COMPLETION_CURSOR_EASE_MS);
      const easedDelta =
        (direction - smoothedDirection.current) * ease;
      const maximumStep =
        (COMPLETION_CURSOR_MAX_SPEED_DEG_PER_SEC * frameDelta) / 1000;
      smoothedDirection.current += Math.max(
        -maximumStep,
        Math.min(maximumStep, easedDelta),
      );
    }

    translateX.set(point.x);
    translateY.set(point.y);
    cursorRotation.set(smoothedDirection.current + 135);
    previousDirection.current = direction;
    previousFrameTime.current = elapsed;
  });

  return (
    <motion.div
      className={`waitlist-complete-ally ${ally.positionClass}`}
      aria-hidden="true"
      style={{ x: translateX, y: translateY }}
    >
      <div className="waitlist-complete-ally-face">
        <AllyAvatar
          shape={ally.shape}
          color={ally.color}
          size={36}
          motion={prefersReducedMotion ? "reduced" : "system"}
        />
      </div>
      <motion.div
        className="waitlist-complete-ally-cursor"
        style={{ rotate: cursorRotation }}
      >
        <CompletionCursor fill={ally.color} />
      </motion.div>
    </motion.div>
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

function WavyText({ text }: { text: string }) {
  return (
    <span className="onboarding-coming-alive-text" aria-label={text}>
      {Array.from(text).map((character, index) => (
        <span
          key={`${character}-${index}`}
          aria-hidden="true"
          style={
            {
              "--wave-delay": `${index * 70}ms`,
            } as CSSProperties
          }
        >
          {character === " " ? "\u00a0" : character}
        </span>
      ))}
    </span>
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
  const [thinkingStartedAt, setThinkingStartedAt] = useState<number | null>(null);
  const [canRevealGreeting, setCanRevealGreeting] = useState(false);
  const [visibleGreeting, setVisibleGreeting] = useState({ source: "", text: "" });
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
    const timer = window.setTimeout(() => {
      setCanRevealGreeting(prefersReducedMotion);
      setThinkingStartedAt(window.performance.now());
      setPhase("thinking");
    }, delay);
    return () => window.clearTimeout(timer);
  }, [prefersReducedMotion]);

  useEffect(() => {
    if (phase !== "thinking") return;
    if (prefersReducedMotion || thinkingStartedAt === null) return;

    const remaining = Math.max(
      0,
      thinkingStartedAt + THINKING_HOLD_MS - window.performance.now(),
    );
    const timer = window.setTimeout(() => setCanRevealGreeting(true), remaining);
    return () => window.clearTimeout(timer);
  }, [phase, prefersReducedMotion, thinkingStartedAt]);

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
  const displayPhase =
    phase === "thinking" && canRevealGreeting && greetingIsCurrent ? "ready" : phase;
  const shouldShowGreeting = displayPhase === "ready" && greetingIsCurrent;
  const greetingText = snapshot?.greeting?.text ?? "";
  const renderedGreeting =
    visibleGreeting.source === greetingText ? visibleGreeting.text : "";
  const joinedEmail = snapshot?.join?.email ?? null;
  const palette = getAccentPalette(color);
  const { accent } = palette;

  useEffect(() => {
    if (!shouldShowGreeting || !greetingText) return;
    if (prefersReducedMotion) {
      const timer = window.setTimeout(
        () => setVisibleGreeting({ source: greetingText, text: greetingText }),
        0,
      );
      return () => window.clearTimeout(timer);
    }

    let characterIndex = 0;
    const timer = window.setInterval(() => {
      characterIndex = Math.min(characterIndex + 1, greetingText.length);
      setVisibleGreeting({
        source: greetingText,
        text: greetingText.slice(0, characterIndex),
      });
      if (characterIndex === greetingText.length) window.clearInterval(timer);
    }, GREETING_CHAR_INTERVAL_MS);

    return () => window.clearInterval(timer);
  }, [greetingText, prefersReducedMotion, shouldShowGreeting]);

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
            <WavyText text="Coming alive...." />
          </motion.div>
        </div>
      </Artboard>
    );
  }

  if (joinedEmail) {
    return (
      <Artboard>
        <motion.main
          data-testid="waitlist-complete"
          className="ph-no-capture onboarding-page waitlist-complete-page"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
        >
          <div className="waitlist-complete-content">
            <CompletionLogo />
            <div className="waitlist-complete-stage">
              <h1>See you soon</h1>
              {COMPLETION_ALLIES.map((ally) => (
                <CompletionAlly
                  key={ally.shape}
                  ally={ally}
                  prefersReducedMotion={prefersReducedMotion}
                />
              ))}
            </div>
            <a
              className="waitlist-complete-follow"
              href="https://x.com/allies_ai"
              target="_blank"
              rel="noreferrer"
              onClick={() =>
                captureWaitlistEvent("waitlist_follow_clicked", {
                  source: "completion",
                })
              }
              style={{ backgroundColor: COMPLETION_BUTTON_COLOR }}
            >
              <span>Follow us on</span>
              <Image src="/ally/icons/x-social.svg" alt="X" width={13} height={13} />
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
        className="ph-no-capture onboarding-page onboarding-overlay-host"
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
                {renderedGreeting}
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
              className="waitlist-save-modal-overlay"
            >
              <motion.div
                initial={{ y: 36, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                exit={{ y: 24, opacity: 0 }}
                transition={{ type: "spring", stiffness: 260, damping: 26 }}
                className="waitlist-save-modal-card"
              >
                <div className="waitlist-save-modal-top-row">
                  <div
                    aria-hidden="true"
                    className="waitlist-save-modal-mailbox"
                    style={{ background: `${accent}40` }}
                  >
                    <MailboxIcon color={accent} />
                  </div>
                  <button
                    type="button"
                    aria-label="Close save Ally dialog"
                    onClick={() => setShowSaveModal(false)}
                    className="waitlist-save-modal-close"
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
                  className="waitlist-save-modal-form"
                >
                  <h2 className="waitlist-save-modal-title">
                    Save
                    <br />
                    your ally
                  </h2>
                  <p className="waitlist-save-modal-description">
                    allies isn&apos;t live yet. Enter your email to save the ally you&apos;ve shaped and its first message.
                  </p>
                  <input
                    data-testid="waitlist-email"
                    aria-label="Email address"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="Email address"
                    className="waitlist-save-modal-email"
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
                    className="waitlist-save-modal-submit"
                    style={{
                      background: email.trim() && consentVersion ? accent : "#d9d9d9",
                      cursor: email.trim() && consentVersion ? "pointer" : "default",
                    }}
                  >
                    {pendingAction === "join" ? "Saving…" : "Submit"}
                  </button>
                  <p className="waitlist-save-modal-consent">
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
