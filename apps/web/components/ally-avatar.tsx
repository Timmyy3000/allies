"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
} from "react";

export const ALLY_SHAPES = ["boxy", "ghosty", "rocky", "rolly"] as const;
export type AllyShape = (typeof ALLY_SHAPES)[number];

export const ALLY_ANIMATION_STATES = ["idle", "thinking"] as const;
export type AllyAnimationState = (typeof ALLY_ANIMATION_STATES)[number];

export const ALLY_MOTION_MODES = ["system", "full", "reduced"] as const;
export type AllyMotionMode = (typeof ALLY_MOTION_MODES)[number];

export const DEFAULT_ALLY_COLOR = "#FF5800";
export const ALLY_AVATAR_CYCLE_MS = 4_000;
export const ALLY_ANIMATION_CYCLE_MS: Record<AllyAnimationState, number> = {
  idle: 4_000,
  thinking: 4_502.083,
};

type AssetSource = {
  animated: string;
  reduced: string;
};

type AllyAssetTable = Record<
  AllyShape,
  Record<AllyAnimationState, AssetSource>
>;

const ASSETS: AllyAssetTable = {
  boxy: {
    idle: {
      animated: "/ally/idle/idle_boxy.svg",
      reduced: "/ally/idle/idle_boxy.reduced.svg",
    },
    thinking: {
      animated: "/ally/thinking/thinking_boxy.svg",
      reduced: "/ally/thinking/thinking_boxy.reduced.svg",
    },
  },
  ghosty: {
    idle: {
      animated: "/ally/idle/idle_ghosty.svg",
      reduced: "/ally/idle/idle_ghosty.reduced.svg",
    },
    thinking: {
      animated: "/ally/thinking/thinking_ghosty.svg",
      reduced: "/ally/thinking/thinking_ghosty.reduced.svg",
    },
  },
  rocky: {
    idle: {
      animated: "/ally/idle/idle_rocky.svg",
      reduced: "/ally/idle/idle_rocky.reduced.svg",
    },
    thinking: {
      animated: "/ally/thinking/thinking_rocky.svg",
      reduced: "/ally/thinking/thinking_rocky.reduced.svg",
    },
  },
  rolly: {
    idle: {
      animated: "/ally/idle/idle_rolly.svg",
      reduced: "/ally/idle/idle_rolly.reduced.svg",
    },
    thinking: {
      animated: "/ally/thinking/thinking_rolly.svg",
      reduced: "/ally/thinking/thinking_rolly.reduced.svg",
    },
  },
};

/**
 * The supplied SVG canvases have slightly different intrinsic dimensions.
 * These fixed inner canvases keep the artwork anchored inside the shared
 * circular shell when the animation state changes.
 */
const ARTWORK_LAYOUT: Record<AllyShape, { height: string; width: string }> = {
  boxy: { width: "72%", height: "72%" },
  ghosty: { width: "72%", height: "76%" },
  rocky: { width: "82%", height: "74%" },
  rolly: { width: "76%", height: "76%" },
};

const HEX_COLOR = /^#(?:[\da-f]{3}|[\da-f]{4}|[\da-f]{6}|[\da-f]{8})$/i;

export function normalizeAllyShape(value: unknown): AllyShape | null {
  return typeof value === "string" && (ALLY_SHAPES as readonly string[]).includes(value)
    ? (value as AllyShape)
    : null;
}

export function normalizeAllyAnimationState(
  value: unknown,
): AllyAnimationState {
  return typeof value === "string" &&
    (ALLY_ANIMATION_STATES as readonly string[]).includes(value)
    ? (value as AllyAnimationState)
    : "idle";
}

export function normalizeAllyColor(value: unknown): string {
  if (typeof value !== "string") return DEFAULT_ALLY_COLOR;
  const color = value.trim();
  return HEX_COLOR.test(color) ? color : DEFAULT_ALLY_COLOR;
}

export function getAllyAsset(
  shape: AllyShape,
  state: AllyAnimationState,
  reducedMotion = false,
): string {
  const selected = ASSETS[shape][state] ?? ASSETS[shape].idle;
  return reducedMotion ? selected.reduced : selected.animated;
}

export function getAllyCycleDelay(
  cycleStartedAt: number,
  now: number,
  cycleMs = ALLY_AVATAR_CYCLE_MS,
): number {
  if (!Number.isFinite(cycleStartedAt) || !Number.isFinite(now)) {
    return cycleMs;
  }

  const elapsed = Math.max(0, now - cycleStartedAt);
  const remainder = elapsed % cycleMs;
  return remainder === 0 ? cycleMs : cycleMs - remainder;
}

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
let reducedMotionMedia: MediaQueryList | null = null;
const reducedMotionSubscribers = new Set<() => void>();

function getReducedMotionMedia() {
  if (typeof window === "undefined") return null;
  return (reducedMotionMedia ??= window.matchMedia(REDUCED_MOTION_QUERY));
}

function notifyReducedMotionSubscribers() {
  reducedMotionSubscribers.forEach((subscriber) => subscriber());
}

function subscribeToReducedMotion(subscriber: () => void) {
  const media = getReducedMotionMedia();
  if (!media) return () => undefined;

  reducedMotionSubscribers.add(subscriber);
  if (reducedMotionSubscribers.size === 1) {
    media.addEventListener("change", notifyReducedMotionSubscribers);
  }

  return () => {
    reducedMotionSubscribers.delete(subscriber);
    if (reducedMotionSubscribers.size === 0) {
      media.removeEventListener("change", notifyReducedMotionSubscribers);
    }
  };
}

function getReducedMotionSnapshot() {
  return getReducedMotionMedia()?.matches ?? false;
}

function usePrefersReducedMotion(mode: AllyMotionMode) {
  const systemReducedMotion = useSyncExternalStore(
    subscribeToReducedMotion,
    getReducedMotionSnapshot,
    () => false,
  );

  return mode === "reduced" || (mode === "system" && systemReducedMotion);
}

function useDeferredAnimationState(
  requestedState: AllyAnimationState,
  shape: AllyShape | null,
  reducedMotion: boolean,
) {
  const [activeState, setActiveState] = useState(requestedState);
  const activeStateRef = useRef(activeState);
  const cycleStartedAt = useRef<number | null>(null);
  const deadlineRef = useRef<number | null>(null);

  const clearDeadline = () => {
    if (deadlineRef.current !== null) {
      window.clearTimeout(deadlineRef.current);
      deadlineRef.current = null;
    }
  };

  useEffect(() => {
    cycleStartedAt.current = performance.now();
  }, [shape, reducedMotion]);

  useEffect(() => {
    clearDeadline();

    if (reducedMotion) {
      activeStateRef.current = requestedState;
      cycleStartedAt.current = performance.now();
      return;
    }

    if (requestedState === activeStateRef.current || shape === null) return;

    const startedAt = cycleStartedAt.current ?? performance.now();
    const delay = getAllyCycleDelay(
      startedAt,
      performance.now(),
      ALLY_ANIMATION_CYCLE_MS[activeStateRef.current],
    );
    deadlineRef.current = window.setTimeout(() => {
      activeStateRef.current = requestedState;
      setActiveState(requestedState);
      cycleStartedAt.current = performance.now();
      deadlineRef.current = null;
    }, delay);

    return clearDeadline;
  }, [requestedState, shape, reducedMotion]);

  useEffect(() => {
    if (reducedMotion) return;
    const frame = window.requestAnimationFrame(() => {
      setActiveState(activeStateRef.current);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [reducedMotion]);

  useEffect(() => clearDeadline, []);

  return reducedMotion ? requestedState : activeState;
}

function normalizeSize(size: number | string | undefined): number | string {
  if (typeof size === "number" && Number.isFinite(size) && size > 0) return size;
  if (typeof size === "string" && size.trim().length > 0) return size;
  return 160;
}

export type AllyAvatarProps = {
  shape: AllyShape;
  state?: AllyAnimationState;
  motion?: AllyMotionMode;
  color?: string;
  size?: number | string;
  label?: string;
  className?: string;
};

export function AllyAvatar({
  shape: shapeInput,
  state: stateInput = "idle",
  motion = "system",
  color,
  size,
  label,
  className,
}: AllyAvatarProps) {
  const shape = normalizeAllyShape(shapeInput);
  const requestedState = normalizeAllyAnimationState(stateInput);
  const reducedMotion = usePrefersReducedMotion(motion);
  const activeState = useDeferredAnimationState(
    requestedState,
    shape,
    reducedMotion,
  );
  const [assetFallback, setAssetFallback] = useState<{
    key: string;
    state: AllyAnimationState;
  } | null>(null);

  useEffect(() => {
    if (shape === null) return;

    const sources = ALLY_ANIMATION_STATES.map((state) =>
      getAllyAsset(shape, state, reducedMotion),
    );
    const preloads = sources.map((source) => {
      const image = new window.Image();
      image.src = source;
      return image;
    });

    return () => {
      preloads.forEach((image) => {
        image.onload = null;
        image.onerror = null;
      });
    };
  }, [shape, reducedMotion]);

  const shellColor = normalizeAllyColor(color);
  const accessibleLabel = label?.trim() || undefined;
  const assetKey = `${shape ?? "invalid"}:${activeState}:${reducedMotion ? "reduced" : "full"}`;
  const renderedState =
    assetFallback?.key === assetKey ? assetFallback.state : activeState;
  const assetSource = shape
    ? getAllyAsset(shape, renderedState, reducedMotion)
    : null;
  const artworkLayout = shape ? ARTWORK_LAYOUT[shape] : null;
  const rootStyle = useMemo<CSSProperties>(
    () => ({
      width: normalizeSize(size),
      height: normalizeSize(size),
      borderRadius: "50%",
      backgroundColor: shellColor,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      overflow: "hidden",
      flexShrink: 0,
      position: "relative",
      transition: reducedMotion ? "none" : "background-color 240ms ease",
    }),
    [reducedMotion, shellColor, size],
  );

  return (
    <div
      className={className}
      data-ally-avatar
      data-ally-shape={shape ?? "invalid"}
      data-ally-state={activeState}
      data-ally-motion={reducedMotion ? "reduced" : "full"}
      role={accessibleLabel ? "img" : undefined}
      aria-label={accessibleLabel}
      aria-hidden={accessibleLabel ? undefined : true}
      style={rootStyle}
    >
      {assetSource && artworkLayout ? (
        <div
          data-ally-artwork
          data-ally-artwork-state={renderedState}
          style={{
            width: artworkLayout.width,
            height: artworkLayout.height,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          {/* External SVGs keep their authored CSS/SMIL animation only when rendered as an image document. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={assetSource}
            alt=""
            aria-hidden="true"
            draggable={false}
            onError={() => {
              if (renderedState !== "idle") {
                setAssetFallback({ key: assetKey, state: "idle" });
              }
            }}
            style={{
              width: "100%",
              height: "100%",
              display: "block",
              objectFit: "contain",
              userSelect: "none",
              pointerEvents: "none",
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
