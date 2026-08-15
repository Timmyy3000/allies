"use client";

import { useEffect, useRef } from "react";

export type SparkTrigger = {
  id: number;
  x: number;
  y: number;
};

type Spark = {
  angle: number;
  startTime: number;
};

/**
 * A small, canvas-based click reaction. The trigger is explicit so staged
 * choreography can fire the same reaction as a real pointer click without
 * making the decorative layer interactive.
 */
export function ClickSpark({
  trigger,
  sparkColor = "#121212",
  sparkSize = 8,
  sparkRadius = 16,
  sparkCount = 8,
  duration = 420,
}: {
  trigger: SparkTrigger | null;
  sparkColor?: string;
  sparkSize?: number;
  sparkRadius?: number;
  sparkCount?: number;
  duration?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sparksRef = useRef<Spark[]>([]);
  const frameRef = useRef<number | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });

  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;

    const resize = () => {
      const rect = parent.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      sizeRef.current = { width: rect.width, height: rect.height };
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      const context = canvas.getContext("2d");
      context?.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(parent);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!trigger) return;

    const now = performance.now();
    sparksRef.current.push(
      ...Array.from({ length: sparkCount }, (_, index) => ({
        angle: (Math.PI * 2 * index) / sparkCount,
        startTime: now,
      })),
    );

    if (frameRef.current !== null) return;

    const draw = (time: number) => {
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (!canvas || !context) {
        frameRef.current = null;
        return;
      }

      const { width, height } = sizeRef.current;
      context.clearRect(0, 0, width, height);
      const alive: Spark[] = [];

      for (const spark of sparksRef.current) {
        const progress = Math.min(1, (time - spark.startTime) / duration);
        if (progress >= 1) continue;

        const eased = 1 - (1 - progress) ** 2;
        const distance = eased * sparkRadius;
        const lineLength = sparkSize * (1 - eased);
        const startX = trigger.x + Math.cos(spark.angle) * distance;
        const startY = trigger.y + Math.sin(spark.angle) * distance;
        const endX =
          trigger.x + Math.cos(spark.angle) * (distance + lineLength);
        const endY =
          trigger.y + Math.sin(spark.angle) * (distance + lineLength);

        context.strokeStyle = sparkColor;
        context.lineWidth = 2;
        context.lineCap = "round";
        context.beginPath();
        context.moveTo(startX, startY);
        context.lineTo(endX, endY);
        context.stroke();
        alive.push(spark);
      }

      sparksRef.current = alive;
      if (alive.length > 0) {
        frameRef.current = window.requestAnimationFrame(draw);
      } else {
        frameRef.current = null;
      }
    };

    frameRef.current = window.requestAnimationFrame(draw);
    return () => {
      if (frameRef.current !== null && sparksRef.current.length === 0) {
        window.cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
      }
    };
  }, [duration, sparkColor, sparkCount, sparkRadius, sparkSize, trigger]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      data-click-spark
      style={{
        position: "absolute",
        inset: 0,
        zIndex: 5,
        pointerEvents: "none",
        display: "block",
      }}
    />
  );
}
