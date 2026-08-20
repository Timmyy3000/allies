import { describe, expect, it } from 'vitest';

import { FLOATING_ALLIES } from './onboarding-characters';
import {
  ENTRANCE_DURATION_FRAMES,
  ENTRANCE_PATHS,
  IDLE_BLEND_END_FRAME,
  MOBILE_MOTION_SAMPLE_STEP,
  MOBILE_MOTION_SAMPLES,
  getEntranceMotionState,
} from './ally-motion';

describe('onboarding floating Allies', () => {
  it('keeps the screenshot colors mapped to the Remotion identities', () => {
    expect(FLOATING_ALLIES.map(({ color, identity }) => [color, identity])).toEqual([
      ['blue', 'rolly'],
      ['yellow', 'boxy'],
      ['green', 'rocky'],
      ['pink', 'ghosty'],
    ]);
  });

  it('keeps the IntroVid2 entrance stagger and path endpoints', () => {
    expect(ENTRANCE_PATHS.blue.delayFrames).toBe(0);
    expect(ENTRANCE_PATHS.green.delayFrames).toBe(10);
    expect(ENTRANCE_PATHS.pink.delayFrames).toBe(15);
    expect(ENTRANCE_PATHS.yellow.delayFrames).toBe(25);

    expect(ENTRANCE_PATHS.blue.start).toEqual({ x: 1280, y: -220 });
    expect(ENTRANCE_PATHS.blue.end).toEqual({ x: 1680, y: 720 });
    expect(ENTRANCE_PATHS.green.end).toEqual({ x: 1220, y: 1360 });
    expect(ENTRANCE_PATHS.pink.end).toEqual({ x: 2820, y: 700 });
    expect(ENTRANCE_PATHS.yellow.end).toEqual({ x: 2060, y: 1440 });
    expect(ENTRANCE_PATHS.blue.durationFrames).toBe(ENTRANCE_DURATION_FRAMES);
  });

  it('hides cursors once an entrance settles', () => {
    expect(getEntranceMotionState(0)).toBe('anticipating');
    expect(getEntranceMotionState(8)).toBe('traveling');
    expect(getEntranceMotionState(ENTRANCE_DURATION_FRAMES + 8)).toBe('settling');
    expect(getEntranceMotionState(ENTRANCE_DURATION_FRAMES + 18)).toBe('idle');
  });

  it('precomputes a bounded motion table with stable path endpoints', () => {
    const expectedSampleCount = IDLE_BLEND_END_FRAME / MOBILE_MOTION_SAMPLE_STEP + 1;

    for (const color of ['blue', 'green', 'pink', 'yellow'] as const) {
      const samples = MOBILE_MOTION_SAMPLES[color];
      const firstSample = samples[0];
      const lastSample = samples[samples.length - 1];

      expect(samples).toHaveLength(expectedSampleCount);
      expect(firstSample.x).toBeCloseTo(ENTRANCE_PATHS[color].start.x, 5);
      expect(firstSample.y).toBeCloseTo(ENTRANCE_PATHS[color].start.y, 5);
      expect(lastSample.x).toBeCloseTo(ENTRANCE_PATHS[color].end.x, 5);
      expect(lastSample.y).toBeCloseTo(ENTRANCE_PATHS[color].end.y, 5);
      expect(lastSample.progress).toBe(1);
      expect(lastSample.idleWeight).toBe(1);
      expect(Number.isFinite(lastSample.directionDeg)).toBe(true);
    }
  });

});
