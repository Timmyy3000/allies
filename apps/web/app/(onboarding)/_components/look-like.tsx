"use client";

import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import { AllyAvatar } from "@/components/ally-avatar";
import { DEFAULT_ACCENT } from "@/components/next-button";
import {
  ALLY_COLORS,
  useOnboardingStore,
} from "../_store/onboarding-store";
import { OnboardingLayout } from "./onboarding-layout";
import { PersistentAllyAvatar } from "./persistent-ally";
import { StepHeading } from "./step-heading";

const AVATAR_NEUTRAL_SIZE = 160;
const AVATAR_BACKGROUND_WIDTH = 164.24;
const AVATAR_FRAME_HEIGHT = 160;
const AVATAR_FRAME_WIDTH = AVATAR_BACKGROUND_WIDTH;
const AVATAR_COLORED_SIZE = 160;
const PREVIEW_SIZE = 40;
const PREVIEW_FRAME_WIDTH = 41.06;
const CAROUSEL_SHAPES = ["ghosty", "rolly", "boxy", "rocky"] as const;

function modulo(value: number, divisor: number) {
  return ((value % divisor) + divisor) % divisor;
}

export function LookLikeScreen() {
  const shape = useOnboardingStore((state) => state.shape);
  const color = useOnboardingStore((state) => state.color);
  const setShape = useOnboardingStore((state) => state.setShape);
  const markSwiped = useOnboardingStore((state) => state.markSwiped);
  const setColor = useOnboardingStore((state) => state.setColor);
  const goTo = useOnboardingStore((state) => state.goTo);
  const back = useOnboardingStore((state) => state.back);
  const prefersReducedMotion = useReducedMotion() ?? false;
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

  const carouselSlideWidth = `${100 / carouselShapes.length}%`;
  const trackX = `${-carouselIndex * (100 / carouselShapes.length)}%`;
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
          width: carouselSlideWidth,
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
          color={color ?? undefined}
          transparent
          artworkSize="full"
          size={color ? AVATAR_COLORED_SIZE : AVATAR_NEUTRAL_SIZE}
          frameSize={{ width: AVATAR_FRAME_WIDTH, height: AVATAR_FRAME_HEIGHT }}
        />
      </div>
    );
  };

  return (
    <OnboardingLayout
      testId="look-like"
      progress={0.45}
      color={accent}
      onBack={back}
      nextActive={Boolean(color)}
      nextColor={color ?? DEFAULT_ACCENT}
      onNext={() => goTo("job")}
    >
      <StepHeading
        lineHeight="28px"
        mark={
          <div className="onboarding-look-preview">
            <PersistentAllyAvatar
              shape={shape}
              color={color ?? undefined}
              neutral={!color}
              size={PREVIEW_SIZE}
              artworkSize="full"
              frameSize={{ width: PREVIEW_FRAME_WIDTH, height: PREVIEW_SIZE }}
              sharedLayout={false}
              layoutMode="position"
            />
          </div>
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
        className="step-stage onboarding-look-stage"
      >
        <div className="onboarding-look-avatar-window">
          <div
            data-testid="avatar-color-shell"
            aria-hidden="true"
            className="onboarding-look-avatar-shell"
            style={{ backgroundColor: color ?? "transparent" }}
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
            className="onboarding-look-track"
            style={{
              x: trackX,
              width: `${carouselShapes.length * 100}%`,
            }}
          >
            {carouselShapes.map(renderAvatar)}
          </motion.div>
        </div>
        <div className="onboarding-look-dots">
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
        <div
          data-testid="color-row"
          className="remove-scrollbar onboarding-horizontal-scroll onboarding-look-colors"
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
      </div>
    </OnboardingLayout>
  );
}
