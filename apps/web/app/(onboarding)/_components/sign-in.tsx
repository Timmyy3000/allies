"use client";

import { NextButton } from "@/components/next-button";
import { Artboard } from "@/components/artboard";
import { MiniAlly } from "./mini-ally";
import { useOnboardingStore } from "../_store/onboarding-store";

export function SignInScreen() {
  const goTo = useOnboardingStore((state) => state.goTo);

  return (
    <Artboard>
      <div data-testid="sign-in-page" style={{ position: "absolute", inset: 0 }}>
        <div
          className="step-stage"
          style={{
            borderRadius: 24,
            backgroundColor: "#ff5800",
            left: "calc(-49.5px + 50%)",
            top: "calc(-48px + 50%)",
            width: 98.5,
            height: 96,
            position: "absolute",
            overflow: "hidden",
          }}
        >
          <svg
            viewBox="0 0 63 68"
            fill="none"
            style={{
              left: "8%",
              top: "10%",
              width: "84%",
              height: "80%",
              position: "absolute",
            }}
          >
            <path
              d="M49.5816 45.864C53.5531 41.7531 57.7402 37.9244 58.6002 26.9219 59.4601 15.9194 50.2435 0 29.8067 0 9.3699 0-0.5115 16.6045 0.0204 27.4861 0.5523 38.3678 3.9733 41.9664 8.8735 45.9446 13.3414 49.5718 10.1974 57.2393 14.4998 58.6801 18.8023 60.1209 21.8343 51.5869 22.8566 51.5869 23.8788 51.5869 23.6839 64 29.8067 64 35.9294 64 35.2493 51.5869 36.3341 51.5869 37.4188 51.5869 39.4232 59.4912 44.1207 58.5189 48.8183 57.5465 45.61 49.9748 49.5816 45.864Z"
              transform="translate(2.18 2.17)"
              fill="#fff"
              stroke="#000"
              strokeWidth="4.08"
            />
            <ellipse cx="26" cy="28" rx="4.6" ry="8.6" fill="#000" />
            <ellipse cx="38" cy="28" rx="4.6" ry="8.6" fill="#000" />
          </svg>
        </div>
        <MiniAlly left={255} top={132} fill="#0d92fd" />
        <MiniAlly left={71} top={231} fill="#3446e9" />
        <MiniAlly
          left={109}
          top="calc(69px + 50%)"
          fill="#fbe65f"
          faceLeft={0}
          flipCursor
        />
        <MiniAlly left={324} top={447} fill="#fd304f" />
        <NextButton
          label="Make your first ally"
          active
          bottom={66}
          onClick={() => goTo("name")}
        />
        <p
          data-testid="sign-in-link"
          style={{
            textAlign: "center",
            fontSize: 16,
            fontWeight: 600,
            letterSpacing: -0.61,
            lineHeight: "22px",
            color: "#000",
            left: 0,
            right: 0,
            bottom: 24,
            width: "100%",
            position: "absolute",
            margin: 0,
          }}
        >
          Not new to this? <span style={{ color: "#ff5800" }}>Sign in</span>
        </p>
      </div>
    </Artboard>
  );
}
