import type { AllyColor } from './onboarding-characters';

export type MotionPoint = {
  x: number;
  y: number;
};

export type CubicPath = {
  start: MotionPoint;
  control1: MotionPoint;
  control2: MotionPoint;
  end: MotionPoint;
};

export const ENTRANCE_DURATION_MS = 2400;

export const ENTRANCE_DELAYS_MS = {
  blue: 0,
  green: 167,
  pink: 250,
  yellow: 417,
} as const satisfies Record<AllyColor, number>;

export const ENTRANCE_EASING = {
  standard: { x1: 0.22, y1: 1, x2: 0.36, y2: 1 },
  soft: { x1: 0.16, y1: 1, x2: 0.3, y2: 1 },
} as const;

export const ENTRANCE_CURVES = {
  blue: {
    start: { x: -90, y: -280 },
    control1: { x: -190, y: -130 },
    control2: { x: 75, y: -150 },
    end: { x: 0, y: 0 },
  },
  yellow: {
    start: { x: 175, y: 590 },
    control1: { x: 25, y: 650 },
    control2: { x: 145, y: -15 },
    end: { x: 0, y: 0 },
  },
  green: {
    start: { x: -260, y: 230 },
    control1: { x: -215, y: -70 },
    control2: { x: -55, y: 225 },
    end: { x: 0, y: 0 },
  },
  pink: {
    start: { x: 260, y: 10 },
    control1: { x: 185, y: -155 },
    control2: { x: 75, y: -130 },
    end: { x: 0, y: 0 },
  },
} as const satisfies Record<AllyColor, CubicPath>;

function clamp(value: number, minimum: number, maximum: number) {
  'worklet';
  return Math.min(maximum, Math.max(minimum, value));
}

export function getCubicPoint(path: CubicPath, progress: number): MotionPoint {
  'worklet';
  const t = clamp(progress, 0, 1);
  const inverse = 1 - t;
  const inverseSquared = inverse * inverse;
  const tSquared = t * t;

  return {
    x:
      inverseSquared * inverse * path.start.x +
      3 * inverseSquared * t * path.control1.x +
      3 * inverse * tSquared * path.control2.x +
      tSquared * t * path.end.x,
    y:
      inverseSquared * inverse * path.start.y +
      3 * inverseSquared * t * path.control1.y +
      3 * inverse * tSquared * path.control2.y +
      tSquared * t * path.end.y,
  };
}

export function getCubicTangent(path: CubicPath, progress: number): MotionPoint {
  'worklet';
  const t = clamp(progress, 0, 1);
  const inverse = 1 - t;
  const firstX = path.control1.x - path.start.x;
  const firstY = path.control1.y - path.start.y;
  const secondX = path.control2.x - path.control1.x;
  const secondY = path.control2.y - path.control1.y;
  const thirdX = path.end.x - path.control2.x;
  const thirdY = path.end.y - path.control2.y;
  const tangentX =
    3 * (inverse * inverse * firstX + 2 * inverse * t * secondX + t * t * thirdX);
  const tangentY =
    3 * (inverse * inverse * firstY + 2 * inverse * t * secondY + t * t * thirdY);
  const length = Math.hypot(tangentX, tangentY) || 1;

  return { x: tangentX / length, y: tangentY / length };
}

export function getOrbitPoint(angle: number, radius: number): MotionPoint {
  'worklet';
  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius,
  };
}

export type IdleHoverOffset = {
  x: number;
  y: number;
  rotation: number;
};

export function getIdleHoverOffset(
  progress: number,
  phase: number,
): IdleHoverOffset {
  'worklet';
  const angle = clamp(progress, 0, 1) * Math.PI * 2 + phase;

  return {
    x: Math.sin(angle) * 2.5 + Math.sin(angle * 2 + 0.4) * 0.8,
    y: Math.cos(angle * 2) * 3 + Math.sin(angle * 3 + 1.1) * 0.6,
    rotation: Math.sin(angle) * 2.2 + Math.cos(angle * 2 + 0.9) * 0.5,
  };
}
