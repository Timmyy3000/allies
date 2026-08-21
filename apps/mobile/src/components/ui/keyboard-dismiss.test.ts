// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';

import { dismissKeyboard, shouldDismissKeyboardForTouch } from './keyboard-dismiss';

describe('dismissKeyboard', () => {
  it('dismisses the active native keyboard', () => {
    const dismiss = vi.fn();

    dismissKeyboard(dismiss);

    expect(dismiss).toHaveBeenCalledOnce();
  });
});

describe('shouldDismissKeyboardForTouch', () => {
  it('keeps the keyboard open when the focused input receives the touch', () => {
    const focusedInput = {};

    expect(shouldDismissKeyboardForTouch('42', focusedInput, 42)).toBe(false);
  });

  it('dismisses the keyboard when another view receives the touch', () => {
    expect(shouldDismissKeyboardForTouch({}, {})).toBe(true);
  });
});
