import type { CSSProperties, ReactNode } from "react";
import { ONBOARDING_LAYOUT } from "@/components/next-button";

export const HEADING_STYLE = {
  margin: 0,
  fontFamily: "var(--font-open-runde), sans-serif",
  fontSize: 24,
  fontWeight: 700,
  letterSpacing: -1,
  lineHeight: "100%",
  color: "#121212",
  whiteSpace: "pre-wrap" as const,
};

export function StepHeading({
  mark,
  children,
  lineHeight,
}: {
  mark?: ReactNode;
  children: ReactNode;
  lineHeight?: CSSProperties["lineHeight"];
}) {
  return (
    <div
      style={{
        left: 20,
        right: 20,
        top: ONBOARDING_LAYOUT.headingTop,
        position: "absolute",
        display: "flex",
        flexDirection: "column",
        rowGap: 18,
        alignItems: "flex-start",
      }}
      className="step-title"
    >
      {mark}
      <h1 style={{ ...HEADING_STYLE, ...(lineHeight ? { lineHeight } : {}) }}>
        {children}
      </h1>
    </div>
  );
}
