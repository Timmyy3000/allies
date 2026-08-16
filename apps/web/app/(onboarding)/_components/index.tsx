"use client";

import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import Image from "next/image";
import Link from "next/link";
import { AllyAvatar } from "@/components/ally-avatar";
import {
  AnimatedCopy,
  type AllyAnimationState,
  type AllyKind,
  type CopyParagraph,
  type StoryActorBounds,
  type StoryBeat,
} from "./animated-copy";
import OnboardingFlow from "./make-ally";
import OnboardingDrawer from "./onboarding-drawer";
import { useOnboardingStore } from "../_store/onboarding-store";

const DESKTOP_ART_W = 1512;
const DESKTOP_ART_H = 982;
const MOBILE_ART_W = 375;
const MOBILE_ART_H = 812;
const BRAND_ORANGE = "#FF5800";

const DESKTOP_ACTOR_BOUNDS: StoryActorBounds = {
  width: DESKTOP_ART_W,
  height: DESKTOP_ART_H,
  offsetLeft: 387,
  offsetTop: 208,
};

const MOBILE_ACTOR_BOUNDS: StoryActorBounds = {
  width: MOBILE_ART_W,
  height: MOBILE_ART_H,
  offsetLeft: 20,
  offsetTop: 128,
};

const DESKTOP_ROAM_OFFSETS = {
  red: { left: 44, top: 24 },
  blue: { left: -40, top: 32 },
  yellow: { left: -34, top: -26 },
  green: { left: 38, top: -22 },
} satisfies Record<AllyKind, { left: number; top: number }>;

const MOBILE_ROAM_OFFSETS = {
  red: { left: 32, top: 20 },
  blue: { left: -28, top: 26 },
  yellow: { left: -25, top: -21 },
  green: { left: 30, top: -18 },
} satisfies Record<AllyKind, { left: number; top: number }>;

const IconSizeContext = createContext(24);

function useArtboardScale(artW: number, maxScale = Number.POSITIVE_INFINITY) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const update = () => {
      setScale(Math.min(host.clientWidth / artW, maxScale));
    };

    update();
    const observer = new ResizeObserver(update);
    observer.observe(host);
    return () => observer.disconnect();
  }, [artW, maxScale]);

  return { hostRef, scale };
}

export default function Onboarding({
  waitlistEnabled = false,
  ctaHref,
  presentation = "route",
}: {
  waitlistEnabled?: boolean;
  ctaHref?: string;
  presentation?: "route" | "drawer";
}) {
  const step = useOnboardingStore((state) => state.step);
  const goTo = useOnboardingStore((state) => state.goTo);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isDrawerPresentation = presentation === "drawer";

  const openDrawer = useCallback(() => {
    setDrawerOpen(true);
    goTo("name");
  }, [goTo]);

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
  }, []);

  const resetAfterDrawerClose = useCallback(() => {
    setDrawerOpen(false);
    goTo("welcome");
  }, [goTo]);

  if (step !== "welcome" && !isDrawerPresentation) {
    return <OnboardingStepFlow />;
  }

  return (
    <>
      <div className="hidden min-[1024px]:block">
        <DesktopOnboarding
          waitlistEnabled={waitlistEnabled}
          ctaHref={ctaHref}
          onOpenOnboarding={isDrawerPresentation ? openDrawer : undefined}
        />
      </div>
      <div className="min-[1024px]:hidden">
        <MobileOnboarding
          waitlistEnabled={waitlistEnabled}
          ctaHref={ctaHref}
          onOpenOnboarding={isDrawerPresentation ? openDrawer : undefined}
        />
      </div>
      {isDrawerPresentation ? (
        <OnboardingDrawer
          open={drawerOpen && step !== "welcome"}
          onClose={closeDrawer}
          onClosed={resetAfterDrawerClose}
        >
          <OnboardingStepFlow />
        </OnboardingDrawer>
      ) : null}
    </>
  );
}

function OnboardingStepFlow() {
  const step = useOnboardingStore((state) => state.step);

  return (
    <LayoutGroup id="onboarding-flow">
      <div
        className="onboarding-step"
        style={{
          minHeight: "var(--onboarding-artboard-min-height, 100dvh)",
          width: "100%",
          overflow: "hidden",
          position: "relative",
        }}
      >
        <AnimatePresence initial={false} mode="sync">
          <motion.div
            key={step}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
            style={{
              position: "absolute",
              inset: 0,
              overflow: "hidden",
            }}
          >
            <OnboardingFlow />
          </motion.div>
        </AnimatePresence>
      </div>
    </LayoutGroup>
  );
}

function FollowAlly({
  ally,
  state,
  hideCursor = false,
}: {
  ally: AllyKind;
  state: AllyAnimationState;
  hideCursor?: boolean;
}) {
  return (
    <div
      style={{
        pointerEvents: "none",
        zIndex: 2,
        width: 60,
        height: 58,
        transform: "scale(0.64)",
        transformOrigin: "0 0",
      }}
    >
      {ally === "red" ? (
        <RedAlly left={0} top={0} state={state} showCursor={!hideCursor} />
      ) : null}
      {ally === "blue" ? (
        <BlueAlly
          left={0}
          top={0}
          width={60}
          faceLeft={23}
          state={state}
          showCursor={!hideCursor}
        />
      ) : null}
      {ally === "yellow" ? (
        <YellowAlly
          left={0}
          top={0}
          width={64}
          faceLeft={26}
          state={state}
          showCursor={!hideCursor}
        />
      ) : null}
      {ally === "green" ? (
        <GreenAlly left={0} top={0} state={state} showCursor={!hideCursor} />
      ) : null}
    </div>
  );
}

function DesktopOnboarding({
  waitlistEnabled,
  ctaHref,
  onOpenOnboarding,
}: {
  waitlistEnabled: boolean;
  ctaHref?: string;
  onOpenOnboarding?: () => void;
}) {
  const { hostRef, scale } = useArtboardScale(DESKTOP_ART_W, 1);
  const isNativeWidth = scale === 1;
  const [storyDone, setStoryDone] = useState(false);

  return (
    <div
      ref={hostRef}
      className="relative min-h-[100dvh] w-full overflow-hidden bg-[#fff]"
    >
      <div style={{ height: DESKTOP_ART_H * scale, width: "100%" }} aria-hidden />
      <div
        className="absolute top-0 origin-top-left"
        style={{
          width: DESKTOP_ART_W,
          height: DESKTOP_ART_H,
          left: isNativeWidth ? "50%" : 0,
          marginLeft: isNativeWidth ? -DESKTOP_ART_W / 2 : 0,
          transform: `scale(${scale})`,
          borderRadius: "10px 10px 0px 0px",
          backgroundColor: "#fff",
          overflow: "hidden",
        }}
      >
        <div
          className="text onboarding-story--desktop"
          style={{
            textAlign: "left",
            lineHeight: "49px",
            fontSize: 24,
            fontWeight: 600,
            fontStretch: "100%",
            letterSpacing: -0.5,
            color: "#121212",
            left: 387,
            top: 208,
            width: 739,
            position: "absolute",
            overflow: "visible",
            whiteSpace: "nowrap",
          }}
        >
          <AnimatedCopy
            paragraphs={DESKTOP_PARAGRAPHS}
            paragraphGap={0}
            beats={STORY_BEATS}
            initialParagraphs={[0]}
            actorBounds={DESKTOP_ACTOR_BOUNDS}
            artboardScale={scale}
            roamOffsets={DESKTOP_ROAM_OFFSETS}
            onComplete={setStoryDone}
            renderActor={(ally, state, options) => (
              <FollowAlly
                ally={ally}
                state={state}
                hideCursor={options?.hideCursor}
              />
            )}
          />
          {storyDone ? (
            <MeetAllyButton
              enabled={waitlistEnabled}
              href={ctaHref}
              onOpen={onOpenOnboarding}
              fontSize={18}
              marginTop={36}
            />
          ) : null}
        </div>
        <FollowUs />
        <LogoMark />
      </div>
    </div>
  );
}

function MobileOnboarding({
  waitlistEnabled,
  ctaHref,
  onOpenOnboarding,
}: {
  waitlistEnabled: boolean;
  ctaHref?: string;
  onOpenOnboarding?: () => void;
}) {
  const { hostRef, scale } = useArtboardScale(MOBILE_ART_W);
  const [storyDone, setStoryDone] = useState(false);

  return (
    <IconSizeContext.Provider value={16}>
      <div
        ref={hostRef}
        className="relative min-h-[100dvh] w-full overflow-hidden bg-[#fff]"
      >
        <div
          style={{ height: MOBILE_ART_H * scale, width: "100%" }}
          aria-hidden
        />
        <div
          className="absolute left-0 top-0 origin-top-left"
          style={{
            width: MOBILE_ART_W,
            height: MOBILE_ART_H,
            transform: `scale(${scale})`,
            backgroundColor: "#fff",
            overflow: "hidden",
          }}
        >
          {/* device chrome stripped — status bar + home indicator */}
          <div
            className="text"
            style={{
              left: 20,
              top: 128,
              width: 335,
              position: "absolute",
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-start",
              textAlign: "left",
              lineHeight: "22px",
              fontSize: 16,
              fontWeight: 600,
              fontStretch: "100%",
              letterSpacing: -0.47,
              color: "#121212",
            }}
          >
            <AnimatedCopy
              paragraphs={MOBILE_PARAGRAPHS}
              paragraphGap={22}
              beats={STORY_BEATS}
              initialParagraphs={[0]}
              actorBounds={MOBILE_ACTOR_BOUNDS}
              artboardScale={scale}
              roamOffsets={MOBILE_ROAM_OFFSETS}
              onComplete={setStoryDone}
              renderActor={(ally, state, options) => (
                <FollowAlly
                  ally={ally}
                  state={state}
                  hideCursor={options?.hideCursor}
                />
              )}
            />
            {storyDone ? (
              <MeetAllyButton
                enabled={waitlistEnabled}
                href={ctaHref}
                onOpen={onOpenOnboarding}
                fontSize={16}
                marginTop={36}
              />
            ) : null}
          </div>
          <FollowUs
            top={71}
            right={20.4}
            left="auto"
            columnGap={6}
            fontSize={16}
            letterSpacing={-0.7}
            iconWidth={14.7}
            iconHeight={15}
          />
          <LogoMark left={20} top={68} />
        </div>
      </div>
    </IconSizeContext.Provider>
  );
}

function MeetAllyButton({
  enabled = true,
  href,
  onOpen,
  top,
  right,
  fontSize,
  marginTop,
}: {
  enabled?: boolean;
  href?: string;
  onOpen?: () => void;
  top?: number;
  right?: number;
  fontSize: number;
  marginTop?: number;
}) {
  const startMakeAlly = useOnboardingStore((state) => state.goTo);
  const label = (
    <span
      className="text"
      style={{
        display: "inline",
        textAlign: "left",
        fontSize,
        fontWeight: 600,
        fontStretch: "100%",
        letterSpacing: -0.7,
        lineHeight: "100%",
        color: "#fff",
        width: "max-content",
        position: "relative",
        flexShrink: 0,
        whiteSpace: "nowrap",
        overflowWrap: "normal",
      }}
    >
      Meet your first ally
    </span>
  );
  const style = {
    borderRadius: 60,
    backgroundColor: "#FF5800",
    display: "flex",
    flexDirection: "row" as const,
    gap: 10,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    top,
    right,
    width: "max-content",
    position:
      top != null ? ("absolute" as const) : ("relative" as const),
    marginTop,
    padding: 16,
    border: "none",
    cursor: "pointer",
    textDecoration: "none",
  };

  if (href && enabled && !onOpen) {
    return (
      <Link href={href} data-testid="make-first-ally" style={style}>
        {label}
      </Link>
    );
  }

  return (
    <button
      type="button"
      data-testid="make-first-ally"
      aria-disabled={!enabled}
      disabled={!enabled}
      onClick={enabled ? onOpen ?? (() => startMakeAlly("name")) : undefined}
      style={style}
    >
      {label}
    </button>
  );
}

function IconWord({
  icon,
  word,
  color,
  iconAfter,
}: {
  icon: ReactNode;
  word: string;
  color?: string;
  iconAfter?: boolean;
}) {
  return (
    <span style={{ whiteSpace: "nowrap" }}>
      {!iconAfter && icon}
      <span style={color ? { color } : undefined}>{word}</span>
      {iconAfter && icon}
    </span>
  );
}

const RED = "#fd304f";
const BLUE = "#3446e9";
const YELLOW = "#E9B43A";
const GREEN = "#12c25b";

const ANIMATED_LINE_ICON_ASSETS = {
  cash: "/ally/icons/cash_anim.svg",
  lang: "/ally/icons/lang_anim.svg",
  lock: "/ally/icons/lock_anim.svg",
  shop: "/ally/icons/shop_anim.svg",
  watch: "/ally/icons/watch_anim.svg",
  work: "/ally/icons/work_anim.svg",
} as const;

type AnimatedLineIconName = keyof typeof ANIMATED_LINE_ICON_ASSETS;
type IconAccent = "pink" | "blue" | "yellow" | "green";

// The supplied animated SVGs carry their source palette in the paths. A
// filter keeps the animation intact while letting a story beat recolour the
// icon to the Ally that triggered it.
const ICON_ACCENT_FILTERS: Record<IconAccent, string> = {
  pink:
    "brightness(0) saturate(100%) invert(27%) sepia(96%) saturate(3528%) hue-rotate(334deg) brightness(102%) contrast(99%)",
  blue:
    "brightness(0) saturate(100%) invert(29%) sepia(77%) saturate(2753%) hue-rotate(218deg) brightness(91%) contrast(101%)",
  yellow:
    "brightness(0) saturate(100%) invert(71%) sepia(69%) saturate(561%) hue-rotate(359deg) brightness(97%) contrast(87%)",
  green:
    "brightness(0) saturate(100%) invert(57%) sepia(84%) saturate(702%) hue-rotate(101deg) brightness(93%) contrast(93%)",
};

const DESKTOP_PARAGRAPHS: CopyParagraph[] = [
  {
    ally: null,
    color: "#121212",
    parts: [{ type: "text", text: "We’re your allies" }],
  },
  {
    ally: "green",
    color: GREEN,
    parts: [
      {
        type: "text",
        text: "We’re personal helpers built around what matters to you.",
      },
    ],
  },
  {
    ally: "blue",
    color: BLUE,
    parts: [
      { type: "text", text: "Our job is to give you back " },
      {
        type: "icon",
        word: "time",
        color: BLUE,
        icon: <AnimatedLineIcon name="watch" accent="blue" />,
      },
      { type: "text", text: "." },
    ],
  },
  {
    ally: "red",
    color: RED,
    parts: [
      { type: "text", text: "We take responsibility for the " },
      {
        type: "icon",
        word: "work",
        color: RED,
        icon: <AnimatedLineIcon name="work" accent="pink" />,
      },
      { type: "text", text: " you want off your plate." },
    ],
  },
  {
    ally: "yellow",
    color: YELLOW,
    parts: [
      { type: "text", text: "We remember what matters and keep you in " },
      {
        type: "icon",
        word: "control",
        color: YELLOW,
        icon: <AnimatedLineIcon name="lock" accent="yellow" />,
        iconAfter: true,
      },
      { type: "text", text: "." },
    ],
  },
  {
    ally: "green",
    color: GREEN,
    parts: [
      { type: "text", text: "We can track your finances, spot " },
      {
        type: "icon",
        word: "overspending",
        color: GREEN,
        icon: <AnimatedLineIcon name="cash" accent="green" />,
      },
      { type: "text", text: ", and keep you updated." },
    ],
  },
  {
    ally: "blue",
    color: BLUE,
    parts: [
      { type: "text", text: "We can help you learn a " },
      {
        type: "icon",
        word: "language",
        color: BLUE,
        icon: <AnimatedLineIcon name="lang" accent="blue" />,
      },
      { type: "text", text: " before your next trip." },
    ],
  },
  {
    ally: "red",
    color: RED,
    parts: [
      { type: "text", text: "We can keep your solo " },
      {
        type: "icon",
        word: "business",
        color: RED,
        icon: <AnimatedLineIcon name="shop" accent="pink" />,
      },
      { type: "text", text: " organised and moving." },
    ],
  },
  {
    ally: "yellow",
    color: YELLOW,
    parts: [
      {
        type: "text",
        text: "And when a job needs more than one of us, we work ",
      },
      {
        type: "icon",
        word: "together",
        color: YELLOW,
        icon: <AvatarCluster />,
      },
      { type: "text", text: "." },
    ],
  },
];

const MOBILE_PARAGRAPHS: CopyParagraph[] = [
  {
    ally: null,
    color: "#121212",
    parts: [{ type: "text", text: "Hi, we’re your allies" }],
  },
  {
    ally: "green",
    color: GREEN,
    parts: [
      {
        type: "text",
        text: "We’re personal helpers built around what matters to you.",
      },
    ],
  },
  ...DESKTOP_PARAGRAPHS.slice(2),
];

// The opening line is already present. Each following sentence gets a click,
// and the visitors cycle green -> blue -> pink -> yellow.
const STORY_BEATS: StoryBeat[] = [
  { actor: "green", color: GREEN, paragraphs: [1] },
  { actor: "blue", color: BLUE, paragraphs: [2] },
  { actor: "red", color: RED, paragraphs: [3] },
  { actor: "yellow", color: YELLOW, paragraphs: [4] },
  { actor: "green", color: GREEN, paragraphs: [5] },
  { actor: "blue", color: BLUE, paragraphs: [6] },
  { actor: "red", color: RED, paragraphs: [7] },
  { actor: "yellow", color: YELLOW, paragraphs: [8] },
];

function useIconBox() {
  const size = useContext(IconSizeContext);
  const isMobile = size < 24;

  return {
    overflow: "hidden",
    width: size,
    height: size,
    position: "relative",
    display: "inline-block",
    verticalAlign: "0.08em",
    marginLeft: isMobile ? 3 : 4,
    marginRight: isMobile ? 2 : 3,
  } as const;
}

function AnimatedLineIcon({
  name,
  accent,
}: {
  name: AnimatedLineIconName;
  accent: IconAccent;
}) {
  const size = useContext(IconSizeContext);
  const isMobile = size < 24;
  const iconScale = 1.28;

  return (
    <img
      data-landing-icon={name}
      aria-hidden="true"
      src={ANIMATED_LINE_ICON_ASSETS[name]}
      style={{
        display: "inline-block",
        width: "auto",
        height: size,
        transform: `scale(${iconScale})`,
        transformOrigin: "center center",
        filter: name === "lock" ? "none" : ICON_ACCENT_FILTERS[accent],
        verticalAlign: "0.08em",
        marginLeft: isMobile ? 3 : 4,
        marginRight: isMobile ? 2 : 3,
      }}
      alt=""
      draggable={false}
    />
  );
}

function CursorMark({ fill }: { fill: string }) {
  return (
    <div
      className="ally-cursor"
      style={{
        overflow: "hidden",
        left: "12%",
        top: "12%",
        right: "10.1%",
        bottom: "10.1%",
        width: "77.9%",
        height: "77.9%",
        position: "absolute",
      }}
    >
      <svg
        width="28.0348114601603"
        height="28.03479203818092"
        viewBox="0 0 28.0348114601603 28.03479203818092"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        style={{
          left: 0,
          top: 0,
          right: 0,
          bottom: 0,
          width: "100%",
          height: "100%",
          position: "absolute",
        }}
      >
        <path
          d="M25.8723 8.1633C28.7683 9.2356 28.7523 13.3397 25.8445 14.3857L17.6873 17.3219C17.5143 17.3847 17.3813 17.5195 17.3221 17.6847L14.3844 25.8445C13.3383 28.7519 9.2337 28.7685 8.1614 25.8727L0.2632 4.6066C0.225 4.5034 0.1859 4.4006 0.1532 4.2955-0.639 1.755 1.7753-0.6558 4.3218 0.1625 4.4342 0.1986 4.5445 0.2414 4.6553 0.2824L25.8723 8.1633Z"
          transform=" translate(0 3.2018006024259194e-9)"
          style={{ fillRule: "nonzero", fill }}
        />
      </svg>
    </div>
  );
}

const BLUE_EYE_MASK =
  "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNCIgaGVpZ2h0PSI2LjI5MjgwMDQyNjQ4MzE1NCIgdmlld0JveD0iMCAwIDQgNi4yOTI4MDA0MjY0ODMxNTQiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiIHByZXNlcnZlQXNwZWN0UmF0aW89Im5vbmUiIHN0eWxlPSJsZWZ0OiAwcHg7dG9wOiAwcHg7cmlnaHQ6IDBweDtib3R0b206IDBweDt0cmFuc2Zvcm06IG1hdHJpeCgxLDAsMCwxLDAsMCk7dHJhbnNmb3JtLW9yaWdpbjogMCAwOyI+PGRlZnM+PGNsaXBQYXRoIGlkPSJkZWZfMCI+PHJlY3QgeD0iMCIgeT0iMCIgd2lkdGg9IjMuNjU4NDE1NTU1OTUzOTc5NSIgaGVpZ2h0PSI2LjI5MjgwMDQyNjQ4MzE1NCI+PC9yZWN0PjwvY2xpcFBhdGg+PC9kZWZzPjxnIGlkPSJtYXNrX3VuZGVmaW5lZCIgbWFza1VuaXRzPSJ1c2VyU3BhY2VPblVzZSIgeD0iMCIgeT0iMCIgd2lkdGg9IjMuNjU4NDE1NTU1OTUzOTc5NSIgaGVpZ2h0PSI2LjI5MjgwMDQyNjQ4MzE1NCIgc3R5bGU9Im1hc2stdHlwZTogbHVtaW5hbmNlOyI+PGcgc3R5bGU9ImNsaXAtcGF0aDogdXJsKCNkZWZfMCk7Ij48cGF0aCBkPSJNMS44MzI5IDBDMi44MzggMCAzLjY1ODQgMS40MDQgMy42NTg0IDMuMTQ2NCAzLjY1ODQgNC44ODg4IDIuODM4IDYuMjkyOCAxLjgzMjkgNi4yOTI4IDAuODIwNCA2LjI5MjggMCA0Ljg4ODggMCAzLjE0NjQgMCAxLjQwNCAwLjgyMDQgMCAxLjgzMjkgMFoiIHN0eWxlPSJmaWxsLXJ1bGU6IG5vbnplcm87ZmlsbDogIzAwMDsiIC8+PC9nPjwvZz48L3N2Zz4=";

function BlueAlly({
  left = 109,
  top = 475,
  width = 60,
  faceLeft = 0,
  state = "idle",
  showCursor = true,
}: {
  left?: number | string;
  top?: number;
  width?: number;
  faceLeft?: number;
  state?: AllyAnimationState;
  showCursor?: boolean;
}) {
  return (
    <div
      style={{
        overflow: "hidden",
        left,
        top,
        width,
        height: 60,
        position: "absolute",
      }}
    >
      <div
        className="ally-face"
        style={{
          left: faceLeft,
          top: 24,
          width: 36,
          height: 36,
          position: "absolute",
        }}
      >
        <AllyAvatar shape="rolly" state={state} color="#3446e9" size={36} />
      </div>
      <div
        className="ally-face"
        style={{
          display: "none",
          borderRadius: 100,
          backgroundColor: "#3446e9",
          overflow: "hidden",
          left: faceLeft,
          top: 24,
          width: 36,
          height: 36,
          position: "absolute",
        }}
      >
        <div
          style={{
            overflow: "hidden",
            left: "calc(-12px + 50%)",
            top: "calc(-12px + 50%)",
            width: 24.6,
            height: 24,
            position: "absolute",
          }}
        >
          <svg
            width="26.406714916229244"
            height="25.771497249603275"
            viewBox="0 0 26.406714916229244 25.771497249603275"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            preserveAspectRatio="none"
            style={{
              left: "calc(-13.3px + 50%)",
              top: "calc(-13px + 50%)",
              width: 26.4,
              height: 25.8,
              position: "absolute",
            }}
          >
            <path
              d="M12.3067 0C19.1038 0 24.6135 5.3674 24.6135 11.9891 24.6135 18.6108 19.1038 23.9782 12.3067 23.9782 5.5096 23.9782 0 18.6108 0 11.9891 0 5.3674 5.5096 0 12.3067 0Z"
              transform=" translate(0.9619579329063142 0.9636885113844187)"
              style={{ fillRule: "nonzero", fill: "#fff" }}
            />
            <path
              d="M12.3067 0C19.1038 0 24.6135 5.3674 24.6135 11.9891 24.6135 18.6108 19.1038 23.9782 12.3067 23.9782 5.5096 23.9782 0 18.6108 0 11.9891 0 5.3674 5.5096 0 12.3067 0Z"
              transform=" translate(0.9619579329063142 0.9636885113844187)"
              style={{ stroke: "#000", strokeWidth: 1.7932639122009277 }}
            />
          </svg>
          <div
            className="ally-eyes"
            style={{
              overflow: "hidden",
              left: 9.5,
              top: 5.7,
              width: 11.1,
              height: 6.3,
              position: "absolute",
            }}
          >
            <div
              style={{
                overflow: "hidden",
                left: 0,
                top: 0,
                width: 3.7,
                height: 6.3,
                position: "absolute",
              }}
            >
              <svg
                width="3.65841555595398"
                height="6.300000190734863"
                viewBox="0 0 3.65841555595398 6.300000190734863"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                preserveAspectRatio="none"
                style={{
                  left: "0.1%",
                  top: 0,
                  right: 0,
                  bottom: 0,
                  width: "99.9%",
                  height: "100%",
                  position: "absolute",
                }}
              >
                <path
                  d="M1.8292 0C2.8395 0 3.6584 1.4105 3.6584 3.15 3.6584 4.8895 2.8395 6.3 1.8292 6.3 0.8189 6.3 0 4.8895 0 3.15 0 1.4105 0.8189 0 1.8292 0Z"
                  style={{ fillRule: "nonzero", fill: "#000" }}
                />
              </svg>
              <div
                style={{
                  overflow: "hidden",
                  left: 0,
                  top: "0.1%",
                  right: 0,
                  bottom: "0.1%",
                  width: "99.9%",
                  height: "99.9%",
                  position: "absolute",
                }}
              >
                <div
                  style={{
                    overflow: "hidden",
                    left: "-23.7%",
                    top: "29.1%",
                    right: "53%",
                    bottom: "28.5%",
                    width: "70.7%",
                    height: "42.3%",
                    position: "absolute",
                    maskImage: `url("${BLUE_EYE_MASK}")`,
                    WebkitMaskImage: `url("${BLUE_EYE_MASK}")`,
                    maskRepeat: "no-repeat",
                    WebkitMaskRepeat: "no-repeat",
                    maskType: "luminance",
                    maskPosition: "0.9px -1.8px",
                    WebkitMaskPosition: "0.9px -1.8px",
                  }}
                >
                  <svg
                    width="2.6645238399505615"
                    height="2.5867583751678467"
                    viewBox="0 0 2.6645238399505615 2.5867583751678467"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                    preserveAspectRatio="none"
                    style={{
                      transformOrigin: "0 0",
                      transform: "rotate(90deg)",
                      left: "100%",
                      top: 0,
                      right: "-103%",
                      bottom: "2.9%",
                      width: "103%",
                      height: "97.1%",
                      position: "absolute",
                    }}
                  >
                    <path
                      d="M1.3323 0L2.6645 2.5868H0L1.3323 0Z"
                      style={{ fillRule: "nonzero", fill: "#fff" }}
                    />
                  </svg>
                </div>
              </div>
            </div>
            <div
              style={{
                overflow: "hidden",
                left: 7.4,
                top: 0,
                width: 3.7,
                height: 6.3,
                position: "absolute",
              }}
            >
              <svg
                width="3.65841555595398"
                height="6.300000190734863"
                viewBox="0 0 3.65841555595398 6.300000190734863"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                preserveAspectRatio="none"
                style={{
                  left: 0,
                  top: 0,
                  right: 0,
                  bottom: 0,
                  width: "99.9%",
                  height: "100%",
                  position: "absolute",
                }}
              >
                <path
                  d="M1.8292 0C2.8395 0 3.6584 1.4105 3.6584 3.15 3.6584 4.8895 2.8395 6.3 1.8292 6.3 0.8189 6.3 0 4.8895 0 3.15 0 1.4105 0.8189 0 1.8292 0Z"
                  style={{ fillRule: "nonzero", fill: "#000" }}
                />
              </svg>
              <div
                style={{
                  overflow: "hidden",
                  left: 0,
                  top: "0.1%",
                  right: "0.1%",
                  bottom: "0.1%",
                  width: "99.9%",
                  height: "99.9%",
                  position: "absolute",
                }}
              >
                <div
                  style={{
                    overflow: "hidden",
                    left: "-23.7%",
                    top: "29.1%",
                    right: "53%",
                    bottom: "28.5%",
                    width: "70.7%",
                    height: "42.3%",
                    position: "absolute",
                    maskImage: `url("${BLUE_EYE_MASK}")`,
                    WebkitMaskImage: `url("${BLUE_EYE_MASK}")`,
                    maskRepeat: "no-repeat",
                    WebkitMaskRepeat: "no-repeat",
                    maskType: "luminance",
                    maskPosition: "0.9px -1.8px",
                    WebkitMaskPosition: "0.9px -1.8px",
                  }}
                >
                  <svg
                    width="2.6645238399505615"
                    height="2.5867583751678467"
                    viewBox="0 0 2.6645238399505615 2.5867583751678467"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                    preserveAspectRatio="none"
                    style={{
                      transformOrigin: "0 0",
                      transform: "rotate(90deg)",
                      left: "100%",
                      top: 0,
                      right: "-103%",
                      bottom: "2.9%",
                      width: "103%",
                      height: "97.1%",
                      position: "absolute",
                    }}
                  >
                    <path
                      d="M1.3323 0L2.6645 2.5868H0L1.3323 0Z"
                      style={{ fillRule: "nonzero", fill: "#fff" }}
                    />
                  </svg>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      {showCursor ? (
        <div
          style={{
            overflow: "hidden",
            left: 0,
            top: 0,
            width: 36,
            height: 36,
            position: "absolute",
          }}
        >
          <CursorMark fill="#3446e9" />
        </div>
      ) : null}
    </div>
  );
}

function TimeIcon() {
  const clipId = useId();
  const box = useIconBox();

  return (
    <div style={box}>
      <svg
        width="14.666666984558105"
        height="21.33333396911621"
        viewBox="0 0 14.666666984558105 21.33333396911621"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        style={{
          left: "19.4%",
          top: "5.6%",
          right: "19.4%",
          bottom: "5.6%",
          width: "61.1%",
          height: "88.9%",
          position: "absolute",
        }}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x="0" y="0" width="14.666666984558105" height="21.33333396911621" />
          </clipPath>
        </defs>
        <g style={{ clipPath: `url(#${clipId})` }}>
          <path
            d="M0.0002 7.6667C0.0002 5.641 1.6412 4 3.6668 4H11.0002C13.0258 4 14.6668 5.641 14.6668 7.6667V13.6667C14.6668 15.6923 13.0258 17.3333 11.0002 17.3333H3.6668C1.6412 17.3333 0.0002 15.6923 0.0002 13.6667V7.6667Z"
            style={{ fillRule: "evenodd", fill: "rgba(27,98,242,0.4)" }}
          />
          <path
            d="M7.3335 7C7.8858 7 8.3335 7.4477 8.3335 8V10.1124L10.5302 11.4853C10.9986 11.778 11.1408 12.3949 10.8482 12.8633 10.5555 13.3317 9.9386 13.474 9.4702 13.1813L6.8035 11.5147C6.5111 11.3319 6.3335 11.0114 6.3335 10.6667V8C6.3335 7.4477 6.7812 7 7.3335 7Z"
            style={{ fillRule: "evenodd", fill: "#1b62f2" }}
          />
          <path
            d="M5.463 0C4.3236 0 3.349 0.8252 3.1619 1.9501L2.8029 4.1023C3.08 4.0354 3.3693 4 3.667 4H11.0003C11.2979 4 11.5873 4.0354 11.8643 4.1023L11.5054 1.9501C11.3182 0.8235 10.3446 0 9.2043 0H5.463Z"
            style={{ fillRule: "nonzero", fill: "#1b62f2" }}
          />
          <path
            d="M2.8029 17.2311L3.1619 19.3832C3.349 20.5081 4.3236 21.3333 5.463 21.3333H9.2043C10.3446 21.3333 11.3183 20.5087 11.5055 19.3821L11.8643 17.2311C11.5873 17.2979 11.2979 17.3333 11.0003 17.3333H3.667C3.3693 17.3333 3.08 17.2979 2.8029 17.2311Z"
            style={{ fillRule: "nonzero", fill: "#1b62f2" }}
          />
        </g>
      </svg>
    </div>
  );
}

function AvatarCluster() {
  const size = useContext(IconSizeContext);
  const isMobile = size < 24;

  return (
    <span
      data-together-icon
      aria-hidden="true"
      style={{
        display: "inline-block",
        height: size,
        width: size * 2.5,
        aspectRatio: "auto",
        verticalAlign: "0.08em",
        marginLeft: isMobile ? 14 : 16,
        marginRight: isMobile ? 8 : 0,
        visibility: "hidden",
      }}
    />
  );
}

function FinanceIcon() {
  const clipId = useId();
  const box = useIconBox();

  return (
    <div style={box}>
      <svg
        width="18.12533187866211"
        height="20.33333396911621"
        viewBox="0 0 18.12533187866211 20.33333396911621"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        style={{
          left: "12.2%",
          top: "8.3%",
          right: "12.2%",
          bottom: "6.9%",
          width: "75.5%",
          height: "84.7%",
          position: "absolute",
        }}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x="0" y="0" width="18.12533187866211" height="20.33333396911621" />
          </clipPath>
        </defs>
        <g style={{ clipPath: `url(#${clipId})` }}>
          <path
            d="M9.0625 0C9.6148 0 10.0625 0.4477 10.0625 1H8.0625C8.0625 0.4477 8.5102 0 9.0625 0Z"
            style={{ fillRule: "nonzero", fill: "#ff2d55" }}
          />
          <path
            d="M14.0625 5.6667C14.6148 5.6667 15.0625 6.1144 15.0625 6.6667 15.0625 9.9803 12.3761 12.6667 9.0625 12.6667 5.7489 12.6667 3.0625 9.9803 3.0625 6.6667 3.0625 6.1144 3.5102 5.6667 4.0625 5.6667H14.0625Z"
            style={{ fillRule: "nonzero", fill: "rgba(255,45,85,0.4)" }}
          />
          <path
            d="M9.0627 14C5.3465 14 2.0744 15.9028 0.1665 18.7808-0.037 19.0877-0.0553 19.4819 0.1189 19.8064 0.2932 20.1308 0.6317 20.3333 1 20.3333H17.1253C17.4936 20.3333 17.8321 20.1309 18.0064 19.8064 18.1805 19.482 18.1624 19.088 17.9589 18.7809 16.0509 15.9012 12.7787 14 9.0627 14Z"
            style={{ fillRule: "nonzero", fill: "rgba(255,45,85,0.4)" }}
          />
          <path
            d="M9.0626 0.6667C6.207 0.6667 3.818 2.6606 3.2112 5.3333H2.3958C1.8436 5.3333 1.3958 5.7811 1.3958 6.3333 1.3958 6.8856 1.8436 7.3333 2.3958 7.3333H15.7292C16.2814 7.3333 16.7292 6.8856 16.7292 6.3333 16.7292 5.7811 16.2814 5.3333 15.7292 5.3333H14.914C14.3072 2.6606 11.9181 0.6667 9.0626 0.6667ZM9.0626 2.6667C9.4078 2.6667 9.7429 2.7104 10.0625 2.7927V3.3333C10.0625 3.8856 9.6148 4.3333 9.0625 4.3333 8.5102 4.3333 8.0625 3.8856 8.0625 3.3333V2.7927C8.3822 2.7104 8.7173 2.6667 9.0626 2.6667Z"
            style={{ fillRule: "evenodd", fill: "#ff2d55" }}
          />
        </g>
      </svg>
    </div>
  );
}

function LanguageIcon() {
  const clipId = useId();
  const box = useIconBox();

  return (
    <div style={box}>
      <svg
        width="19.333660125732422"
        height="21.333324432373047"
        viewBox="0 0 19.333660125732422 21.333324432373047"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        style={{
          left: "2.8%",
          top: "5.6%",
          right: "16.7%",
          bottom: "5.6%",
          width: "80.6%",
          height: "88.9%",
          position: "absolute",
        }}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x="0" y="0" width="19.333660125732422" height="21.333324432373047" />
          </clipPath>
        </defs>
        <g style={{ clipPath: `url(#${clipId})` }}>
          <path
            d="M4.6668 14C4.6668 9.9498 7.9506 6.6667 12.0002 6.6667 16.0498 6.6667 19.3335 9.9498 19.3335 14 19.3335 18.0503 16.0498 21.3333 12.0002 21.3333 7.9506 21.3333 4.6668 18.0503 4.6668 14Z"
            style={{ fillRule: "evenodd", fill: "rgba(233,180,58,0.4)" }}
          />
          <path
            d="M12.0002 12.3333C12.5524 12.3333 13.0002 12.7811 13.0002 13.3333V14.6667C13.0002 15.2189 12.5524 15.6667 12.0002 15.6667 11.4479 15.6667 11.0002 15.2189 11.0002 14.6667V13.3333C11.0002 12.7811 11.4479 12.3333 12.0002 12.3333Z"
            style={{ fillRule: "evenodd", fill: "#e9b43a" }}
          />
          <path
            d="M4.6667 0C2.0891 0 0 2.0891 0 4.6667V7C0 7.5523 0.4477 8 1 8 1.5523 8 2 7.5523 2 7V4.6667C2 3.1936 3.1936 2 4.6667 2 6.1397 2 7.3333 3.1936 7.3333 4.6667V8.343C7.9284 7.8515 8.6024 7.4521 9.3333 7.1667V4.6667C9.3333 2.0891 7.2443 0 4.6667 0Z"
            style={{ fillRule: "nonzero", fill: "#e9b43a" }}
          />
        </g>
      </svg>
    </div>
  );
}

function MoneyIcon() {
  const box = useIconBox();

  return (
    <div style={box}>
      <div
        style={{
          overflow: "hidden",
          left: 0,
          top: "10.8%",
          right: 0,
          bottom: "10.9%",
          width: "100%",
          height: "78.3%",
          position: "absolute",
        }}
      >
        <svg
          width="24"
          height="18.784261804339035"
          viewBox="0 0 24 18.784261804339035"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          preserveAspectRatio="none"
          style={{
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
            width: "100%",
            height: "100%",
            position: "absolute",
          }}
        >
          <path
            d="M17.4492 0.0034C19.3923 0.0519 21.216 0.6145 23.1562 1.56 23.672 1.8114 24 2.336 24 2.9097V15.9097C23.9998 16.4266 23.7334 16.9071 23.295 17.1811 22.8566 17.4551 22.3084 17.4835 21.8438 17.2573 20.21 16.4611 18.8497 16.1722 17.4805 16.2339 16.0782 16.297 14.553 16.7321 12.5879 17.5679 10.3815 18.5063 8.4342 18.8763 6.502 18.7651 4.5925 18.6551 2.801 18.0801 0.9199 17.2925 0.3628 17.0589 0.0002 16.5138 0 15.9097V2.9097C0 2.4077 0.252 1.9377 0.6699 1.6597 1.0877 1.3821 1.6174 1.3311 2.0801 1.5249 3.769 2.2321 5.1688 2.5539 6.5684 2.5366 7.9745 2.5192 9.4923 2.1578 11.4121 1.3413 13.5737 0.4219 15.5085-0.0449 17.4492 0.0034ZM12 6.4097C10.3431 6.4097 9 7.7528 9 9.4097 9.0003 11.0663 10.3433 12.4097 12 12.4097 13.6567 12.4097 14.9997 11.0663 15 9.4097 15 7.7528 13.6569 6.4097 12 6.4097Z"
            style={{ fillRule: "nonzero", fill: "#12c25b" }}
          />
        </svg>
      </div>
    </div>
  );
}

function TranslateIcon() {
  const clipId = useId();
  const box = useIconBox();

  return (
    <div style={box}>
      <svg
        width="20.000701904296875"
        height="20.000228881835938"
        viewBox="0 0 20.000701904296875 20.000228881835938"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        style={{
          left: "8.3%",
          top: "8.3%",
          right: "8.3%",
          bottom: "8.3%",
          width: "83.3%",
          height: "83.3%",
          position: "absolute",
        }}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x="0" y="0" width="20.000701904296875" height="20.000228881835938" />
          </clipPath>
        </defs>
        <g style={{ clipPath: `url(#${clipId})` }}>
          <path
            d="M7.3334 1C7.3334 0.4477 6.8857 0 6.3334 0 5.7811 0 5.3334 0.4477 5.3334 1V2.6667H1C0.4478 2.6667 0 3.1144 0 3.6667 0 4.2189 0.4478 4.6667 1 4.6667H2.7513C2.9957 6.4044 3.731 8.0023 4.8283 9.2978 4.6588 9.408 4.4884 9.5094 4.3184 9.6028 3.453 10.0784 2.5949 10.3476 1.9494 10.4971 1.6283 10.5715 1.3646 10.6152 1.1852 10.6399 1.0593 10.6573 0.9925 10.6641 0.9316 10.669 0.3813 10.7067-0.0346 11.183 0.0023 11.7335 0.0392 12.2845 0.5158 12.7013 1.0669 12.6644L1.0691 12.6643C1.174 12.6569 1.2765 12.6463 1.4586 12.6212 1.6897 12.5892 2.0134 12.5352 2.4007 12.4456 3.1718 12.2669 4.2137 11.9424 5.2817 11.3555 5.6271 11.1657 5.9745 10.9485 6.3158 10.7007 7.0296 11.2369 7.8281 11.6728 8.6929 11.9853 9.2123 12.1732 9.7855 11.9043 9.9733 11.3849 10.1611 10.8655 9.8922 10.2923 9.3728 10.1045 8.8192 9.9044 8.3004 9.6396 7.8243 9.3199 8.808 8.1817 9.5922 6.6675 9.895 4.6667H11.6667C12.219 4.6667 12.6667 4.2189 12.6667 3.6667 12.6667 3.1144 12.219 2.6667 11.6667 2.6667H7.3334V1ZM7.8668 4.6667H6.3334 4.7768C5.0016 5.9064 5.548 7.0456 6.3364 7.9838 7.0357 7.1633 7.6016 6.087 7.8668 4.6667Z"
            style={{ fillRule: "evenodd", fill: "rgba(27,98,242,0.4)" }}
          />
          <path
            d="M14.3336 7.3333C13.9168 7.3333 13.5436 7.5919 13.3972 7.9822L9.3973 18.6489C9.2034 19.166 9.4654 19.7424 9.9825 19.9363 10.4996 20.1303 11.076 19.8683 11.2699 19.3511L12.2766 16.6667H17.0572L18.0639 19.3511C18.2579 19.8683 18.8343 20.1303 19.3514 19.9363 19.8686 19.7424 20.1306 19.166 19.9366 18.6489L15.9366 7.9822C15.7903 7.5919 15.4171 7.3333 15.0003 7.3333H14.3336ZM16.3072 14.6667L14.667 10.2924 13.0266 14.6667H16.3072Z"
            style={{ fillRule: "evenodd", fill: "#1b62f2" }}
          />
        </g>
      </svg>
    </div>
  );
}

function ShopIcon() {
  const clipId = useId();
  const box = useIconBox();

  return (
    <div style={box}>
      <svg
        width="21.33333396911621"
        height="21.33333396911621"
        viewBox="0 0 21.33333396911621 21.33333396911621"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        style={{
          left: "5.6%",
          top: "5.6%",
          right: "5.6%",
          bottom: "5.6%",
          width: "88.9%",
          height: "88.9%",
          position: "absolute",
        }}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x="0" y="0" width="21.33333396911621" height="21.33333396911621" />
          </clipPath>
        </defs>
        <g style={{ clipPath: `url(#${clipId})` }}>
          <path
            d="M3.6665 5.6068L17.6665 5.6064C17.9317 5.6064 18.1861 5.7117 18.3736 5.8993 18.5612 6.0868 18.6665 6.3412 18.6665 6.6064V20.3333C18.6665 20.8856 18.2188 21.3333 17.6665 21.3333H3.6665C3.1142 21.3333 2.6665 20.8856 2.6665 20.3333V6.6068C2.6665 6.0545 3.1142 5.6068 3.6665 5.6068Z"
            style={{ fillRule: "evenodd", fill: "rgba(255,88,0,0.4)" }}
          />
          <path
            d="M2.4137 1.1778C2.8288 0.4503 3.6027 0 4.441 0H16.8903C17.7274 0 18.5033 0.4493 18.9189 1.1778L21.1915 5.1722C21.3509 5.4524 21.3654 5.7923 21.2306 6.0851 20.4419 7.7969 18.7167 9 16.6957 9 15.5537 9 14.5133 8.6106 13.6811 7.9714 12.8493 8.6105 11.8094 9 10.6663 9 9.523 9 8.4824 8.6096 7.6503 7.9702 6.8183 8.6096 5.7777 9 4.6343 9 2.6117 9 0.888 7.7967 0.0994 6.0851-0.0356 5.7921-0.0209 5.452 0.1387 5.1717L2.4137 1.1778Z"
            style={{ fillRule: "evenodd", fill: BRAND_ORANGE }}
          />
          <path
            d="M7.9998 20V15.3334C7.9998 13.8611 9.1942 12.6667 10.6665 12.6667 12.1388 12.6667 13.3332 13.8611 13.3332 15.3334V20H7.9998Z"
            style={{ fillRule: "nonzero", fill: BRAND_ORANGE }}
          />
          <path
            d="M-0.0002 20.3334C-0.0002 19.7811 0.4476 19.3334 0.9998 19.3334H20.3332C20.8854 19.3334 21.3332 19.7811 21.3332 20.3334 21.3332 20.8856 20.8854 21.3334 20.3332 21.3334H0.9998C0.4476 21.3334-0.0002 20.8856-0.0002 20.3334Z"
            style={{ fillRule: "evenodd", fill: BRAND_ORANGE }}
          />
        </g>
      </svg>
    </div>
  );
}

function FollowUs({
  left = 387,
  top = 875,
  right,
  columnGap = 12,
  fontSize = 18,
  letterSpacing = -0.7,
  iconWidth = 17.6,
  iconHeight = 18,
}: {
  left?: number | "auto";
  top?: number;
  right?: number;
  columnGap?: number;
  fontSize?: number;
  letterSpacing?: number;
  iconWidth?: number;
  iconHeight?: number;
}) {
  return (
    <a
      href="https://x.com/allies_ai"
      target="_blank"
      rel="noreferrer"
      aria-label="Follow Allies on X at @allies_ai"
      style={{
        display: "flex",
        flexDirection: "row",
        columnGap,
        alignItems: "center",
        justifyContent: "flex-start",
        left,
        right,
        top,
        width: "min-content",
        position: "absolute",
        color: "inherit",
        cursor: "pointer",
        textDecoration: "none",
      }}
    >
      <span
        className="text"
        style={{
          display: "inline",
          textAlign: "left",
          fontSize,
          fontWeight: 600,
          fontStretch: "100%",
          letterSpacing,
          color: "#757575",
          width: "max-content",
          position: "relative",
          flexShrink: 0,
          whiteSpace: "pre-wrap",
          overflowWrap: "break-word",
        }}
      >
        Follow us
      </span>
      <div
        style={{
          overflow: "hidden",
          width: iconWidth,
          height: iconHeight,
          position: "relative",
          flexShrink: 0,
        }}
      >
        <svg
          width="17.603912353515625"
          height="17.99075698852539"
          viewBox="0 0 17.603912353515625 17.99075698852539"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          preserveAspectRatio="none"
          style={{
            left: 0,
            top: 0,
            right: 0,
            bottom: "0.1%",
            width: "100%",
            height: "99.9%",
            position: "absolute",
          }}
        >
          <path
            d="M10.4767 7.6179L17.0302 0H15.4772L9.7869 6.6145 5.242 0H0L6.8727 10.0023 0 17.9908H1.553L7.5622 11.0056 12.3619 17.9908H17.6039L10.4763 7.6179H10.4767ZM8.3496 10.0904L7.6533 9.0944 2.1126 1.1691H4.498L8.9694 7.5651 9.6657 8.5611 15.4779 16.8748H13.0926L8.3496 10.0908V10.0904Z"
            style={{ fillRule: "nonzero", fill: "#757575" }}
          />
        </svg>
      </div>
    </a>
  );
}

function LogoMark({
  left = "calc(-369px + 50%)",
  top = 88,
}: {
  left?: number | string;
  top?: number;
}) {
  const clipId = useId();

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        columnGap: 8.6,
        alignItems: "center",
        justifyContent: "flex-start",
        left,
        top,
        width: "min-content",
        position: "absolute",
      }}
    >
      <div
        style={{
          borderRadius: 6,
          backgroundColor: BRAND_ORANGE,
          overflow: "hidden",
          width: 24.6,
          height: 24,
          position: "relative",
          flexShrink: 0,
        }}
      >
        <Image
          src="/allies-icon.svg"
          alt=""
          aria-hidden="true"
          draggable={false}
          width={25}
          height={24}
          style={{ display: "block", width: "100%", height: "100%" }}
        />
        <div
          style={{
            overflow: "hidden",
            display: "none",
            left: "calc(-7.5px + 50%)",
            top: "calc(-8px + 50%)",
            width: 14.7,
            height: 16,
            position: "absolute",
          }}
        >
          <svg
            width="15.682546823223662"
            height="17.018763184547424"
            viewBox="0 0 15.682546823223662 17.018763184547424"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            preserveAspectRatio="none"
            style={{
              left: "-3.7%",
              top: "-3.4%",
              right: "-3.2%",
              bottom: "-3%",
              width: "106.9%",
              height: "106.4%",
              position: "absolute",
            }}
          >
            <path
              d="M12.3954 11.466C13.3883 10.4383 14.4351 9.4811 14.65 6.7305 14.865 3.9798 12.5609 0 7.4517 0 2.3425 0-0.1279 4.1511 0.0051 6.8715 0.1381 9.5919 0.9933 10.4916 2.2184 11.4861 3.3354 12.3929 2.5493 14.3098 3.625 14.67 4.7006 15.0302 5.4586 12.8967 5.7141 12.8967 5.9697 12.8967 5.921 16 7.4517 16 8.9824 16 8.8123 12.8967 9.0835 12.8967 9.3547 12.8967 9.8558 14.8728 11.0302 14.6297 12.2046 14.3866 11.4025 12.4937 12.3954 11.466Z"
              transform=" translate(0.5447706334116094 0.541815293092125)"
              style={{ fillRule: "nonzero", fill: "#fff" }}
            />
            <path
              d="M12.3954 11.466C13.3883 10.4383 14.4351 9.4811 14.65 6.7305 14.865 3.9798 12.5609 0 7.4517 0 2.3425 0-0.1279 4.1511 0.0051 6.8715 0.1381 9.5919 0.9933 10.4916 2.2184 11.4861 3.3354 12.3929 2.5493 14.3098 3.625 14.67 4.7006 15.0302 5.4586 12.8967 5.7141 12.8967 5.9697 12.8967 5.921 16 7.4517 16 8.9824 16 8.8123 12.8967 9.0835 12.8967 9.3547 12.8967 9.8558 14.8728 11.0302 14.6297 12.2046 14.3866 11.4025 12.4937 12.3954 11.466Z"
              transform=" translate(0.5447706334116094 0.541815293092125)"
              style={{ stroke: "#000", strokeWidth: 1.0187631845474243 }}
            />
          </svg>
          <LogoEyes />
        </div>
      </div>
      <svg
        width="50.446250915527344"
        height="18"
        viewBox="0 0 50.446250915527344 18"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        style={{ width: 50.4, height: 18, position: "relative", flexShrink: 0 }}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x="0" y="0" width="50.446250915527344" height="18" />
          </clipPath>
        </defs>
        <g style={{ clipPath: `url(#${clipId})` }}>
          <path
            d="M48.2232 8.6198C47.7025 8.6777 47.4215 8.4463 47.1157 8.0083 46.7356 7.4959 46.0827 7.1157 45.1075 7.1157 43.8595 7.1157 42.9091 7.7107 42.9174 8.5702 42.9091 9.3058 43.4215 9.7521 44.7108 10.0413L46.8761 10.5041C49.2728 11.0248 50.438 12.1322 50.4463 13.9421 50.438 16.3471 48.1984 17.9917 45.0248 17.9917 42.3637 17.9917 40.5455 16.9835 39.843 15.2314 39.6033 14.6446 39.9504 14.2397 40.5703 14.1818L41.7025 14.0744C42.2314 14.0248 42.5042 14.2645 42.7934 14.7273 43.2149 15.3967 43.9752 15.7355 45.0166 15.7355 46.438 15.7355 47.3802 15.0826 47.3802 14.2149 47.3802 13.4959 46.8347 13.0248 45.6694 12.7686L43.5042 12.314C41.0661 11.8099 39.9256 10.5868 39.9339 8.7355 39.9256 6.3884 42.0083 4.8843 45.0661 4.8843 47.5703 4.8843 49.1901 5.8595 49.8843 7.4463 50.1323 8.0331 49.8017 8.4463 49.1736 8.5124L48.2232 8.6198Z"
            style={{ fillRule: "nonzero", fill: BRAND_ORANGE }}
          />
          <path
            d="M33.1285 17.9917C29.302 17.9917 26.9632 15.4545 26.9632 11.4711 26.9632 7.5537 29.3351 4.8843 32.9715 4.8843 36.0954 4.8843 38.7731 6.843 38.7731 11.2975V11.3058C38.7731 11.8926 38.4508 12.2149 37.864 12.2149H29.9301C29.9549 14.3884 31.2359 15.6612 33.1698 15.6612 34.1615 15.6612 34.9797 15.3306 35.4839 14.6859 35.8062 14.2645 36.1037 14.0496 36.6161 14.1074L37.6243 14.2231C38.2607 14.2975 38.5913 14.6446 38.3847 15.1157 37.6078 16.876 35.7235 17.9917 33.1285 17.9917ZM29.9384 10.1983H35.9053C35.8888 8.4711 34.7318 7.2149 33.0128 7.2149 31.2277 7.2149 30.0293 8.5785 29.9384 10.1983Z"
            style={{ fillRule: "nonzero", fill: BRAND_ORANGE }}
          />
          <path
            d="M24.1083 3.2479C23.1496 3.2479 22.3727 2.5207 22.3727 1.6281 22.3727 0.7273 23.1496 0 24.1083 0 25.0587 0 25.8355 0.7273 25.8355 1.6281 25.8355 2.5207 25.0587 3.2479 24.1083 3.2479ZM22.6041 16.8347V5.9587C22.6041 5.3719 22.9265 5.0496 23.5132 5.0496H24.6868C25.2736 5.0496 25.5959 5.3719 25.5959 5.9587V16.8347C25.5959 17.4215 25.2736 17.7438 24.6868 17.7438H23.5132C22.9265 17.7438 22.6041 17.4215 22.6041 16.8347Z"
            style={{ fillRule: "nonzero", fill: BRAND_ORANGE }}
          />
          <path
            d="M20.6913 16.8347C20.6913 17.4215 20.3689 17.7438 19.7822 17.7438H18.6086C18.0218 17.7438 17.6995 17.4215 17.6995 16.8347V1.7273C17.6995 1.1405 18.0218 0.8182 18.6086 0.8182H19.7822C20.3689 0.8182 20.6913 1.1405 20.6913 1.7273V16.8347Z"
            style={{ fillRule: "nonzero", fill: BRAND_ORANGE }}
          />
          <path
            d="M15.7868 16.8347C15.7868 17.4215 15.4645 17.7438 14.8777 17.7438H13.7041C13.1174 17.7438 12.795 17.4215 12.795 16.8347V1.7273C12.795 1.1405 13.1174 0.8182 13.7041 0.8182H14.8777C15.4645 0.8182 15.7868 1.1405 15.7868 1.7273V16.8347Z"
            style={{ fillRule: "nonzero", fill: BRAND_ORANGE }}
          />
          <path
            d="M4.2479 18C1.8264 18 0 16.6777 0 14.1818 0 11.3223 2.3554 10.5868 4.8182 10.3223 7.0578 10.0826 7.9587 10.0413 7.9587 9.1818V9.1322C7.9587 7.8843 7.1983 7.1735 5.8099 7.1735 4.7438 7.1735 4.0083 7.5702 3.5702 8.1157 3.2479 8.5372 2.9587 8.7521 2.438 8.6777L1.438 8.5372C0.8016 8.4463 0.4959 8.0083 0.8016 7.4297 1.7025 5.7438 3.5207 4.8843 5.7934 4.8843 8.2149 4.8843 10.9504 5.8926 10.9504 9.2479V16.8347C10.9504 17.4215 10.6281 17.7438 10.0413 17.7438H8.9835C8.3967 17.7438 8.0744 17.4298 8.0744 16.8678V16H7.9752C7.4297 17.0661 6.2397 18 4.2479 18ZM2.8843 14.1322C2.8843 15.2314 3.7769 15.8016 5.0248 15.8016 6.8264 15.8016 7.9669 14.6033 7.9669 13.1901V11.6942C7.5785 12.0083 6.0083 12.2066 5.2231 12.314 3.8843 12.5041 2.8843 12.9835 2.8843 14.1322Z"
            style={{ fillRule: "nonzero", fill: BRAND_ORANGE }}
          />
        </g>
      </svg>
    </div>
  );
}

const LOGO_EYE_MASK =
  "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMi4zMDE3MDIwMjI1NTI0OTAyIiBoZWlnaHQ9IjQuMzE2NDc3Nzc1NTczNzMwNSIgdmlld0JveD0iMCAwIDIuMzAxNzAyMDIyNTUyNDkwMiA0LjMxNjQ3Nzc3NTU3MzczMDUiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiIHByZXNlcnZlQXNwZWN0UmF0aW89Im5vbmUiIHN0eWxlPSJsZWZ0OiAwcHg7dG9wOiAwcHg7cmlnaHQ6IDBweDtib3R0b206IDBweDt0cmFuc2Zvcm06IG1hdHJpeCgxLDAsMCwxLDAsMCk7dHJhbnNmb3JtLW9yaWdpbjogMCAwOyI+PGRlZnM+PGNsaXBQYXRoIGlkPSJkZWZfMCI+PHJlY3QgeD0iMCIgeT0iMCIgd2lkdGg9IjIuMzAxNzAyMDIyNTUyNDkwMiIgaGVpZ2h0PSI0LjMxNjQ3Nzc3NTU3MzczMDUiPjwvcmVjdD48L2NsaXBQYXRoPjwvZGVmcz48ZyBpZD0ibWFza191bmRlZmluZWQiIG1hc2tVbml0cz0idXNlclNwYWNlT25Vc2UiIHg9IjAiIHk9IjAiIHdpZHRoPSIyLjMwMTcwMjAyMjU1MjQ5MDIiIGhlaWdodD0iNC4zMTY0Nzc3NTU3MzczMDUiIHN0eWxlPSJtYXNrLXR5cGU6IGx1bWluYW5jZTsiPjxnIHN0eWxlPSJjbGlwLXBhdGg6IHVybCgjZGVmXzApOyI+PHBhdGggZD0iTTEuMTUzMiAwQzEuNzg1NiAwIDIuMzAxNyAwLjk2MzEgMi4zMDE3IDIuMTU4MiAyLjMwMTcgMy4zNTM0IDEuNzg1NiA0LjMxNjUgMS4xNTMyIDQuMzE2NSAwLjUxNjEgNC4zMTY1IDAgMy4zNTM0IDAgMi4xNTgyIDAgMC45NjMxIDAuNTE2MSAwIDEuMTUzMiAwWiIgc3R5bGU9ImZpbGwtcnVsZTogbm9uemVybztmaWxsOiAjMDAwOyIgLz48L2c+PC9nPjwvc3ZnPg==";

function LogoEyes() {
  return (
    <div
      style={{
        overflow: "hidden",
        left: "calc(-5.3px + 50%)",
        top: 3.7,
        width: 6.1,
        height: 4.3,
        position: "absolute",
      }}
    >
      <LogoEye left={0} />
      <LogoEye left={3.8} />
    </div>
  );
}

function LogoEye({ left }: { left: number }) {
  return (
    <div
      style={{
        overflow: "hidden",
        left,
        top: 0,
        width: 2.3,
        height: 4.3,
        position: "absolute",
      }}
    >
      <svg
        width="2.3017020225524907"
        height="4.32141637802124"
        viewBox="0 0 2.3017020225524907 4.32141637802124"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        style={{
          left: "0.1%",
          top: 0,
          right: 0,
          bottom: 0,
          width: "99.9%",
          height: "100%",
          position: "absolute",
        }}
      >
        <path
          d="M1.1509 0C1.7865 0 2.3017 0.9675 2.3017 2.1607 2.3017 3.3539 1.7865 4.3214 1.1509 4.3214 0.5152 4.3214 0 3.3539 0 2.1607 0 0.9675 0.5152 0 1.1509 0Z"
          style={{ fillRule: "nonzero", fill: "#000" }}
        />
      </svg>
      <div
        style={{
          overflow: "hidden",
          left: 0,
          top: "0.1%",
          right: "0.1%",
          bottom: "0.1%",
          width: "99.9%",
          height: "99.9%",
          position: "absolute",
        }}
      >
        <div
          style={{
            overflow: "hidden",
            left: "-23.7%",
            top: "29.1%",
            right: "53%",
            bottom: "28.5%",
            width: "70.7%",
            height: "42.3%",
            position: "absolute",
            maskImage: `url("${LOGO_EYE_MASK}")`,
            WebkitMaskImage: `url("${LOGO_EYE_MASK}")`,
            maskRepeat: "no-repeat",
            WebkitMaskRepeat: "no-repeat",
            maskType: "luminance",
            maskPosition: "0.5px -1.3px",
            WebkitMaskPosition: "0.5px -1.3px",
          }}
        >
          <svg
            width="1.827701210975647"
            height="1.6274662017822266"
            viewBox="0 0 1.827701210975647 1.6274662017822266"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            preserveAspectRatio="none"
            style={{
              transformOrigin: "0 0",
              transform: "rotate(90deg)",
              left: "100%",
              top: 0,
              right: "-112.3%",
              bottom: "11%",
              width: "112.3%",
              height: "89%",
              position: "absolute",
            }}
          >
            <path
              d="M0.9849 0.1266l0.7746 1.3795c0.0305 0.0543-0.0088 0.1214-0.071 0.1214h-1.5493c-0.0623 0-0.1016-0.0671-0.071-0.1214l0.7746-1.3795c0.0311-0.0555 0.111-0.0555 0.1421 0z"
              style={{ fillRule: "nonzero", fill: "#fff" }}
            />
          </svg>
        </div>
      </div>
    </div>
  );
}

const YELLOW_EYE_MASK =
  "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNCIgaGVpZ2h0PSI3IiB2aWV3Qm94PSIwIDAgNCA3IiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHhtbG5zOnhsaW5rPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5L3hsaW5rIiBwcmVzZXJ2ZUFzcGVjdFJhdGlvPSJub25lIiBzdHlsZT0ibGVmdDogMHB4O3RvcDogMHB4O3JpZ2h0OiAwcHg7Ym90dG9tOiAwcHg7dHJhbnNmb3JtOiBtYXRyaXgoMSwwLDAsMSwwLDApO3RyYW5zZm9ybS1vcmlnaW46IDAgMDsiPjxkZWZzPjxjbGlwUGF0aCBpZD0iZGVmXzAiPjxyZWN0IHg9IjAiIHk9IjAiIHdpZHRoPSIzLjY2Mzc0NjU5NTM4MjY5MDQiIGhlaWdodD0iNi44NzA3NzY2NTMyODk3OTUiPjwvcmVjdD48L2NsaXBQYXRoPjwvZGVmcz48ZyBpZD0ibWFza191bmRlZmluZWQiIG1hc2tVbml0cz0idXNlclNwYWNlT25Vc2UiIHg9IjAiIHk9IjAiIHdpZHRoPSIzLjY2Mzc0NjU5NTM4MjY5MDQiIGhlaWdodD0iNi44NzA3NzY2NTMyODk3OTUiIHN0eWxlPSJtYXNrLXR5cGU6IGx1bWluYW5jZTsiPjxnIHN0eWxlPSJjbGlwLXBhdGg6IHVybCgjZGVmXzApOyI+PHBhdGggZD0iTTEuODM1NiAwQzIuODQyMiAwIDMuNjYzNyAxLjUzMyAzLjY2MzcgMy40MzU0IDMuNjYzNyA1LjMzNzggMi44NDIyIDYuODcwOCAxLjgzNTYgNi44NzA4IDAuODIxNiA2Ljg3MDggMCA1LjMzNzggMCAzLjQzNTQgMCAxLjUzMyAwLjgyMTYgMCAxLjgzNTYgMFoiIHN0eWxlPSJmaWxsLXJ1bGU6IG5vbnplcm87ZmlsbDogIzAwMDsiIC8+PC9nPjwvZz48L3N2Zz4=";

function YellowAlly({
  left = 1023,
  top = 584,
  width = 62,
  faceLeft = 26,
  flipCursor = false,
  state = "idle",
  showCursor = true,
}: {
  left?: number | string;
  top?: number;
  width?: number;
  faceLeft?: number;
  flipCursor?: boolean;
  state?: AllyAnimationState;
  showCursor?: boolean;
}) {
  return (
    <div
      style={{
        overflow: "hidden",
        left,
        top,
        width,
        height: 60,
        position: "absolute",
      }}
    >
      <div
        className="ally-face"
        style={{
          left: faceLeft,
          top: 24,
          width: 36,
          height: 36,
          position: "absolute",
        }}
      >
        <AllyAvatar shape="boxy" state={state} color="#fbe65f" size={36} />
      </div>
      <div
        className="ally-face"
        style={{
          display: "none",
          borderRadius: 100,
          backgroundColor: "#fbe65f",
          overflow: "hidden",
          left: faceLeft,
          top: 24,
          width: 36,
          height: 36,
          position: "absolute",
        }}
      >
        <div
          style={{
            overflow: "hidden",
            left: "calc(-12px + 50%)",
            top: "calc(-12px + 50%)",
            width: 24,
            height: 24,
            position: "absolute",
          }}
        >
          <div
            style={{
              borderWidth: 1.6,
              borderStyle: "solid",
              borderColor: "#000",
              borderRadius: 6.5,
              backgroundColor: "#fff",
              left: "calc(-12px + 50%)",
              top: "calc(-12px + 50%)",
              width: 24,
              height: 24,
              position: "absolute",
            }}
          />
          <div
            className="ally-eyes"
            style={{
              overflow: "hidden",
              left: "calc(-0.9px + 50%)",
              top: 10.1,
              width: 9.8,
              height: 6.9,
              position: "absolute",
            }}
          >
            <YellowEye left={0} />
            <YellowEye left={6.1} />
          </div>
        </div>
      </div>
      {showCursor ? (
        <div
          style={{
            overflow: "hidden",
            transformOrigin: flipCursor ? "0 0" : undefined,
            transform: flipCursor ? "scale(-1,1)" : undefined,
            left: flipCursor ? 60 : 0,
            top: 0,
            width: 36,
            height: 36,
            position: "absolute",
          }}
        >
          <CursorMark fill="#fbe65f" />
        </div>
      ) : null}
    </div>
  );
}

function YellowEye({ left }: { left: number }) {
  return (
    <div
      style={{
        overflow: "hidden",
        left,
        top: 0,
        width: 3.7,
        height: 6.9,
        position: "absolute",
      }}
    >
      <svg
        width="3.6637465953826904"
        height="6.878637313842773"
        viewBox="0 0 3.6637465953826904 6.878637313842773"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        style={{
          top: 0,
          right: 0,
          width: 3.7,
          height: 6.9,
          position: "absolute",
        }}
      >
        <path
          d="M1.8319 0C2.8437 0 3.6637 1.54 3.6637 3.4393 3.6637 5.3386 2.8437 6.8786 1.8319 6.8786 0.8201 6.8786 0 5.3386 0 3.4393 0 1.54 0.8201 0 1.8319 0Z"
          style={{ fillRule: "nonzero", fill: "#000" }}
        />
      </svg>
      <div
        style={{
          overflow: "hidden",
          left: 0,
          top: "0.1%",
          right: "0.1%",
          bottom: "0.1%",
          width: "99.9%",
          height: "99.9%",
          position: "absolute",
        }}
      >
        <div
          style={{
            overflow: "hidden",
            left: "-23.7%",
            top: "29.1%",
            right: "53%",
            bottom: "28.5%",
            width: "70.7%",
            height: "42.3%",
            position: "absolute",
            maskImage: `url("${YELLOW_EYE_MASK}")`,
            WebkitMaskImage: `url("${YELLOW_EYE_MASK}")`,
            maskRepeat: "no-repeat",
            WebkitMaskRepeat: "no-repeat",
            maskType: "luminance",
            maskPosition: "0.9px -2px",
            WebkitMaskPosition: "0.9px -2px",
          }}
        >
          <svg
            width="2.9092531204223633"
            height="2.59053"
            viewBox="0 0 2.9092531204223633 2.59053"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            preserveAspectRatio="none"
            style={{
              transformOrigin: "0 0",
              transform: "rotate(90deg)",
              top: 0,
              right: -2.9,
              width: 2.9,
              height: 2.6,
              position: "absolute",
            }}
          >
            <path
              d="M1.5677 0.2014l1.233 2.1959c0.0486 0.0865-0.0139 0.1933-0.1131 0.1932h-2.466c-0.0992 0-0.1617-0.1068-0.1131-0.1932l1.233-2.1959c0.0496-0.0883 0.1767-0.0883 0.2262 0z"
              style={{ fillRule: "nonzero", fill: "#fff" }}
            />
          </svg>
        </div>
      </div>
    </div>
  );
}

const GREEN_EYE_MASK =
  "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMy40Mjc5MDM2NTIxOTExNjIiIGhlaWdodD0iNi40Mjg0OTAxNjE4OTU3NTIiIHZpZXdCb3g9IjAgMCAzLjQyNzkwMzY1MjE5MTE2MiA2LjQyODQ5MDE2MTg5NTc1MiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgcHJlc2VydmVBc3BlY3RSYXRpbz0ibm9uZSIgc3R5bGU9ImxlZnQ6IDBweDt0b3A6IDBweDtyaWdodDogMHB4O2JvdHRvbTogMHB4O3RyYW5zZm9ybTogbWF0cml4KDEsMCwwLDEsMCwwKTt0cmFuc2Zvcm0tb3JpZ2luOiAwIDA7Ij48ZGVmcz48Y2xpcFBhdGggaWQ9ImRlZl8wIj48cmVjdCB4PSIwIiB5PSIwIiB3aWR0aD0iMy40Mjc5MDM2NTIxOTExNjIiIGhlaWdodD0iNi40Mjg0OTAxNjE4OTU3NTIiPjwvcmVjdD48L2NsaXBQYXRoPjwvZGVmcz48ZyBpZD0ibWFza191bmRlZmluZWQiIG1hc2tVbml0cz0idXNlclNwYWNlT25Vc2UiIHg9IjAiIHk9IjAiIHdpZHRoPSIzLjQyNzkwMzY1MjE5MTE2MiIgaGVpZ2h0PSI2LjQyODQ5MDE2MTg5NTc1MiIgc3R5bGU9Im1hc2stdHlwZTogbHVtaW5hbmNlOyI+PGcgc3R5bGU9ImNsaXAtcGF0aDogdXJsKCNkZWZfMCk7Ij48cGF0aCBkPSJNMS43MTc0IDBDMi42NTkyIDAgMy40Mjc5IDEuNDM0MyAzLjQyNzkgMy4yMTQyIDMuNDI3OSA0Ljk5NDIgMi42NTkyIDYuNDI4NSAxLjcxNzQgNi40Mjg1IDAuNzY4NyA2LjQyODUgMCA0Ljk5NDIgMCAzLjIxNDIgMCAxLjQzNDMgMC43Njg3IDAgMS43MTc0IDBaIiBzdHlsZT0iZmlsbC1ydWxlOiBub256ZXJvO2ZpbGw6ICMwMDA7IiAvPjwvZz48L2c+PC9zdmc+";

function GreenAlly({
  left = "calc(-274px + 50%)",
  top = 784,
  state = "idle",
  showCursor = true,
}: {
  left?: number | string;
  top?: number;
  state?: AllyAnimationState;
  showCursor?: boolean;
}) {
  return (
    <div
      style={{
        overflow: "hidden",
        left,
        top,
        width: 62,
        height: 60,
        position: "absolute",
      }}
    >
      <div
        className="ally-face"
        style={{
          left: 26,
          top: 24,
          width: 36,
          height: 36,
          position: "absolute",
        }}
      >
        <AllyAvatar shape="rocky" state={state} color="#12c25b" size={36} />
      </div>
      <div
        className="ally-face"
        style={{
          display: "none",
          borderRadius: 100,
          backgroundColor: "#12c25b",
          overflow: "hidden",
          left: 26,
          top: 24,
          width: 36,
          height: 36,
          position: "absolute",
        }}
      >
        <div
          style={{
            overflow: "hidden",
            left: "calc(-12px + 50%)",
            top: "calc(-11px + 50%)",
            width: 24.7,
            height: 22,
            position: "absolute",
          }}
        >
          <svg
            width="26.222559618744608"
            height="23.517239575217122"
            viewBox="0 0 26.222559618744608 23.517239575217122"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            preserveAspectRatio="none"
            style={{
              left: "calc(-13.2px + 50%)",
              top: "calc(-11.8px + 50%)",
              width: 26.2,
              height: 23.5,
              position: "absolute",
            }}
          >
            <path
              d="M14.6001 0.0001c6.0059-0.0368 12.124 14.87 9.4667 19.5942-1.6861 2.9976-7.4379 2.4446-12.4457 2.2032-5.0077-0.2414-10.9855 0.0545-11.5583-4.4393-0.9228-7.2404 8.5314-17.3213 14.5373-17.3581z"
              transform=" translate(0.8052124278313405 0.8109333064961849)"
              style={{ fillRule: "nonzero", fill: "#fff" }}
            />
            <path
              d="M14.6001 0.0001c6.0059-0.0368 12.124 14.87 9.4667 19.5942-1.6861 2.9976-7.4379 2.4446-12.4457 2.2032-5.0077-0.2414-10.9855 0.0545-11.5583-4.4393-0.9228-7.2404 8.5314-17.3213 14.5373-17.3581z"
              transform=" translate(0.8052124278313405 0.8109333064961849)"
              style={{ stroke: "#000", strokeWidth: 1.5172345638275146 }}
            />
          </svg>
          <div
            className="ally-eyes"
            style={{
              overflow: "hidden",
              left: "calc(-7.6px + 50%)",
              top: 8.4,
              width: 9.1,
              height: 6.4,
              position: "absolute",
            }}
          >
            <GreenEye left={0} />
            <GreenEye left={5.7} />
          </div>
        </div>
      </div>
      {showCursor ? (
        <div
          style={{
            overflow: "hidden",
            left: 0,
            top: 0,
            width: 36,
            height: 36,
            position: "absolute",
          }}
        >
          <CursorMark fill="#12c25b" />
        </div>
      ) : null}
    </div>
  );
}

function GreenEye({ left }: { left: number }) {
  return (
    <div
      style={{
        overflow: "hidden",
        left,
        top: 0,
        width: 3.4,
        height: 6.4,
        position: "absolute",
      }}
    >
      <svg
        width="3.427903652191162"
        height="6.435845851898193"
        viewBox="0 0 3.427903652191162 6.435845851898193"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        style={{
          left: left === 0 ? "0.1%" : 0,
          top: 0,
          right: 0,
          bottom: 0,
          width: left === 0 ? "99.9%" : "100%",
          height: "100%",
          position: "absolute",
        }}
      >
        <path
          d="M1.714 0C2.6606 0 3.4279 1.4409 3.4279 3.2179 3.4279 4.995 2.6606 6.4358 1.714 6.4358 0.7673 6.4358 0 4.995 0 3.2179 0 1.4409 0.7673 0 1.714 0Z"
          style={{ fillRule: "nonzero", fill: "#000" }}
        />
      </svg>
      <div
        style={{
          overflow: "hidden",
          left: 0,
          top: "0.1%",
          right: left === 0 ? "0.1%" : 0,
          bottom: "0.1%",
          width: left === 0 ? "99.9%" : "100%",
          height: "99.9%",
          position: "absolute",
        }}
      >
        <div
          style={{
            overflow: "hidden",
            left: "-23.7%",
            top: "29.1%",
            right: "53%",
            bottom: "28.5%",
            width: "70.7%",
            height: "42.3%",
            position: "absolute",
            maskImage: `url("${GREEN_EYE_MASK}")`,
            WebkitMaskImage: `url("${GREEN_EYE_MASK}")`,
            maskRepeat: "no-repeat",
            WebkitMaskRepeat: "no-repeat",
            maskType: "luminance",
            maskPosition: "0.8px -1.9px",
            WebkitMaskPosition: "0.8px -1.9px",
          }}
        >
          <svg
            width="2.7219784259796143"
            height="2.4237704277038574"
            viewBox="0 0 2.7219784259796143 2.4237704277038574"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            preserveAspectRatio="none"
            style={{
              transformOrigin: "0 0",
              transform: "rotate(90deg)",
              left: "100%",
              top: 0,
              right: "-112.3%",
              bottom: "11%",
              width: "112.3%",
              height: "89%",
              position: "absolute",
            }}
          >
            <path
              d="M1.4668 0.1885l1.1536 2.0545c0.0454 0.0809-0.013 0.1808-0.1058 0.1808h-2.3072c-0.0928 0-0.1513-0.0999-0.1059-0.1808l1.1536-2.0545c0.0464-0.0826 0.1653-0.0826 0.2117 0z"
              style={{ fillRule: "nonzero", fill: "#fff" }}
            />
          </svg>
        </div>
      </div>
    </div>
  );
}

const RED_EYE_MASK =
  "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNCIgaGVpZ2h0PSI3LjE4NzYwNDQyNzMzNzY0NjUiIHZpZXdCb3g9IjAgMCA0IDcuMTg3NjA0NDI3MzM3NjQ2NSIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgcHJlc2VydmVBc3BlY3RSYXRpbz0ibm9uZSIgc3R5bGU9ImxlZnQ6IDBweDt0b3A6IDBweDtyaWdodDogMHB4O2JvdHRvbTogMHB4O3RyYW5zZm9ybTogbWF0cml4KDEsMCwwLDEsMCwwKTt0cmFuc2Zvcm0tb3JpZ2luOiAwIDA7Ij48ZGVmcz48Y2xpcFBhdGggaWQ9ImRlZl8wIj48cmVjdCB4PSIwIiB5PSIwIiB3aWR0aD0iMy44MzI2OTA5NTQyMDgzNzQiIGhlaWdodD0iNy4xODc2MDQ0MjczMzc2NDY1Ij48L3JlY3Q+PC9jbGlwUGF0aD48L2RlZnM+PGcgaWQ9Im1hc2tfdW5kZWZpbmVkIiBtYXNrVW5pdHM9InVzZXJTcGFjZU9uVXNlIiB4PSIwIiB5PSIwIiB3aWR0aD0iMy44MzI2OTA5NTQyMDgzNzQiIGhlaWdodD0iNy4xODc2MDQ0MjczMzc2NDY1IiBzdHlsZT0ibWFzay10eXBlOiBsdW1pbmFuY2U7Ij48ZyBzdHlsZT0iY2xpcC1wYXRoOiB1cmwoI2RlZl8wKTsiPjxwYXRoIGQ9Ik0xLjkyMDIgMEMyLjk3MzIgMCAzLjgzMjcgMS42MDM2IDMuODMyNyAzLjU5MzggMy44MzI3IDUuNTg0IDIuOTczMiA3LjE4NzYgMS45MjAyIDcuMTg3NiAwLjg1OTUgNy4xODc2IDAgNS41ODQgMCAzLjU5MzggMCAxLjYwMzYgMC44NTk1IDAgMS45MjAyIDBaIiBzdHlsZT0iZmlsbC1ydWxlOiBub256ZXJvO2ZpbGw6ICMwMDA7IiAvPjwvZz48L2c+PC9zdmc+";

function RedAlly({
  left = 568,
  top = 211,
  state = "idle",
  showCursor = true,
}: {
  left?: number | string;
  top?: number;
  state?: AllyAnimationState;
  showCursor?: boolean;
}) {
  return (
    <div
      style={{
        overflow: "hidden",
        left,
        top,
        width: 63,
        height: 60,
        position: "absolute",
      }}
    >
      <div
        className="ally-face"
        style={{
          left: 26,
          top: 24,
          width: 37,
          height: 36,
          position: "absolute",
        }}
      >
        <AllyAvatar shape="ghosty" state={state} color="#fd304f" size={36} />
      </div>
      <div
        className="ally-face"
        style={{
          display: "none",
          borderRadius: 100,
          backgroundColor: "#fd304f",
          left: 26,
          top: 24,
          width: 37,
          height: 36,
          position: "absolute",
        }}
      >
        <div
          style={{
            overflow: "hidden",
            left: "calc(-12.2px + 50%)",
            top: "calc(-13.3px + 50%)",
            width: 24.4,
            height: 26.6,
            position: "absolute",
          }}
        >
          <svg
            width="26.11387430377176"
            height="28.338881373405457"
            viewBox="0 0 26.11387430377176 28.338881373405457"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            preserveAspectRatio="none"
            style={{
              left: "-3.7%",
              top: "-3.4%",
              right: "-3.2%",
              bottom: "-3%",
              width: "106.9%",
              height: "106.4%",
              position: "absolute",
            }}
          >
            <path
              d="M20.6402 19.0927C22.2935 17.3814 24.0366 15.7875 24.3946 11.2073 24.7526 6.6271 20.9158 0 12.4082 0 3.9006 0-0.2129 6.9123 0.0085 11.4422 0.2299 15.9721 1.654 17.4701 3.6939 19.1262 5.5539 20.6362 4.245 23.8281 6.0361 24.4279 7.8272 25.0277 9.0894 21.475 9.5149 21.475 9.9405 21.475 9.8594 26.6425 12.4082 26.6425 14.957 26.6425 14.6739 21.475 15.1255 21.475 15.577 21.475 16.4114 24.7655 18.367 24.3608 20.3225 23.956 18.987 20.804 20.6402 19.0927Z"
              transform=" translate(0.9071275397366982 0.9022064417506335)"
              style={{ fillRule: "nonzero", fill: "#fff" }}
            />
            <path
              d="M20.6402 19.0927C22.2935 17.3814 24.0366 15.7875 24.3946 11.2073 24.7526 6.6271 20.9158 0 12.4082 0 3.9006 0-0.2129 6.9123 0.0085 11.4422 0.2299 15.9721 1.654 17.4701 3.6939 19.1262 5.5539 20.6362 4.245 23.8281 6.0361 24.4279 7.8272 25.0277 9.0894 21.475 9.5149 21.475 9.9405 21.475 9.8594 26.6425 12.4082 26.6425 14.957 26.6425 14.6739 21.475 15.1255 21.475 15.577 21.475 16.4114 24.7655 18.367 24.3608 20.3225 23.956 18.987 20.804 20.6402 19.0927Z"
              transform=" translate(0.9071275397366982 0.9022064417506335)"
              style={{ stroke: "#000", strokeWidth: 1.6963986158370972 }}
            />
          </svg>
          <div
            className="ally-eyes"
            style={{
              overflow: "hidden",
              left: "calc(-8.9px + 50%)",
              top: 6.2,
              width: 10.2,
              height: 7.2,
              position: "absolute",
            }}
          >
            <RedEye left={0} />
            <RedEye left={6.4} />
          </div>
        </div>
      </div>
      {showCursor ? (
        <div
          style={{
            overflow: "hidden",
            left: 0,
            top: 0,
            width: 36,
            height: 36,
            position: "absolute",
          }}
        >
          <CursorMark fill="#fd304f" />
        </div>
      ) : null}
    </div>
  );
}

function RedEye({ left }: { left: number }) {
  return (
    <div
      style={{
        overflow: "hidden",
        left,
        top: 0,
        width: 3.8,
        height: 7.2,
        position: "absolute",
      }}
    >
      <svg
        width="3.8326909542083745"
        height="7.195828914642334"
        viewBox="0 0 3.8326909542083745 7.195828914642334"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
        style={{
          left: "0.1%",
          top: 0,
          right: 0,
          bottom: 0,
          width: "99.9%",
          height: "100%",
          position: "absolute",
        }}
      >
        <path
          d="M1.9163 0C2.9748 0 3.8327 1.611 3.8327 3.5979 3.8327 5.5848 2.9748 7.1958 1.9163 7.1958 0.8579 7.1958 0 5.5848 0 3.5979 0 1.611 0.8579 0 1.9163 0Z"
          style={{ fillRule: "nonzero", fill: "#000" }}
        />
      </svg>
      <div
        style={{
          overflow: "hidden",
          left: 0,
          top: "0.1%",
          right: 0,
          bottom: "0.1%",
          width: "99.9%",
          height: "99.9%",
          position: "absolute",
        }}
      >
        <div
          style={{
            overflow: "hidden",
            left: "-23.7%",
            top: "29.1%",
            right: "53%",
            bottom: "28.5%",
            width: "70.7%",
            height: "42.3%",
            position: "absolute",
            maskImage: `url("${RED_EYE_MASK}")`,
            WebkitMaskImage: `url("${RED_EYE_MASK}")`,
            maskRepeat: "no-repeat",
            WebkitMaskRepeat: "no-repeat",
            maskType: "luminance",
            maskPosition: "0.9px -2.1px",
            WebkitMaskPosition: "0.9px -2.1px",
          }}
        >
          <svg
            width="3.0434062480926514"
            height="2.70999"
            viewBox="0 0 3.0434062480926514 2.70999"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            preserveAspectRatio="none"
            style={{
              transformOrigin: "0 0",
              transform: "rotate(90deg)",
              left: "100%",
              top: 0,
              right: "-112.3%",
              bottom: "11%",
              width: "112.3%",
              height: "89%",
              position: "absolute",
            }}
          >
            <path
              d="M1.64 0.2107l1.2899 2.2971c0.0508 0.0905-0.0146 0.2022-0.1183 0.2022h-2.5797c-0.1037 0-0.1691-0.1117-0.1184-0.2022l1.2899-2.2971c0.0519-0.0924 0.1848-0.0924 0.2367 0z"
              style={{ fillRule: "nonzero", fill: "#fff" }}
            />
          </svg>
        </div>
      </div>
    </div>
  );
}
