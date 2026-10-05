"use client";

import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";

import { AllyAvatar, type AllyShape } from "./ally-avatar";

const AVATAR_SIZE = 160;
const AVATAR_FRAME_WIDTH = 164.24;
const CAROUSEL_SHAPES = ["ghosty", "rolly", "boxy", "rocky"] as const satisfies readonly AllyShape[];

function modulo(value: number, divisor: number) {
  return ((value % divisor) + divisor) % divisor;
}

export function AllyLookPicker({
  shape,
  color,
  colors,
  dotColor,
  onShapeChange,
  onColorChange,
  swatchSize = 48,
  className = "",
}: {
  shape: AllyShape;
  color: string | null;
  colors: readonly string[];
  dotColor: string;
  onShapeChange: (shape: AllyShape) => void;
  onColorChange: (color: string) => void;
  swatchSize?: number;
  className?: string;
}) {
  const prefersReducedMotion = useReducedMotion() ?? false;
  const shapeCount = CAROUSEL_SHAPES.length;
  const shapeIndex = CAROUSEL_SHAPES.findIndex((candidate) => candidate === shape);
  const [carouselIndex, setCarouselIndex] = useState(shapeCount + Math.max(0, shapeIndex));
  const [isRebasing, setIsRebasing] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const setCarouselPage = (nextIndex: number) => {
    const nextShape = CAROUSEL_SHAPES[modulo(nextIndex, shapeCount)];
    if (!nextShape) return;
    setIsDragging(true);
    setCarouselIndex(nextIndex);
    onShapeChange(nextShape);
  };

  const swipeTo = (nextShapeIndex: number) => {
    if (nextShapeIndex === shapeIndex) return;
    let delta = nextShapeIndex - shapeIndex;
    if (delta > shapeCount / 2) delta -= shapeCount;
    if (delta < -shapeCount / 2) delta += shapeCount;
    setCarouselPage(carouselIndex + delta);
  };

  const handleDragEnd = (
    _event: MouseEvent | TouchEvent | PointerEvent,
    info: { offset: { x: number }; velocity: { x: number } },
  ) => {
    const intent = Math.abs(info.velocity.x) > 200 ? info.velocity.x : info.offset.x;
    if (Math.abs(intent) < 36 && Math.abs(info.velocity.x) < 400) {
      setIsDragging(false);
      return;
    }
    setCarouselPage(carouselIndex + (intent < 0 ? 1 : -1));
  };

  const handleAnimationComplete = () => {
    if (carouselIndex < shapeCount || carouselIndex >= shapeCount * 2) {
      setIsRebasing(true);
      setCarouselIndex(shapeCount + modulo(carouselIndex, shapeCount));
      return;
    }
    if (isRebasing) setIsRebasing(false);
    setIsDragging(false);
  };

  const carouselShapes = Array.from({ length: shapeCount * 3 }, (_, index) => CAROUSEL_SHAPES[index % shapeCount]);
  const slideWidth = `${100 / carouselShapes.length}%`;
  const trackX = `${-carouselIndex * (100 / carouselShapes.length)}%`;
  const trackTransition = prefersReducedMotion || isRebasing
    ? { duration: 0 }
    : { type: "spring" as const, bounce: 0.15, duration: 0.4 };

  return (
    <div
      data-testid="avatar-carousel"
      role="group"
      aria-label="Swipe to choose an Ally shape"
      className={`step-stage onboarding-look-stage ${className}`}
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
          style={{ width: `${carouselShapes.length * 100}%` }}
        >
          {carouselShapes.map((avatarShape, index) => (
            <div
              key={`${avatarShape}-${index}`}
              style={{
                width: slideWidth,
                height: AVATAR_SIZE,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
                opacity: index === carouselIndex || (isDragging && Math.abs(index - carouselIndex) <= 1) ? 1 : 0,
                transition: prefersReducedMotion ? "none" : "opacity 120ms ease",
              }}
            >
              <AllyAvatar
                shape={avatarShape}
                motion="reduced"
                color={color ?? undefined}
                transparent
                artworkSize="full"
                size={AVATAR_SIZE}
                frameSize={{ width: AVATAR_FRAME_WIDTH, height: AVATAR_SIZE }}
              />
            </div>
          ))}
        </motion.div>
      </div>
      <div className="onboarding-look-dots">
        {CAROUSEL_SHAPES.map((dotShape, index) => (
          <button
            key={dotShape}
            type="button"
            data-testid={`avatar-dot-${index}`}
            aria-label={`Avatar ${index + 1}`}
            aria-pressed={index === shapeIndex}
            onClick={() => swipeTo(index)}
            className="onboarding-pop"
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              backgroundColor: index === shapeIndex ? dotColor : "#f0f0f0",
              border: 0,
              padding: 0,
              cursor: "pointer",
            }}
          />
        ))}
      </div>
      <div data-testid="color-row" className="remove-scrollbar onboarding-horizontal-scroll onboarding-look-colors">
        {colors.map((swatch) => {
          const selected = color?.toLowerCase() === swatch.toLowerCase();
          return (
            <button
              key={swatch}
              type="button"
              data-testid={`color-${swatch}`}
              aria-label={`Select ${swatch}`}
              aria-pressed={selected}
              onClick={() => onColorChange(swatch)}
              className="onboarding-swatch"
              data-selected={selected ? "true" : "false"}
              style={{
                width: swatchSize,
                height: swatchSize,
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
                <svg width="20" height="16" viewBox="0 0 20 16" fill="none" aria-hidden="true">
                  <path d="M1.76 8.72L7.06 14.39 18.75 1.86" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
