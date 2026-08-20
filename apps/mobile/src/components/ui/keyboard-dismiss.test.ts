// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';

import { dismissKeyboard } from './keyboard-dismiss';

describe('dismissKeyboard', () => {
  it('dismisses the active native keyboard', () => {
    const dismiss = vi.fn();

    dismissKeyboard(dismiss);

    expect(dismiss).toHaveBeenCalledOnce();
  });
});
