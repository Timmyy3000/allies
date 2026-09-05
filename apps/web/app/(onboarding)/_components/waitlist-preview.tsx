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
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import { useRouter } from "next/navigation";

import { Artboard } from "@/components/artboard";
import { AllyAvatar, type AllyShape } from "@/components/ally-avatar";
import { getAccentPalette } from "@/components/next-button";
import { ShinyText } from "@/components/text-animations/shiny-text";
import { captureWaitlistEvent } from "@/lib/analytics/waitlist";
import {
  OnboardingAuthResumeContext,
  clearOnboardingResume,
  writeOnboardingResume,
} from "../_store/onboarding-resume";
import { useOnboardingStore } from "../_store/onboarding-store";
import { WaitlistMappingError } from "../../../lib/waitlist/catalog";
import {
  serializeOnboardingConfiguration,
  useAllyPreviewFlow,
  waitlistGreetingFingerprint,
} from "../../../lib/waitlist/flow";
import { AllowNotifications } from "./allow-notifications";
import { AuthOverlay } from "./auth-overlay";
import { AuthWelcome } from "./auth-welcome";
import {
  ONBOARDING_ALLY_LAYOUT_ID,
  PersistentAllyAvatar,
} from "./persistent-ally";

const AUTH_WELCOME_HOLD_MS = 3_000;
type AuthGate = "closed" | "overlay" | "welcome" | "notifications" | "done";

function localPreviewGreeting(allyName: string) {
  const who = allyName.trim() || "your ally";
  return [
    `Welcome! I am ${who}, and I am thrilled to help you make your day easier, more productive, and fun. Think of me as your always-available partner for brainstorming, writing, learning, and organising.`,
    "No task is too big or too small, and I am constantly learning new ways to assist you better. Let us collaborate and build something great together.",
  ].join("\n\n");
}

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

async function requestBrowserNotifications() {
  if (typeof Notification === "undefined" || Notification.permission !== "default") {
    return;
  }
  try {
    await Notification.requestPermission();
  } catch {
    return;
  }
}

export function WaitlistPreviewScreen() {
  const name = useOnboardingStore((state) => state.name);
  const shape = useOnboardingStore((state) => state.shape);
  const color = useOnboardingStore((state) => state.color);
  const job = useOnboardingStore((state) => state.job);
  const personalities = useOnboardingStore((state) => state.personalities);
  const personalityNote = useOnboardingStore((state) => state.personalityNote);
  const personalityRaw = useOnboardingStore((state) => state.personalityRaw);
  const router = useRouter();
  const resumeAfterGoogle = useContext(OnboardingAuthResumeContext);
  const [phase, setPhase] = useState<PreviewPhase>(resumeAfterGoogle ? "ready" : "coming-alive");
  const [thinkingStartedAt, setThinkingStartedAt] = useState<number | null>(null);
  const [canRevealGreeting, setCanRevealGreeting] = useState(false);
  const [visibleGreeting, setVisibleGreeting] = useState({ source: "", text: "" });
  const [replyDraft, setReplyDraft] = useState<string | null>(null);
  const [authGate, setAuthGate] = useState<AuthGate>(resumeAfterGoogle ? "welcome" : "closed");
  const prefersReducedMotion = useReducedMotion() ?? false;

  if (resumeAfterGoogle && (phase !== "ready" || authGate !== "welcome")) {
    setPhase("ready");
    setAuthGate("welcome");
  }
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
    retry,
    completionMode,
  } = useAllyPreviewFlow();

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
    phase === "thinking" && canRevealGreeting ? "ready" : phase;
  const cloudGreeting = greetingIsCurrent ? snapshot?.greeting?.text ?? "" : "";
  const greetingText =
    cloudGreeting ||
    (displayPhase === "ready" ? localPreviewGreeting(name) : "");
  const shouldShowGreeting = displayPhase === "ready" && Boolean(greetingText);
  const renderedGreeting =
    visibleGreeting.source === greetingText ? visibleGreeting.text : "";
  const joinedEmail = completionMode === "waitlist" ? snapshot?.join?.email ?? null : null;
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

  useEffect(() => {
    if (authGate !== "welcome") return;
    const hold = prefersReducedMotion ? 0 : AUTH_WELCOME_HOLD_MS;
    const timer = window.setTimeout(() => setAuthGate("notifications"), hold);
    return () => window.clearTimeout(timer);
  }, [authGate, prefersReducedMotion]);

  const openAuthGate = () => {
    if (
      completionMode === "authenticated" ||
      phase === "coming-alive" ||
      authGate === "welcome" ||
      authGate === "notifications" ||
      authGate === "done"
    ) {
      return;
    }
    setAuthGate("overlay");
  };

  const persistOnboardingResume = () => {
    writeOnboardingResume({
      name,
      shape,
      color,
      job,
      personalities,
      personalityNote,
      personalityRaw,
    });
  };

  const goToHome = () => {
    clearOnboardingResume();
    router.replace("/home");
  };

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

  if (authGate === "welcome") {
    return <AuthWelcome name={name} shape={shape} color={accent} />;
  }

  if (authGate === "notifications") {
    return (
      <AllowNotifications
        shape={shape}
        color={accent}
        onLater={goToHome}
        onAllow={async () => {
          await requestBrowserNotifications();
          goToHome();
        }}
      />
    );
  }

  if (joinedEmail || authGate === "done") {
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
              if (completionMode === "authenticated") {
                if (!isBusy && replyText.trim() && greetingIsCurrent && cloudGreeting) {
                  void recordReply(replyText.trim()).catch(() => undefined);
                }
              } else {
                openAuthGate();
              }
            }}
          >
          <input
            aria-label="Reply to your Ally"
            data-testid="waitlist-reply"
            value={replyText}
            onFocus={openAuthGate}
            onChange={(event) => {
              setReplyDraft(event.target.value);
              openAuthGate();
            }}
            placeholder={`Reply ${name || "your Ally"}`}
            maxLength={4000}
            className="waitlist-preview-composer-input"
          />
          <button
            type="submit"
            aria-label="Send reply"
            disabled={completionMode === "authenticated" && (isBusy || !replyText.trim() || !greetingIsCurrent || !cloudGreeting)}
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
          {authGate === "overlay" ? (
            <AuthOverlay
              shape={shape}
              color={accent}
              onClose={() => setAuthGate("closed")}
              onPrepareGoogleSignIn={persistOnboardingResume}
              onSignUp={(provider) => {
                if (provider === "chatgpt") setAuthGate("welcome");
              }}
            />
          ) : null}
        </AnimatePresence>
      </div>
    </Artboard>
  );
}
