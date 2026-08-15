"use client";

import { useRef, type PointerEvent } from "react";
import { Artboard } from "@/components/artboard";
import { AllyAvatar } from "@/components/ally-avatar";
import { BackButton } from "@/components/back-button";
import { DEFAULT_ACCENT, NextButton } from "@/components/next-button";
import { ProgressRing } from "@/components/progress-ring";
import {
  ALLY_COLORS,
  ALLY_SHAPES,
  useOnboardingStore,
} from "../_store/onboarding-store";
import { StepHeading } from "./step-heading";

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
  const startX = useRef<number | null>(null);

  const shapeIndex = ALLY_SHAPES.indexOf(shape);

  const swipeTo = (next: number) => {
    if (next === shapeIndex) return;
    const nextShape = ALLY_SHAPES[next];
    if (!nextShape) return;
    setShape(nextShape);
    markSwiped();
  };

  const onPointerDown = (event: PointerEvent) => {
    startX.current = event.clientX;
  };

  const onPointerUp = (event: PointerEvent) => {
    if (startX.current == null) return;
    const delta = event.clientX - startX.current;
    startX.current = null;
    if (Math.abs(delta) < 24) return;
    if (delta < 0) swipeTo(Math.min(ALLY_SHAPES.length - 1, shapeIndex + 1));
    else swipeTo(Math.max(0, shapeIndex - 1));
  };

  return (
    <Artboard>
      <div data-testid="look-like" style={{ position: "absolute", inset: 0 }}>
        <BackButton onClick={back} />
        <ProgressRing progress={0.45} />
        <StepHeading
          mark={
            <AllyAvatar
              shape={shape}
              color={color ?? "#a0a0a0"}
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
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
          className="step-stage"
          style={{
            left: "calc(-82.5px + 50%)",
            top: "calc(-80px + 50%)",
            width: 164.2,
            height: 160,
            position: "absolute",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            touchAction: "pan-y",
            cursor: "grab",
          }}
        >
          <AllyAvatar shape={shape} color={color ?? undefined} size={160} />
        </div>
        <div
          style={{
            left: "calc(-24.5px + 50%)",
            top: 522,
            width: "min-content",
            position: "absolute",
            display: "flex",
            flexDirection: "row",
            columnGap: 6,
            alignItems: "center",
          }}
        >
          {ALLY_SHAPES.map((_, index) => (
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
                backgroundColor: index === shapeIndex ? DEFAULT_ACCENT : "#f0f0f0",
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
              bottom: 90,
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
              bottom: 90,
              width: 375,
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
