import { describe, expect, it } from 'vitest';

import {
  PRESS_SCALE,
  PRESS_SCALE_DURATION_MS,
  getPressScaleTarget,
} from './press-scale';

describe('press scale contract', () => {
  it('scales only enabled controls while pressed', () => {
    expect(PRESS_SCALE).toBe(1.075);
    expect(PRESS_SCALE_DURATION_MS).toBe(140);
    expect(getPressScaleTarget(true, false, false)).toBe(1.075);
    expect(getPressScaleTarget(true, false, false, 1.03)).toBe(1.03);
    expect(getPressScaleTarget(false, false, false)).toBe(1);
    expect(getPressScaleTarget(true, true, false)).toBe(1);
    expect(getPressScaleTarget(true, false, true)).toBe(1);
  });
});
