import { describe, expect, it, vi } from 'vitest';

import {
  deliverNativeAuthReturn,
  registerNativeAuthReturnListener,
} from './native-auth-return';

describe('native auth return broker', () => {
  it('delivers an app-link return only while a flow is active', () => {
    const listener = vi.fn();
    const dispose = registerNativeAuthReturnListener(listener);

    expect(deliverNativeAuthReturn('https://mobile.example/auth/return?state=state')).toBe(true);
    expect(listener).toHaveBeenCalledWith('https://mobile.example/auth/return?state=state');

    dispose();
    expect(deliverNativeAuthReturn('https://mobile.example/auth/return?state=late')).toBe(false);
  });
});
