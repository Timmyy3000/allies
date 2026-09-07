"use client";

import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import { AllyAvatar } from "../../components/ally-avatar";
import type { ProductionAllyFrameModel } from "./conversation-frame-model";
import styles from "./conversation-frame.module.css";

export function ConversationPresence({
  ally, state, stateReady, docked, muted, placementKey, layoutVersion, shellRef, headerRef, threadRef, onAnimationStateChange,
}: {
  ally: ProductionAllyFrameModel;
  state: "sleeping" | "idle" | "thinking";
  stateReady: boolean;
  docked: boolean;
  muted: boolean;
  placementKey: string;
  layoutVersion: string;
  shellRef: RefObject<HTMLDivElement | null>;
  headerRef: RefObject<HTMLSpanElement | null>;
  threadRef: RefObject<HTMLSpanElement | null>;
  onAnimationStateChange?: (state: string) => void;
}) {
  const actorRef = useRef<HTMLDivElement>(null);
  const last = useRef<{ x: number; y: number; size: number; placement: string } | null>(null);
  const animation = useRef<Animation | null>(null);

  useLayoutEffect(() => {
    if (actorRef.current) actorRef.current.style.visibility = "hidden";
  }, [docked, placementKey]);

  useEffect(() => {
    const actor = actorRef.current;
    const shell = shellRef.current;
    const anchor = docked ? headerRef.current : threadRef.current;
    if (!actor || !shell || !anchor) return;
    const placement = docked ? "header" : "thread";
    const canvas = threadRef.current?.closest('[data-testid="conversation-frame-canvas"]');
    const measure = (animate = false) => {
      const origin = shell.getBoundingClientRect();
      const target = anchor.getBoundingClientRect();
      const x = target.left - origin.left;
      const y = target.top - origin.top;
      const size = target.width || (docked ? 24 : 36);
      const bounds = canvas?.getBoundingClientRect();
      const visible = docked || !bounds || (target.bottom > bounds.top + 60 && target.top < bounds.bottom);
      const previous = last.current;
      actor.style.visibility = visible ? "visible" : "hidden";
      if (previous?.x === x && previous.y === y && previous.size === size && previous.placement === placement) return;
      animation.current?.cancel();
      actor.style.transform = `translate(${x}px, ${y}px) scale(${size / 36})`;
      if (animate && visible && previous && previous.placement !== placement
        && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches && actor.animate) {
        animation.current = actor.animate([
          { transform: `translate(${previous.x}px, ${previous.y}px) scale(${previous.size / 36})` },
          { transform: `translate(${x}px, ${y}px) scale(${size / 36})` },
        ], { duration: 520, easing: "cubic-bezier(0.22, 1, 0.36, 1)" });
      }
      last.current = { x, y, size, placement };
    };
    measure(true);
    const update = () => measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(shell);
    observer?.observe(anchor);
    if (canvas) observer?.observe(canvas);
    if (docked && anchor.nextElementSibling) observer?.observe(anchor.nextElementSibling);
    if (anchor.parentElement) observer?.observe(anchor.parentElement);
    const rail = anchor.closest('[data-testid="conversation-frame-rail"]');
    if (rail) observer?.observe(rail);
    canvas?.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      observer?.disconnect();
      canvas?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [docked, placementKey, layoutVersion, shellRef, headerRef, threadRef]);

  useEffect(() => () => { animation.current?.cancel(); }, []);

  return (
    <div ref={actorRef} className={styles.framePresenceActor} data-testid="conversation-ally" data-state={state} data-location={docked ? "header" : "thread"}>
      <div className={styles.framePresenceColor} data-muted={muted}>
        {ally.supportedAppearance ? (
          <AllyAvatar shape={ally.shape} color={ally.accent} size={36} state={state} stateReady={stateReady}
            label={`${ally.name} avatar`} skipWakeTransition onAnimationStateChange={onAnimationStateChange} />
        ) : <span role="img" aria-label="Ally appearance unavailable" data-testid="ally-appearance-unavailable">?</span>}
      </div>
    </div>
  );
}
