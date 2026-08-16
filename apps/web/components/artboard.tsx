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
      className="relative min-h-[100dvh] w-full overflow-hidden"
      style={{
        background,
        minHeight: "var(--onboarding-artboard-min-height, 100dvh)",
      }}
    >
      {/* The onboarding frame follows the viewport; children own their insets. */}
      {children}
    </div>
  );
}
