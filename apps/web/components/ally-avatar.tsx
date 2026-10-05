"use client";

import {
  useMemo,
  useState,
  useSyncExternalStore,
  type CSSProperties,
} from "react";

import { AllyArtwork } from "./ally-artwork";

export const ALLY_SHAPES = ["boxy", "ghosty", "rocky", "rolly"] as const;
export type AllyShape = (typeof ALLY_SHAPES)[number];

export const ALLY_ANIMATION_STATES = ["idle", "thinking", "sleeping"] as const;
export type AllyAnimationState = (typeof ALLY_ANIMATION_STATES)[number];

export const ALLY_MOTION_MODES = ["system", "full", "reduced"] as const;
export type AllyMotionMode = (typeof ALLY_MOTION_MODES)[number];

export const DEFAULT_ALLY_COLOR = "#FF5800";
export const ALLY_AVATAR_CYCLE_MS = 4_000;
export const ALLY_ANIMATION_CYCLE_MS: Record<AllyAnimationState, number> = {
  idle: 4_000,
  thinking: 4_502.083,
  sleeping: 9_600,
};

/**
 * Colored Allies use the shared shell as the visual container. Keep the
 * authored 470px animation canvas intact, but give the artwork a consistent
 * margin inside that shell when a color is present.
 */
const COLORED_ARTWORK_SCALE = 0.86;
// Render animated SVG masks and transforms above display size before downsampling on high-DPI surfaces.
const ARTWORK_RENDER_SCALE = 2;

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
    sleeping: { animated: "/ally/sleeping/sleeping_boxy.svg", reduced: "/ally/sleeping/sleeping_boxy.reduced.svg" },
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
    sleeping: { animated: "/ally/sleeping/sleeping_ghosty.svg", reduced: "/ally/sleeping/sleeping_ghosty.reduced.svg" },
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
    sleeping: { animated: "/ally/sleeping/sleeping_rocky.svg", reduced: "/ally/sleeping/sleeping_rocky.reduced.svg" },
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
    sleeping: { animated: "/ally/sleeping/sleeping_rolly.svg", reduced: "/ally/sleeping/sleeping_rolly.reduced.svg" },
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

function normalizeSize(size: number | string | undefined): number | string {
  if (typeof size === "number" && Number.isFinite(size) && size > 0) return size;
  if (typeof size === "string" && size.trim().length > 0) return size;
  return 160;
}

export type AllyAvatarProps = {
  shape: AllyShape;
  state?: AllyAnimationState;
  stateReady?: boolean;
  motion?: AllyMotionMode;
  color?: string;
  size?: number | string;
  frameSize?: { width: number | string; height: number | string };
  /** Scale the artwork inside its fixed shell without changing the shell size. */
  artworkScale?: number;
  /** Render the authored artwork without a coloured shell. */
  transparent?: boolean;
  /** Render an unselected Ally as the neutral Figma artwork. */
  neutral?: boolean;
  /** Use the full authored canvas when a screen owns the artwork scale. */
  artworkSize?: "default" | "full";
  label?: string;
  className?: string;
  onAnimationStateChange?: (state: string) => void;
  skipWakeTransition?: boolean;
};

export function AllyAvatar({
  shape: shapeInput,
  state: stateInput = "idle",
  stateReady = true,
  motion = "system",
  color,
  size,
  frameSize,
  artworkScale,
  transparent = false,
  neutral = false,
  artworkSize = "default",
  label,
  className,
  onAnimationStateChange,
  skipWakeTransition = false,
}: AllyAvatarProps) {
  const shape = normalizeAllyShape(shapeInput);
  const requestedState = normalizeAllyAnimationState(stateInput);
  const reducedMotion = usePrefersReducedMotion(motion);
  const [displayedState, setDisplayedState] = useState<string>(requestedState);
  const shellColor = normalizeAllyColor(color);
  const accessibleLabel = label?.trim() || undefined;
  const artworkLayout = shape ? ARTWORK_LAYOUT[shape] : null;
  const hasShell = !transparent && !neutral;
  const hasColorShell = !neutral && Boolean(color?.trim());
  const rootStyle = useMemo<CSSProperties>(
    () => ({
      width: normalizeSize(frameSize?.width ?? size),
      height: normalizeSize(frameSize?.height ?? size),
      borderRadius: "50%",
      backgroundColor: hasShell ? shellColor : "transparent",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      overflow: "hidden",
      flexShrink: 0,
      position: "relative",
      transition: reducedMotion
        ? "none"
        : "background-color 240ms ease, filter 240ms ease",
    }),
    [frameSize, hasShell, reducedMotion, shellColor, size],
  );

  return (
    <div
      className={className}
      data-ally-avatar
      data-ally-shape={shape ?? "invalid"}
      data-ally-state={displayedState}
      data-ally-motion={reducedMotion ? "reduced" : "full"}
      role={accessibleLabel ? "img" : undefined}
      aria-label={accessibleLabel}
      aria-hidden={accessibleLabel ? undefined : true}
      style={rootStyle}
    >
      {artworkLayout ? (
        <div
          data-ally-artwork
          data-ally-artwork-state={displayedState}
          style={{
            width: hasColorShell || artworkSize === "full" ? "100%" : artworkLayout.width,
            height: hasColorShell || artworkSize === "full" ? "100%" : artworkLayout.height,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            transform: hasColorShell
              ? `scale(${artworkScale ?? COLORED_ARTWORK_SCALE})`
              : undefined,
            transformOrigin: "center",
          }}
        >
          <div
            style={{
              width: "100%",
              height: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              filter: neutral ? "grayscale(1) opacity(0.38)" : undefined,
            }}
          >
            <div
              data-ally-artwork-raster
              data-ally-artwork-raster-scale={ARTWORK_RENDER_SCALE}
              style={{
                width: `${ARTWORK_RENDER_SCALE * 100}%`,
                height: `${ARTWORK_RENDER_SCALE * 100}%`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
                transform: `scale(${1 / ARTWORK_RENDER_SCALE})`,
                transformOrigin: "center",
              }}
            >
              {shape && stateReady && <AllyArtwork key={shape} shape={shape} state={requestedState} reduced={reducedMotion} skipWakeTransition={skipWakeTransition} onStateChange={(state) => { setDisplayedState(state); onAnimationStateChange?.(state); }} />}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
