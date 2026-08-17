import type { CSSProperties, ReactNode } from "react";

export const HEADING_STYLE = {
  margin: 0,
  fontFamily: "var(--font-open-runde), sans-serif",
  fontSize: 24,
  fontWeight: 700,
  letterSpacing: -1,
  lineHeight: "120%",
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
      className="step-title onboarding-step-heading"
    >
      {mark}
      <h1 style={{ ...HEADING_STYLE, ...(lineHeight ? { lineHeight } : {}) }}>
        {children}
      </h1>
    </div>
  );
}
