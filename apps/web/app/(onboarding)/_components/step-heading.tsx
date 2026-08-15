import type { ReactNode } from "react";

export const HEADING_STYLE = {
  margin: 0,
  fontSize: 24,
  fontWeight: 700,
  letterSpacing: -0.92,
  lineHeight: "32px",
  color: "#121212",
  whiteSpace: "pre-wrap" as const,
};

export function StepHeading({
  mark,
  children,
}: {
  mark?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        left: 20,
        top: 88,
        width: 247,
        position: "absolute",
        display: "flex",
        flexDirection: "column",
        rowGap: 18,
        alignItems: "flex-start",
      }}
      className="step-title"
    >
      {mark}
      <h1 style={HEADING_STYLE}>{children}</h1>
    </div>
  );
}
