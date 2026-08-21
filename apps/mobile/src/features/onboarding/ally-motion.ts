import type { AllyColor } from './onboarding-characters';
import { ALLY_IDLE_PERIOD_MS } from './ally-idle-sprite-motion';

export type MotionPoint = {
  x: number;
  y: number;
};

export type EntranceMotionState = 'anticipating' | 'traveling' | 'settling' | 'idle';

export type AllyIdleMotion = {
  yRange: readonly [number, number];
  xRange: readonly [number, number];
  rotRange: readonly [number, number];
  periodFrames: number;
  phase: number;
};

export type EntrancePath = {
  start: MotionPoint;
  control1: MotionPoint;
  control2: MotionPoint;
  end: MotionPoint;
  totalLength: number;
  delayFrames: number;
  durationFrames: number;
  easing: 'travelIn' | 'softTravelIn';
  entryTiltDeg: number;
  responsiveness: number;
  organicDeviation: number;
  idle: AllyIdleMotion;
  arcLengths: readonly number[];
};

export const ENTRANCE_FPS = 60;
export const ENTRANCE_DURATION_FRAMES = 55;
export const ANTICIPATION_FRAMES = 8;
export const SETTLE_FADE_LEAD_FRAMES = 6;
export const SETTLE_FADE_DURATION_FRAMES = 10;
export const TOTAL_ENTRANCE_FRAMES =
  ANTICIPATION_FRAMES +
  ENTRANCE_DURATION_FRAMES -
  SETTLE_FADE_LEAD_FRAMES +
  SETTLE_FADE_DURATION_FRAMES;

export const IDLE_BLEND_START_FRAME =
  ANTICIPATION_FRAMES + ENTRANCE_DURATION_FRAMES - 8;
export const IDLE_BLEND_FRAMES = 20;
export const IDLE_BLEND_END_FRAME = IDLE_BLEND_START_FRAME + IDLE_BLEND_FRAMES;
export const MOBILE_MOTION_SAMPLE_STEP = 0.5;

const ARC_LENGTH_SAMPLES = 48;

function cubicPoint(
  start: MotionPoint,
  control1: MotionPoint,
  control2: MotionPoint,
  end: MotionPoint,
  t: number,
): MotionPoint {
  const inverse = 1 - t;
  const inverseSquared = inverse * inverse;
  const tSquared = t * t;

  return {
    x:
      inverseSquared * inverse * start.x +
      3 * inverseSquared * t * control1.x +
      3 * inverse * tSquared * control2.x +
      tSquared * t * end.x,
    y:
      inverseSquared * inverse * start.y +
      3 * inverseSquared * t * control1.y +
      3 * inverse * tSquared * control2.y +
      tSquared * t * end.y,
  };
}

function getArcLengths(
  start: MotionPoint,
  control1: MotionPoint,
  control2: MotionPoint,
  end: MotionPoint,
) {
  const lengths = [0];
  let total = 0;
  let previous = start;

  for (let index = 1; index <= ARC_LENGTH_SAMPLES; index += 1) {
    const point = cubicPoint(start, control1, control2, end, index / ARC_LENGTH_SAMPLES);
    total += Math.hypot(point.x - previous.x, point.y - previous.y);
    lengths.push(total);
    previous = point;
  }

  return lengths.map((length) => length / total);
}

function createEntrancePath(
  path: Omit<EntrancePath, 'arcLengths'>,
): EntrancePath {
  return {
    ...path,
    arcLengths: getArcLengths(path.start, path.control1, path.control2, path.end),
  };
}

export const ENTRANCE_PATHS = {
  blue: createEntrancePath({
    start: { x: 1280, y: -220 },
    control1: { x: 836, y: 316 },
    control2: { x: 1974, y: 235 },
    end: { x: 1680, y: 720 },
    totalLength: 1242.1260025390552,
    delayFrames: 0,
    durationFrames: ENTRANCE_DURATION_FRAMES,
    easing: 'travelIn',
    entryTiltDeg: -8,
    responsiveness: 0.32,
    organicDeviation: 2.8,
    idle: {
      yRange: [-20, 20],
      xRange: [-14, 14],
      rotRange: [-3, 3],
      periodFrames: 180,
      phase: 0,
    },
  }),
  green: createEntrancePath({
    start: { x: -220, y: 1980 },
    control1: { x: -55, y: 1179 },
    control2: { x: 952, y: 2069 },
    end: { x: 1220, y: 1360 },
    totalLength: 1762.3636609094228,
    delayFrames: 10,
    durationFrames: ENTRANCE_DURATION_FRAMES,
    easing: 'softTravelIn',
    entryTiltDeg: 8,
    responsiveness: 0.22,
    organicDeviation: 3.2,
    idle: {
      yRange: [-18, 18],
      xRange: [-15, 15],
      rotRange: [-2.5, 2.5],
      periodFrames: 210,
      phase: 1.5,
    },
  }),
  pink: createEntrancePath({
    start: { x: 4060, y: 720 },
    control1: { x: 3658, y: 103 },
    control2: { x: 3185, y: 152 },
    end: { x: 2820, y: 700 },
    totalLength: 1579.9406448417428,
    delayFrames: 15,
    durationFrames: ENTRANCE_DURATION_FRAMES,
    easing: 'travelIn',
    entryTiltDeg: -10,
    responsiveness: 0.3,
    organicDeviation: 3,
    idle: {
      yRange: [-22, 22],
      xRange: [-14, 14],
      rotRange: [-3.5, 3.5],
      periodFrames: 170,
      phase: 3.1,
    },
  }),
  yellow: createEntrancePath({
    start: { x: 2850, y: 2380 },
    control1: { x: 2177, y: 2483 },
    control2: { x: 2720, y: 1374 },
    end: { x: 2060, y: 1440 },
    totalLength: 1433.4679476916995,
    delayFrames: 25,
    durationFrames: ENTRANCE_DURATION_FRAMES,
    easing: 'travelIn',
    entryTiltDeg: 8,
    responsiveness: 0.26,
    organicDeviation: 2.8,
    idle: {
      yRange: [-18, 18],
      xRange: [-16, 16],
      rotRange: [-2.5, 2.5],
      periodFrames: 195,
      phase: 4.5,
    },
  }),
} as const satisfies Record<AllyColor, EntrancePath>;

export type MobileMotionSample = {
  x: number;
  y: number;
  progress: number;
  idleWeight: number;
  directionDeg: number;
  targetDirectionDeg: number;
  velocity: number;
};

export type MobileIdleSample = {
  x: number;
  y: number;
  rotation: number;
};

type MotionTarget = {
  x: number;
  y: number;
  normalX: number;
  normalY: number;
  progress: number;
};

type TravelSample = Pick<MobileMotionSample, 'x' | 'y' | 'progress' | 'idleWeight'>;

function motionClamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function motionSmoothstep(value: number) {
  const clamped = motionClamp(value, 0, 1);
  return clamped * clamped * (3 - 2 * clamped);
}

function cubicBezierCoordinateForMotion(t: number, first: number, second: number) {
  const inverse = 1 - t;
  return 3 * inverse * inverse * t * first + 3 * inverse * t * t * second + t * t * t;
}

function cubicBezierSlopeForMotion(t: number, first: number, second: number) {
  const inverse = 1 - t;
  return 3 * inverse * inverse * first + 6 * inverse * t * (second - first) + 3 * t * t * (1 - second);
}

function cubicBezierEaseForMotion(
  t: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
) {
  if (t <= 0 || t >= 1) {
    return t;
  }

  let parameter = t;
  for (let index = 0; index < 5; index += 1) {
    const slope = cubicBezierSlopeForMotion(parameter, x1, x2);
    if (Math.abs(slope) < 0.0001) {
      break;
    }
    parameter = motionClamp(
      parameter -
        (cubicBezierCoordinateForMotion(parameter, x1, x2) - t) / slope,
      0,
      1,
    );
  }

  return cubicBezierCoordinateForMotion(parameter, y1, y2);
}

function getArcParameterForMotion(arcLengths: readonly number[], distance: number) {
  const target = motionClamp(distance, 0, 1);

  for (let index = 1; index < arcLengths.length; index += 1) {
    if (target <= arcLengths[index]) {
      const previousLength = arcLengths[index - 1];
      const segmentLength = arcLengths[index] - previousLength || 1;
      const segmentProgress = (target - previousLength) / segmentLength;
      return (index - 1 + segmentProgress) / (arcLengths.length - 1);
    }
  }

  return 1;
}

function getPathPointForMotion(motion: EntrancePath, distance: number) {
  const parameter = getArcParameterForMotion(
    motion.arcLengths,
    distance / motion.totalLength,
  );

  return cubicPoint(
    motion.start,
    motion.control1,
    motion.control2,
    motion.end,
    parameter,
  );
}

function getPathTangentForMotion(motion: EntrancePath, distance: number) {
  const pointBefore = getPathPointForMotion(motion, Math.max(0, distance - 1));
  const pointAfter = getPathPointForMotion(
    motion,
    Math.min(motion.totalLength, distance + 1),
  );
  const x = pointAfter.x - pointBefore.x;
  const y = pointAfter.y - pointBefore.y;
  const length = Math.hypot(x, y) || 1;

  return { x: x / length, y: y / length };
}

function getPathTargetForMotion(
  motion: EntrancePath,
  frame: number,
  startFrame: number,
): MotionTarget {
  const endFrame = startFrame + motion.durationFrames;

  if (frame <= startFrame) {
    const point = getPathPointForMotion(motion, 0);
    const tangent = getPathTangentForMotion(motion, 0);

    return {
      x: point.x,
      y: point.y,
      normalX: -tangent.y,
      normalY: tangent.x,
      progress: 0,
    };
  }

  if (frame >= endFrame) {
    const point = getPathPointForMotion(motion, motion.totalLength);
    const tangent = getPathTangentForMotion(motion, motion.totalLength);

    return {
      x: point.x,
      y: point.y,
      normalX: -tangent.y,
      normalY: tangent.x,
      progress: 1,
    };
  }

  const rawProgress = motionClamp(
    (frame - startFrame) / motion.durationFrames,
    0,
    1,
  );
  const easedProgress = cubicBezierEaseForMotion(
    rawProgress,
    motion.easing === 'softTravelIn' ? 0.16 : 0.22,
    1,
    motion.easing === 'softTravelIn' ? 0.3 : 0.36,
    1,
  );
  const distance = easedProgress * motion.totalLength;
  const point = getPathPointForMotion(motion, distance);
  const tangent = getPathTangentForMotion(motion, distance);

  return {
    x: point.x,
    y: point.y,
    normalX: -tangent.y,
    normalY: tangent.x,
    progress: easedProgress,
  };
}

function getTravelSampleAtFrame(samples: readonly TravelSample[], frame: number) {
  const boundedFrame = motionClamp(frame, 0, IDLE_BLEND_END_FRAME);
  const samplePosition = boundedFrame / MOBILE_MOTION_SAMPLE_STEP;
  const lowerIndex = Math.floor(samplePosition);
  const upperIndex = Math.min(samples.length - 1, lowerIndex + 1);
  const alpha = samplePosition - lowerIndex;
  const lower = samples[lowerIndex];
  const upper = samples[upperIndex];

  return {
    x: lower.x + (upper.x - lower.x) * alpha,
    y: lower.y + (upper.y - lower.y) * alpha,
  };
}

function getAngleDifference(target: number, current: number) {
  return ((target - current + 540) % 360) - 180;
}

function getTravelSamples(motion: EntrancePath): TravelSample[] {
  const sampleCount = IDLE_BLEND_END_FRAME / MOBILE_MOTION_SAMPLE_STEP + 1;
  const samples: TravelSample[] = [];
  const followerAlpha = 1 - Math.pow(1 - motion.responsiveness, MOBILE_MOTION_SAMPLE_STEP);
  let followerX = motion.start.x;
  let followerY = motion.start.y;

  for (let index = 0; index < sampleCount; index += 1) {
    const frame = index * MOBILE_MOTION_SAMPLE_STEP;
    const target = getPathTargetForMotion(motion, frame, ANTICIPATION_FRAMES);

    if (frame > ANTICIPATION_FRAMES) {
      followerX += (target.x - followerX) * followerAlpha;
      followerY += (target.y - followerY) * followerAlpha;
    }

    const settleProgress = motionSmoothstep(
      (frame - (ANTICIPATION_FRAMES + motion.durationFrames)) / 12,
    );
    const finalX = followerX * (1 - settleProgress) + target.x * settleProgress;
    const finalY = followerY * (1 - settleProgress) + target.y * settleProgress;
    const organicEnvelope = Math.sin(target.progress * Math.PI);
    const organicWave =
      Math.sin(target.progress * Math.PI * 3 + 1.2) +
      Math.sin(target.progress * Math.PI * 6.5 + 0.8) * 0.45 +
      Math.cos(target.progress * Math.PI * 11 + 2.1) * 0.25;
    const organicOffset =
      target.progress > 0.01 && target.progress < 0.99
        ? organicWave * motion.organicDeviation * organicEnvelope
        : 0;

    samples.push({
      x: finalX + target.normalX * organicOffset,
      y: finalY + target.normalY * organicOffset,
      progress: target.progress,
      idleWeight: motionSmoothstep(
        (frame - IDLE_BLEND_START_FRAME) / IDLE_BLEND_FRAMES,
      ),
    });
  }

  return samples;
}

const DIRECTION_TIE_BREAK_SIGN: Record<AllyColor, number> = {
  blue: 1,
  green: -1,
  pink: 1,
  yellow: -1,
};

function buildMobileMotionSamples(
  motion: EntrancePath,
  tieBreakSign: number,
): MobileMotionSample[] {
  const travelSamples = getTravelSamples(motion);
  const initialTangent = getPathTangentForMotion(motion, 0);
  const initialPathAngle = Math.atan2(initialTangent.y, initialTangent.x) * (180 / Math.PI);
  const directionSamples: {
    directionDeg: number;
    targetDirectionDeg: number;
    velocity: number;
  }[] = [];
  let displayedDirection = initialPathAngle;
  let lastStableDirection = initialPathAngle;

  for (let frame = 0; frame <= IDLE_BLEND_END_FRAME; frame += 1) {
    let targetDirection = initialPathAngle;
    let velocity = 0;

    if (frame >= ANTICIPATION_FRAMES) {
      const ahead = getTravelSampleAtFrame(travelSamples, frame + 0.25);
      const behind = getTravelSampleAtFrame(travelSamples, frame - 0.25);
      const velocityX = (ahead.x - behind.x) / 0.5;
      const velocityY = (ahead.y - behind.y) / 0.5;
      velocity = Math.hypot(velocityX, velocityY);

      if (velocity >= 1) {
        targetDirection = Math.atan2(velocityY, velocityX) * (180 / Math.PI);
        lastStableDirection = targetDirection;
      } else {
        targetDirection = lastStableDirection;
      }
    }

    const directionDifference = getAngleDifference(targetDirection, displayedDirection);
    const smoothedDifference =
      Math.abs(Math.abs(directionDifference) - 180) < 0.05
        ? tieBreakSign * 180
        : directionDifference;
    displayedDirection += smoothedDifference * 0.22;

    directionSamples.push({
      directionDeg: displayedDirection,
      targetDirectionDeg: targetDirection,
      velocity,
    });
  }

  return travelSamples.map((travelSample, index) => {
    const frame = index * MOBILE_MOTION_SAMPLE_STEP;
    const lowerIndex = Math.floor(frame);
    const upperIndex = Math.min(directionSamples.length - 1, lowerIndex + 1);
    const alpha = frame - lowerIndex;
    const lower = directionSamples[lowerIndex];
    const upper = directionSamples[upperIndex];

    return {
      ...travelSample,
      directionDeg: lower.directionDeg + (upper.directionDeg - lower.directionDeg) * alpha,
      targetDirectionDeg:
        lower.targetDirectionDeg +
        (upper.targetDirectionDeg - lower.targetDirectionDeg) * alpha,
      velocity: lower.velocity + (upper.velocity - lower.velocity) * alpha,
    };
  });
}

export const MOBILE_MOTION_SAMPLES = {
  blue: buildMobileMotionSamples(
    ENTRANCE_PATHS.blue,
    DIRECTION_TIE_BREAK_SIGN.blue,
  ),
  green: buildMobileMotionSamples(
    ENTRANCE_PATHS.green,
    DIRECTION_TIE_BREAK_SIGN.green,
  ),
  pink: buildMobileMotionSamples(
    ENTRANCE_PATHS.pink,
    DIRECTION_TIE_BREAK_SIGN.pink,
  ),
  yellow: buildMobileMotionSamples(
    ENTRANCE_PATHS.yellow,
    DIRECTION_TIE_BREAK_SIGN.yellow,
  ),
} as const satisfies Record<AllyColor, readonly MobileMotionSample[]>;

const IDLE_SAMPLE_COUNT = 241;
const REMOTION_BASE_ENTRANCE_START_FRAME = 184;

function buildIdleMotionSamples(motion: EntrancePath): MobileIdleSample[] {
  const idlePhaseOffset =
    ((REMOTION_BASE_ENTRANCE_START_FRAME +
      motion.delayFrames -
      ANTICIPATION_FRAMES +
      IDLE_BLEND_END_FRAME) /
      motion.idle.periodFrames) *
      2 *
      Math.PI +
    motion.idle.phase;

  return Array.from({ length: IDLE_SAMPLE_COUNT }, (_, index) => {
    const progress = index / (IDLE_SAMPLE_COUNT - 1);
    const idleTime =
      (progress * (ALLY_IDLE_PERIOD_MS / 1_000) * ENTRANCE_FPS * 2 * Math.PI) /
        motion.idle.periodFrames +
      idlePhaseOffset;
    const halfXRange = (motion.idle.xRange[1] - motion.idle.xRange[0]) / 2;
    const halfYRange = (motion.idle.yRange[1] - motion.idle.yRange[0]) / 2;

    return {
      x:
        Math.cos(idleTime * 1.15) * halfXRange * 2 +
        Math.sin(idleTime * 0.65 + 1.2) * 3.5,
      y:
        Math.sin(idleTime) * halfYRange * 2 +
        Math.sin(idleTime * 2.15 + 0.4) * 4.5,
      rotation:
        Math.sin(idleTime * 0.95) *
          ((motion.idle.rotRange[1] - motion.idle.rotRange[0]) / 2) +
        Math.cos(idleTime * 1.8 + 0.9) * 0.8,
    };
  });
}

export const MOBILE_IDLE_MOTION_SAMPLES = {
  blue: buildIdleMotionSamples(ENTRANCE_PATHS.blue),
  green: buildIdleMotionSamples(ENTRANCE_PATHS.green),
  pink: buildIdleMotionSamples(ENTRANCE_PATHS.pink),
  yellow: buildIdleMotionSamples(ENTRANCE_PATHS.yellow),
} as const satisfies Record<AllyColor, readonly MobileIdleSample[]>;

export function getEntranceMotionState(frame: number): EntranceMotionState {
  if (frame < ANTICIPATION_FRAMES) {
    return 'anticipating';
  }

  if (frame < ANTICIPATION_FRAMES + ENTRANCE_DURATION_FRAMES - SETTLE_FADE_LEAD_FRAMES) {
    return 'traveling';
  }

  if (frame <= TOTAL_ENTRANCE_FRAMES) {
    return 'settling';
  }

  return 'idle';
}
