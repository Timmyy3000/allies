import { describe, expect, it } from 'vitest';

import {
  getBottomSheetAnimationTarget,
  shouldDismissBottomSheet,
} from './bottom-sheet-motion';

describe('bottom sheet modal motion', () => {
  it('animates the backdrop opacity separately from the sheet position', () => {
    expect(getBottomSheetAnimationTarget(true, false, 844)).toEqual({
      duration: 260,
      overlayOpacity: 1,
      translateY: 0,
    });
    expect(getBottomSheetAnimationTarget(false, false, 844)).toEqual({
      duration: 260,
      overlayOpacity: 0,
      translateY: 844,
    });
  });

  it('keeps the final positions while disabling motion when requested', () => {
    expect(getBottomSheetAnimationTarget(true, true, 844)).toEqual({
      duration: 0,
      overlayOpacity: 1,
      translateY: 0,
    });
    expect(getBottomSheetAnimationTarget(false, true, 844)).toEqual({
      duration: 0,
      overlayOpacity: 0,
      translateY: 844,
    });
  });

  it('dismisses after a deliberate downward drag or a fast downward fling', () => {
    expect(shouldDismissBottomSheet(170, 0, 844)).toBe(true);
    expect(shouldDismissBottomSheet(150, 0, 844)).toBe(false);
    expect(shouldDismissBottomSheet(0, 900, 844)).toBe(true);
    expect(shouldDismissBottomSheet(0, -900, 844)).toBe(false);
  });
});
