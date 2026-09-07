"use client";

import { motion, useAnimationFrame, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import { useRef } from "react";

export function ShinyText({
  children,
  color,
  shineColor = "#ffffff",
  speed = 1.7,
  className = "",
}: {
  children: string;
  color: string;
  shineColor?: string;
  speed?: number;
  className?: string;
}) {
  const reducedMotion = useReducedMotion() ?? false;
  const progress = useMotionValue(0);
  const elapsed = useRef(0);
  const previousTime = useRef<number | null>(null);

  useAnimationFrame((time) => {
    if (reducedMotion) return;
    if (previousTime.current === null) {
      previousTime.current = time;
      return;
    }

    elapsed.current += time - previousTime.current;
    previousTime.current = time;
    progress.set((elapsed.current % (speed * 1000)) / (speed * 10));
  });

  const backgroundPosition = useTransform(progress, (value) => `${150 - value * 2}% center`);

  if (reducedMotion) return <span className={className} style={{ color }}>{children}</span>;

  return (
    <motion.span
      className={`shiny-text ${className}`}
      style={{
        color,
        backgroundImage: `linear-gradient(120deg, ${color} 0%, ${color} 35%, ${shineColor} 50%, ${color} 65%, ${color} 100%)`,
        backgroundPosition,
      }}
    >
      {children}
    </motion.span>
  );
}
