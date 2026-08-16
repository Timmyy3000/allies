"use client";

import { motion, type Transition } from "motion/react";

import {
  AllyAvatar,
  type AllyAnimationState,
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
  layoutId = ONBOARDING_ALLY_LAYOUT_ID,
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
  layoutId?: string;
  layoutMode?: "position" | "full";
  pulse?: boolean;
  motionMode?: AllyMotionMode;
  state?: AllyAnimationState;
  label?: string;
}) {
  return (
    <motion.div
      layoutId={layoutId}
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
        width: size,
        height: size,
        display: "flex",
        flexShrink: 0,
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
        label={label}
      />
    </motion.div>
  );
}
