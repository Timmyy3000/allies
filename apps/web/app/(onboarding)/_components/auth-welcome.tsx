"use client";

import { motion, useReducedMotion } from "motion/react";

import { Artboard } from "@/components/artboard";
import { type AllyShape } from "@/components/ally-avatar";
import {
  AUTH_SIGNUP_ALLY_LAYOUT_ID,
  PersistentAllyAvatar,
} from "./persistent-ally";

export function AuthWelcome({
  name,
  shape,
  color,
}: {
  name: string;
  shape: AllyShape;
  color: string;
}) {
  const prefersReducedMotion = useReducedMotion() ?? false;
  const greetingName = name.trim() || "there";

  return (
    <Artboard>
      <div
        data-testid="welcome-allies-1"
        className="onboarding-page waitlist-auth-welcome"
      >
        <div className="waitlist-auth-welcome-stack">
          <PersistentAllyAvatar
            shape={shape}
            color={color}
            state="idle"
            size={61.6}
            frameSize={{ width: 61.6, height: 60 }}
            layoutId={AUTH_SIGNUP_ALLY_LAYOUT_ID}
            layoutMode="full"
            pulse={!prefersReducedMotion}
            motionMode="system"
            label={`${greetingName} Ally`}
          />
          <motion.div
            className="waitlist-auth-welcome-copy"
            initial={prefersReducedMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.32, delay: 0.16, ease: [0.22, 1, 0.36, 1] }}
          >
            <h1>Looking good, {greetingName}</h1>
            <p>We’re done with the basics, one more thing</p>
          </motion.div>
        </div>
      </div>
    </Artboard>
  );
}
