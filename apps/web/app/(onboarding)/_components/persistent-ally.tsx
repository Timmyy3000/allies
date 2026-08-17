"use client";

import { motion, type Transition } from "motion/react";

import {
  AllyAvatar,
  type AllyAnimationState,
  type AllyAvatarProps,
  type AllyMotionMode,
  type AllyShape,
} from "@/components/ally-avatar";

const LAYOUT_TRANSITION: Transition = {
  type: "spring",
  stiffness: 190,
  damping: 24,
  mass: 0.82,
};

export const ONBOARDING_ALLY_LAYOUT_ID = "onboarding-ally";

export function PersistentAllyAvatar({
  shape,
  color,
  neutral = false,
  size,
  artworkSize = "default",
  frameSize,
  layoutId = ONBOARDING_ALLY_LAYOUT_ID,
  sharedLayout = true,
  layoutMode = "position",
  pulse = false,
  motionMode = "system",
  state,
  label,
}: {
  shape: AllyShape;
  color?: string;
  neutral?: boolean;
  size: number | string;
  artworkSize?: "default" | "full";
  frameSize?: AllyAvatarProps["frameSize"];
  layoutId?: string;
  sharedLayout?: boolean;
  layoutMode?: "position" | "full";
  pulse?: boolean;
  motionMode?: AllyMotionMode;
  state?: AllyAnimationState;
  label?: string;
}) {
  return (
    <motion.div
      layoutId={sharedLayout ? layoutId : undefined}
      layout={layoutMode === "full" ? true : "position"}
      initial={false}
      animate={{ scale: pulse ? [1, 1.025, 1] : 1 }}
      transition={{
        layout: LAYOUT_TRANSITION,
        scale: pulse
          ? { duration: 2.8, ease: "easeInOut", repeat: Infinity }
          : { duration: 0.24, ease: "easeOut" },
      }}
      style={{
        width: frameSize?.width ?? size,
        height: frameSize?.height ?? size,
        aspectRatio: frameSize ? undefined : 1,
        display: "flex",
        flexShrink: 0,
        transition: sharedLayout
          ? undefined
          : "width 240ms ease, height 240ms ease",
        willChange: pulse ? "transform" : undefined,
      }}
      data-testid="persistent-ally"
    >
      <AllyAvatar
        shape={shape}
        color={color}
        neutral={neutral}
        state={state}
        motion={motionMode}
        size="100%"
        artworkSize={artworkSize}
        frameSize={frameSize}
        label={label}
      />
    </motion.div>
  );
}
