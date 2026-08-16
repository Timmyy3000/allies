"use client";

import { motion, useReducedMotion } from "motion/react";
import { useState, useSyncExternalStore } from "react";
import { Artboard } from "@/components/artboard";
import { AllyAvatar } from "@/components/ally-avatar";
import { BackButton } from "@/components/back-button";
import {
  DEFAULT_ACCENT,
  NextButton,
  ONBOARDING_CTA,
  ONBOARDING_LAYOUT,
} from "@/components/next-button";
import { ProgressRing } from "@/components/progress-ring";
import {
  ALLY_COLORS,
  useOnboardingStore,
} from "../_store/onboarding-store";
import { PersistentAllyAvatar } from "./persistent-ally";
import { StepHeading } from "./step-heading";

const AVATAR_SHELL_SIZE = 164.2;
const AVATAR_FRAME_HEIGHT = AVATAR_SHELL_SIZE;
const FALLBACK_VIEWPORT_WIDTH = 375;
const CAROUSEL_SHAPES = ["rolly", "ghosty", "boxy", "rocky"] as const;
const COLOR_PICKER_GAP = 28;

function modulo(value: number, divisor: number) {
  return ((value % divisor) + divisor) % divisor;
}

function subscribeToViewport(callback: () => void) {
  if (typeof window === "undefined") return () => undefined;

  window.addEventListener("resize", callback);
  return () => window.removeEventListener("resize", callback);
}

function getViewportWidth() {
  return typeof window === "undefined" ? FALLBACK_VIEWPORT_WIDTH : window.innerWidth;
}

function useViewportWidth() {
  return useSyncExternalStore(
    subscribeToViewport,
    getViewportWidth,
    () => FALLBACK_VIEWPORT_WIDTH,
  );
}

function PaintIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 21.33 21.3" fill="none" aria-hidden>
      <path
        d="M21.3334 10.6667C21.3334 4.7155 16.4583-0.0985 10.4836 0.0015 4.93 0.0944 0.2409 4.6605 0.0095 10.2118-0.2301 15.9607 4.0842 20.7551 9.643 21.2849 10.6107 21.3777 11.4867 20.9098 12.0283 20.2327 12.7351 19.3491 12.8459 18.1285 12.3092 17.1325L11.9929 16.5447C11.6982 15.9975 12.0947 15.3334 12.716 15.3334H16.6667C19.244 15.3334 21.3334 13.2445 21.3334 10.6667Z"
        fill="rgba(253,48,79,0.4)"
      />
      <path
        d="M16.3234 7.3668C15.6725 8.0175 14.6173 8.0175 13.9663 7.3668 13.3154 6.7157 13.3154 5.6608 13.9663 5.0097 14.6173 4.3587 15.6725 4.3587 16.3234 5.0097 16.9743 5.6608 16.9743 6.7157 16.3234 7.3668Z"
        fill="#fd304f"
      />
      <path
        d="M2.6666 10.6666C2.6666 11.5872 3.4128 12.3333 4.3333 12.3333 5.2538 12.3333 6 11.5872 6 10.6666 6 9.7461 5.2538 9 4.3333 9 3.4128 9 2.6666 9.7461 2.6666 10.6666Z"
        fill="#fd304f"
      />
      <path
        d="M5.0096 7.3668C5.6606 8.0175 6.7158 8.0175 7.3667 7.3668 8.0176 6.7157 8.0176 5.6608 7.3667 5.0097 6.7158 4.3587 5.6606 4.3587 5.0096 5.0097 4.3587 5.6608 4.3587 6.7157 5.0096 7.3668Z"
        fill="#fd304f"
      />
      <path
        d="M9 4.3333C9 5.2538 9.7461 6 10.6666 6 11.5872 6 12.3333 5.2538 12.3333 4.3333 12.3333 3.4128 11.5872 2.6666 10.6666 2.6666 9.7461 2.6666 9 3.4128 9 4.3333Z"
        fill="#fd304f"
      />
    </svg>
  );
}

export function LookLikeScreen() {
  const shape = useOnboardingStore((state) => state.shape);
  const hasSwipedAvatar = useOnboardingStore((state) => state.hasSwipedAvatar);
  const color = useOnboardingStore((state) => state.color);
  const setShape = useOnboardingStore((state) => state.setShape);
  const markSwiped = useOnboardingStore((state) => state.markSwiped);
  const setColor = useOnboardingStore((state) => state.setColor);
  const goTo = useOnboardingStore((state) => state.goTo);
  const back = useOnboardingStore((state) => state.back);
  const prefersReducedMotion = useReducedMotion() ?? false;
  const viewportWidth = useViewportWidth();
  const accent = color ?? DEFAULT_ACCENT;

  const shapeIndex = CAROUSEL_SHAPES.findIndex((candidate) => candidate === shape);
  const shapeCount = CAROUSEL_SHAPES.length;
  const [carouselIndex, setCarouselIndex] = useState(
    shapeCount + Math.max(0, shapeIndex),
  );
  const [isRebasing, setIsRebasing] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const setCarouselPage = (nextIndex: number) => {
    const nextShapeIndex = modulo(nextIndex, shapeCount);
    const nextShape = CAROUSEL_SHAPES[nextShapeIndex];
    if (!nextShape) return;

    setIsDragging(true);
    setCarouselIndex(nextIndex);
    setShape(nextShape);
    markSwiped();
  };

  const swipeTo = (nextShapeIndex: number) => {
    if (nextShapeIndex === shapeIndex) return;

    let delta = nextShapeIndex - shapeIndex;
    if (delta > shapeCount / 2) delta -= shapeCount;
    if (delta < -shapeCount / 2) delta += shapeCount;
    setCarouselPage(carouselIndex + delta);
  };

  const swipeBy = (direction: -1 | 1) => {
    setCarouselPage(carouselIndex + direction);
  };

  const handleDragEnd = (
    _event: MouseEvent | TouchEvent | PointerEvent,
    info: { offset: { x: number }; velocity: { x: number } },
  ) => {
    const intent = info.offset.x || info.velocity.x;
    if (Math.abs(intent) < 36 && Math.abs(info.velocity.x) < 400) {
      setIsDragging(false);
      return;
    }

    swipeBy(intent < 0 ? 1 : -1);
  };

  const handleAnimationComplete = () => {
    const isOutsideMiddleCopy = carouselIndex < shapeCount || carouselIndex >= shapeCount * 2;
    if (isOutsideMiddleCopy) {
      setIsRebasing(true);
      setCarouselIndex(shapeCount + modulo(carouselIndex, shapeCount));
      return;
    }

    if (isRebasing) setIsRebasing(false);
    setIsDragging(false);
  };

  const carouselShapes = Array.from({ length: shapeCount * 3 }, (_, index) => {
    return CAROUSEL_SHAPES[index % shapeCount];
  });

  const trackX = -viewportWidth / 2 - carouselIndex * viewportWidth;
  const trackTransition = prefersReducedMotion || isRebasing
    ? { duration: 0 }
    : { type: "spring" as const, stiffness: 280, damping: 32, mass: 0.72 };

  const renderAvatar = (
    avatarShape: (typeof CAROUSEL_SHAPES)[number],
    index: number,
  ) => {
    const isNearActive = Math.abs(index - carouselIndex) <= 1;
    return (
      <div
        key={`${avatarShape}-${index}`}
        style={{
          width: viewportWidth,
          height: AVATAR_FRAME_HEIGHT,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          opacity: index === carouselIndex || (isDragging && isNearActive) ? 1 : 0,
          transition: prefersReducedMotion ? "none" : "opacity 120ms ease",
        }}
      >
        <AllyAvatar
          shape={avatarShape}
          motion="reduced"
          transparent
          size={160}
        />
      </div>
    );
  };

  return (
    <Artboard>
      <div data-testid="look-like" style={{ position: "absolute", inset: 0 }}>
        <BackButton onClick={back} />
        <ProgressRing progress={0.45} color={accent} />
        <StepHeading
          lineHeight="28px"
          mark={
            <PersistentAllyAvatar
              shape={shape}
              color={color ?? undefined}
              neutral={!color}
              size={40}
            />
          }
        >
          What should I
          <br />
          look like?
        </StepHeading>
        <div
          data-testid="avatar-carousel"
          role="group"
          aria-label="Swipe to choose an Ally shape"
          className="step-stage"
          style={{
            left: 0,
            right: 0,
            top: `calc(-${AVATAR_FRAME_HEIGHT / 2}px + 50%)`,
            height: AVATAR_FRAME_HEIGHT,
            position: "absolute",
            overflow: "hidden",
            touchAction: "pan-y",
            cursor: "grab",
            userSelect: "none",
          }}
        >
          <div
            data-testid="avatar-color-shell"
            aria-hidden="true"
            style={{
              position: "absolute",
              left: "50%",
              top: 0,
              width: AVATAR_SHELL_SIZE,
              height: AVATAR_SHELL_SIZE,
              marginLeft: -AVATAR_SHELL_SIZE / 2,
              borderRadius: "50%",
              backgroundColor: color ?? "transparent",
              transition: prefersReducedMotion
                ? "none"
                : "background-color 240ms ease",
              pointerEvents: "none",
              zIndex: 0,
            }}
          />
          <motion.div
            drag="x"
            dragMomentum={false}
            dragElastic={0.12}
            onDragStart={() => setIsDragging(true)}
            onDragEnd={handleDragEnd}
            onAnimationComplete={handleAnimationComplete}
            animate={{ x: trackX }}
            initial={false}
            transition={trackTransition}
            style={{
              position: "absolute",
              left: "50%",
              top: 0,
              display: "flex",
              width: "max-content",
              height: AVATAR_FRAME_HEIGHT,
              x: trackX,
              zIndex: 1,
            }}
          >
            {carouselShapes.map(renderAvatar)}
          </motion.div>
        </div>
        <div
          style={{
            left: "50%",
            marginLeft: -24.5,
            top: "calc(50% + 100px)",
            width: "min-content",
            position: "absolute",
            display: "flex",
            flexDirection: "row",
            columnGap: 6,
            alignItems: "center",
          }}
        >
          {CAROUSEL_SHAPES.map((_, index) => (
            <button
              key={index}
              type="button"
              data-testid={`avatar-dot-${index}`}
              aria-label={`Avatar ${index + 1}`}
              onClick={() => swipeTo(index)}
              className="onboarding-pop"
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: index === shapeIndex ? accent : "#f0f0f0",
                border: 0,
                padding: 0,
                cursor: "pointer",
              }}
            />
          ))}
        </div>
        {!hasSwipedAvatar ? (
          <div
            data-testid="swipe-hint"
            style={{
              left: 0,
              right: 0,
              top: 646,
              position: "absolute",
              display: "flex",
              flexDirection: "row",
              columnGap: 6,
              alignItems: "center",
              justifyContent: "center",
              margin: 0,
              fontSize: 18,
              fontWeight: 600,
              letterSpacing: -0.48,
              lineHeight: "24px",
              color: "#121212",
            }}
          >
            <PaintIcon />
            Swipe then pick a colour
          </div>
        ) : (
          <div
            data-testid="color-row"
            className="remove-scrollbar"
            style={{
              left: 0,
              right: 0,
              bottom: `calc(${ONBOARDING_LAYOUT.bottomPadding} + ${
                ONBOARDING_CTA.height + COLOR_PICKER_GAP
              }px)`,
              width: "auto",
              position: "absolute",
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              columnGap: 18,
              overflowX: "auto",
              paddingLeft: 20,
              paddingRight: 20,
            }}
          >
            {ALLY_COLORS.map((swatch) => {
              const selected = color === swatch;
              return (
                <button
                  key={swatch}
                  type="button"
                  data-testid={`color-${swatch}`}
                  aria-label={`Select ${swatch}`}
                  onClick={() => setColor(swatch)}
                  className="onboarding-swatch"
                  data-selected={selected ? "true" : "false"}
                  style={{
                    width: 48,
                    height: 48,
                    borderRadius: "50%",
                    backgroundColor: swatch,
                    border: 0,
                    flexShrink: 0,
                    cursor: "pointer",
                    padding: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {selected ? (
                    <svg width="20" height="16" viewBox="0 0 20 16" fill="none">
                      <path
                        d="M1.76 8.72L7.06 14.39 18.75 1.86"
                        stroke="#fff"
                        strokeWidth="3"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  ) : null}
                </button>
              );
            })}
          </div>
        )}
       <NextButton
         label="Next"
         active={hasSwipedAvatar && Boolean(color)}
         color={color ?? DEFAULT_ACCENT}
          onClick={() => goTo("job")}
        />
      </div>
    </Artboard>
  );
}
