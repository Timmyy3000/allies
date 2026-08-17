import type { ReactNode } from "react";

export const ART_W = 375;
export const ART_H = 812;

export function getArtboardScale(containerWidth: number): number {
  return Math.min(1, Math.max(0, containerWidth / ART_W));
}

export function Artboard({
  children,
  background = "#fff",
}: {
  children: ReactNode;
  background?: string;
}) {
  return (
    <div
      className="onboarding-artboard"
      style={{
        background,
      }}
    >
      {children}
    </div>
  );
}
