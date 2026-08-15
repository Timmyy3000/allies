"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

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
  const hostRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const update = () => setScale(getArtboardScale(host.clientWidth));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={hostRef}
      className="relative w-full overflow-hidden"
      style={{ background }}
    >
      <div style={{ height: ART_H * scale, width: "100%" }} aria-hidden />
      <div
        className="absolute top-0 origin-top-left"
        style={{
          left: `calc(50% - ${(ART_W * scale) / 2}px)`,
          width: ART_W,
          height: ART_H,
          transform: `scale(${scale})`,
          background,
        }}
      >
        {/* device chrome stripped — status bar + home indicator */}
        {children}
      </div>
    </div>
  );
}
