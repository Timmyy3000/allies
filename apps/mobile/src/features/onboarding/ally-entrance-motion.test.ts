import { describe, expect, it } from 'vitest';

import {
  ENTRANCE_CURVES,
  ENTRANCE_DELAYS_MS,
  ENTRANCE_DURATION_MS,
  ENTRANCE_EASING,
  getCubicTangent,
  getCubicPoint,
  getIdleHoverOffset,
  getOrbitPoint,
} from './ally-entrance-motion';

describe('mobile Ally entrance curves', () => {
  it('keeps the Remotion entrance directions, stagger, and easing contract', () => {
    expect(ENTRANCE_CURVES.blue.start.y).toBeLessThan(0);
    expect(ENTRANCE_CURVES.green.start.x).toBeLessThan(0);
    expect(ENTRANCE_CURVES.pink.start.x).toBeGreaterThan(0);
    expect(ENTRANCE_CURVES.yellow.start.x).toBeGreaterThan(0);
    expect(ENTRANCE_CURVES.yellow.start.y).toBeGreaterThan(0);

    expect(ENTRANCE_DELAYS_MS).toEqual({
      blue: 0,
      green: 167,
      pink: 250,
      yellow: 417,
    });
    expect(ENTRANCE_DURATION_MS).toBe(2400);
    expect(ENTRANCE_EASING.standard).toEqual({
      x1: 0.22,
      y1: 1,
      x2: 0.36,
      y2: 1,
    });
    expect(ENTRANCE_EASING.soft).toEqual({
      x1: 0.16,
      y1: 1,
      x2: 0.3,
      y2: 1,
    });
  });

  it('clamps progress and preserves each path endpoint', () => {
    for (const path of Object.values(ENTRANCE_CURVES)) {
      expect(getCubicPoint(path, -1)).toEqual(path.start);
      expect(getCubicPoint(path, 0)).toEqual(path.start);
      expect(getCubicPoint(path, 1)).toEqual(path.end);
      expect(getCubicPoint(path, 2)).toEqual(path.end);
    }
  });

  it('bends every path away from its straight start-to-end midpoint', () => {
    for (const path of Object.values(ENTRANCE_CURVES)) {
      const midpoint = getCubicPoint(path, 0.5);
      const straightMidpoint = {
        x: (path.start.x + path.end.x) / 2,
        y: (path.start.y + path.end.y) / 2,
      };

      expect(
        Math.hypot(
          midpoint.x - straightMidpoint.x,
          midpoint.y - straightMidpoint.y,
        ),
      ).toBeGreaterThan(8);
    }
  });

  it('returns a normalized tangent that follows each curve', () => {
    for (const path of Object.values(ENTRANCE_CURVES)) {
      const tangent = getCubicTangent(path, 0.5);

      expect(Math.hypot(tangent.x, tangent.y)).toBeCloseTo(1, 5);
    }

    expect(getCubicTangent(ENTRANCE_CURVES.blue, 0).x).toBeLessThan(0);
    expect(getCubicTangent(ENTRANCE_CURVES.blue, 0.5).x).toBeGreaterThan(0);
    expect(getCubicTangent(ENTRANCE_CURVES.blue, 1).x).toBeLessThan(0);
  });

  it('places the cursor at a stable radius from the Ally center', () => {
    const radius = 42;
    const orbit = getOrbitPoint(Math.PI / 4, radius);

    expect(Math.hypot(orbit.x, orbit.y)).toBeCloseTo(radius, 5);
    expect(orbit.x).toBeCloseTo(orbit.y, 5);
  });

  it('returns the same hover pose at both ends of the loop', () => {
    for (const phase of [0.2, 1.8, 3.4, 5.1]) {
      const first = getIdleHoverOffset(0, phase);
      const last = getIdleHoverOffset(1, phase);

      expect(last.x).toBeCloseTo(first.x, 5);
      expect(last.y).toBeCloseTo(first.y, 5);
      expect(last.rotation).toBeCloseTo(first.rotation, 5);
    }
  });
});
