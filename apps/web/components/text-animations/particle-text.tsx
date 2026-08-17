"use client";

import { useEffect, useRef } from "react";

type Particle = {
  x: number;
  y: number;
  startX: number;
  startY: number;
  targetX: number;
  targetY: number;
  delay: number;
  size: number;
};

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), max);

export function ParticleText({
  text,
  color,
  className = "",
}: {
  text: string;
  color: string;
  className?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!host || !canvas || !context) return;

    let particles: Particle[] = [];
    let frame = 0;
    let resizeFrame = 0;
    let startedAt = performance.now();
    let width = 0;
    let height = 0;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const build = () => {
      const rect = host.getBoundingClientRect();
      width = Math.max(1, Math.floor(rect.width));
      height = Math.max(1, Math.floor(rect.height));
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);

      const computed = window.getComputedStyle(host);
      const fontSize = Number.parseFloat(computed.fontSize) || 18;
      const fontWeight = computed.fontWeight || "600";
      const fontFamily = computed.fontFamily || "sans-serif";
      const sample = document.createElement("canvas");
      const sampleContext = sample.getContext("2d", { willReadFrequently: true });
      if (!sampleContext) return;

      sampleContext.font = `${fontWeight} ${fontSize}px ${fontFamily}`;
      const metrics = sampleContext.measureText(text);
      const textWidth = Math.ceil(metrics.width);
      const textHeight = Math.ceil(
        (metrics.actualBoundingBoxAscent || fontSize * 0.78) +
          (metrics.actualBoundingBoxDescent || fontSize * 0.22),
      );
      const padding = 6;
      sample.width = textWidth + padding * 2;
      sample.height = textHeight + padding * 2;
      sampleContext.font = `${fontWeight} ${fontSize}px ${fontFamily}`;
      sampleContext.textBaseline = "alphabetic";
      sampleContext.fillStyle = "#fff";
      sampleContext.fillText(
        text,
        padding,
        padding + (metrics.actualBoundingBoxAscent || fontSize * 0.78),
      );

      const pixels = sampleContext.getImageData(0, 0, sample.width, sample.height).data;
      const targets: Array<{ x: number; y: number }> = [];
      const density = 2;
      for (let y = 0; y < sample.height; y += density) {
        for (let x = 0; x < sample.width; x += density) {
          if (pixels[(y * sample.width + x) * 4 + 3] > 48) {
            targets.push({
              x: width / 2 - sample.width / 2 + x,
              y: height / 2 - sample.height / 2 + y,
            });
          }
        }
      }

      const stride = Math.max(1, Math.ceil(targets.length / 900));
      particles = targets
        .filter((_, index) => index % stride === 0)
        .map((target, index) => {
          const seed = ((index * 9301 + 49297) % 233280) / 233280;
          const angle = seed * Math.PI * 2;
          const distance = reducedMotion ? 0 : 54 * (0.45 + seed * 0.6);
          const startX = target.x + Math.cos(angle) * distance;
          const startY = target.y + Math.sin(angle) * distance;
          return {
            x: startX,
            y: startY,
            startX,
            startY,
            targetX: target.x,
            targetY: target.y,
            delay: reducedMotion ? 0 : seed * 260,
            size: 1.25 + seed * 0.75,
          };
        });
      startedAt = performance.now();
    };

    const render = (now: number) => {
      context.clearRect(0, 0, width, height);
      context.fillStyle = color;
      const elapsed = now - startedAt;
      particles.forEach((particle) => {
        const local = clamp((elapsed - particle.delay) / (reducedMotion ? 1 : 920), 0, 1);
        const eased = 1 - (1 - local) ** 3;
        particle.x = particle.startX + (particle.targetX - particle.startX) * eased;
        particle.y = particle.startY + (particle.targetY - particle.startY) * eased;
        context.globalAlpha = 0.25 + local * 0.75;
        context.beginPath();
        context.arc(particle.x, particle.y, particle.size / 2, 0, Math.PI * 2);
        context.fill();
      });
      context.globalAlpha = 1;
      frame = window.requestAnimationFrame(render);
    };

    const queueBuild = () => {
      window.cancelAnimationFrame(resizeFrame);
      resizeFrame = window.requestAnimationFrame(build);
    };

    const observer = new ResizeObserver(queueBuild);
    observer.observe(host);
    void document.fonts?.ready.then(build);
    build();
    frame = window.requestAnimationFrame(render);

    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(frame);
      window.cancelAnimationFrame(resizeFrame);
    };
  }, [color, text]);

  return (
    <div ref={hostRef} className={`particle-text ${className}`} aria-label={text}>
      <canvas ref={canvasRef} className="particle-text__canvas" aria-hidden="true" />
      <span className="particle-text__sr">{text}</span>
    </div>
  );
}
