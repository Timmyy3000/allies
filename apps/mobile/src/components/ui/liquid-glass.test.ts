import { describe, expect, it } from 'vitest';

import { getLiquidGlassPointerEvents, shouldUseLiquidGlass } from './liquid-glass';

describe('Liquid Glass availability', () => {
  it('keeps background-only surfaces out of hit testing and child hosts interactive', () => {
    expect(getLiquidGlassPointerEvents(false)).toBe('none');
    expect(getLiquidGlassPointerEvents(true)).toBe('auto');
  });

  it('uses glass only on a supported iOS device without Reduce Transparency', () => {
    expect(
      shouldUseLiquidGlass({
        apiAvailable: true,
        liquidGlassAvailable: true,
        platform: 'ios',
        reduceTransparency: false,
      }),
    ).toBe(true);

    expect(
      shouldUseLiquidGlass({
        apiAvailable: true,
        liquidGlassAvailable: true,
        platform: 'ios',
        reduceTransparency: false,
        forceFallback: true,
      }),
    ).toBe(false);

    for (const unavailable of [
      { apiAvailable: true, liquidGlassAvailable: true, platform: 'android', reduceTransparency: false },
      { apiAvailable: false, liquidGlassAvailable: true, platform: 'ios', reduceTransparency: false },
      { apiAvailable: true, liquidGlassAvailable: false, platform: 'ios', reduceTransparency: false },
      { apiAvailable: true, liquidGlassAvailable: true, platform: 'ios', reduceTransparency: true },
    ] as const) {
      expect(shouldUseLiquidGlass(unavailable)).toBe(false);
    }
  });
});
