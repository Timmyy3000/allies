import { describe, expect, it } from 'vitest';

import {
  ALLY_IDLE_PERIOD_MS,
  ALLY_IDLE_SPRITES,
  getAllyIdleSpriteFrame,
} from './ally-idle-sprite-motion';

describe('sprite Ally idle motion', () => {
  it('keeps every sprite loop aligned to the shared idle clock', () => {
    expect(ALLY_IDLE_PERIOD_MS).toBe(4000);

    for (const sprite of Object.values(ALLY_IDLE_SPRITES)) {
      expect(sprite.columns).toBe(16);
      expect(sprite.frameCount).toBeGreaterThan(0);
    }
  });

  it('clamps progress to the available frame range', () => {
    expect(getAllyIdleSpriteFrame(0, 130)).toBe(0);
    expect(getAllyIdleSpriteFrame(0.5, 130)).toBe(65);
    expect(getAllyIdleSpriteFrame(1, 130)).toBe(129);
    expect(getAllyIdleSpriteFrame(-1, 130)).toBe(0);
  });
});
