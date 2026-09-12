"use client";

import { useEffect, useRef, type ReactNode } from "react";

export type WanderAgent = {
  id: string;
  start: { left: number; top: number };
  render: () => ReactNode;
};

type Body = {
  x: number;
  y: number;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  midX: number;
  midY: number;
  flyStarted: number;
  flyDuration: number;
  mode: "work" | "fly";
  workUntil: number;
  angle: number;
};

function bezier(from: number, mid: number, to: number, t: number) {
  const rest = 1 - t;
  return rest * rest * from + 2 * rest * t * mid + t * t * to;
}

function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function easeInOut(t: number) {
  const clamped = Math.min(1, Math.max(0, t));
  return clamped < 0.5
    ? 4 * clamped * clamped * clamped
    : 1 - (-2 * clamped + 2) ** 3 / 2;
}

function rand(min: number, max: number) {
  return min + Math.random() * (max - min);
}

function pickSpot(
  artW: number,
  artH: number,
  others: Array<{ x: number; y: number }>,
) {
  const pad = 24;
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const x = rand(pad, Math.max(pad + 1, artW - 86));
    const y = rand(pad, Math.max(pad + 1, artH - 84));
    const farEnough = others.every(
      (other) => Math.hypot(other.x - x, other.y - y) > 120,
    );
    if (farEnough) return { x, y };
  }
  return {
    x: rand(pad, Math.max(pad + 1, artW - 86)),
    y: rand(pad, Math.max(pad + 1, artH - 84)),
  };
}

export function WanderAllies({
  artW,
  artH,
  agents,
}: {
  artW: number;
  artH: number;
  agents: WanderAgent[];
}) {
  const layerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const layer = layerRef.current;
    if (!layer || prefersReducedMotion()) return;

    const now = performance.now();
    const bodies: Body[] = agents.map((agent) => ({
      x: agent.start.left,
      y: agent.start.top,
      fromX: agent.start.left,
      fromY: agent.start.top,
      toX: agent.start.left,
      toY: agent.start.top,
      midX: agent.start.left,
      midY: agent.start.top,
      flyStarted: now,
      flyDuration: 1,
      mode: "work",
      workUntil: now + rand(500, 1400),
      angle: 0,
    }));

    const nodes = Array.from(
      layer.querySelectorAll<HTMLElement>("[data-wander]"),
    );

    const place = (index: number, x: number, y: number, angle: number, busy: boolean) => {
      const node = nodes[index];
      if (!node) return;
      node.style.transform = `translate3d(${x}px, ${y}px, 0) rotate(${angle}deg)`;
      node.dataset.busy = busy ? "true" : "false";
    };

    let frame = 0;
    const tick = (time: number) => {
      bodies.forEach((body, index) => {
        if (body.mode === "work") {
          const bob = Math.sin(time / 380 + index * 1.8) * 3.2;
          const nod = Math.sin(time / 280 + index) * 5;
          body.angle += (nod - body.angle) * 0.05;
          place(index, body.x, body.y + bob, body.angle, true);

          if (time < body.workUntil) return;

          const others = bodies
            .filter((_, other) => other !== index)
            .map((item) => ({ x: item.x, y: item.y }));
          const next = pickSpot(artW, artH, others);
          body.fromX = body.x;
          body.fromY = body.y;
          body.toX = next.x;
          body.toY = next.y;
          body.midX = Math.max(24, Math.min(artW - 86, (body.x + next.x) / 2 + rand(-90, 90)));
          body.midY = Math.max(24, Math.min(artH - 84, (body.y + next.y) / 2 + rand(-70, 70)));
          body.flyStarted = time;
          body.flyDuration = rand(3200, 6200);
          body.mode = "fly";
          return;
        }

        const t = (time - body.flyStarted) / body.flyDuration;
        if (t >= 1) {
          body.x = body.toX;
          body.y = body.toY;
          body.mode = "work";
          body.workUntil = time + rand(1500, 3000);
          place(index, body.x, body.y, body.angle, true);
          return;
        }

        const p = easeInOut(t);
        const nextX = bezier(body.fromX, body.midX, body.toX, p);
        const nextY = bezier(body.fromY, body.midY, body.toY, p);
        const heading =
          (Math.atan2(nextY - body.y, nextX - body.x) * 180) / Math.PI;
        body.x = nextX;
        body.y = nextY;
        const bank = Math.max(-12, Math.min(12, heading * 0.12));
        body.angle += (bank - body.angle) * 0.04;
        place(index, body.x, body.y, body.angle, false);
      });
      frame = window.requestAnimationFrame(tick);
    };

    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [artH, artW, agents]);

  return (
    <div
      ref={layerRef}
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        zIndex: 3,
      }}
    >
      {agents.map((agent) => (
        <div
          key={agent.id}
          data-wander
          className="ally-wander"
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            transform: `translate3d(${agent.start.left}px, ${agent.start.top}px, 0)`,
            willChange: "transform",
          }}
        >
          {agent.render()}
        </div>
      ))}
    </div>
  );
}
