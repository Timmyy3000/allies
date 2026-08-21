import { describe, expect, it } from 'vitest';

import {
  bytesToBase64Url,
  parseNativeAuthReturn,
  toBase64Url,
} from './pkce';

describe('native Google PKCE helpers', () => {
  it('converts standard base64 into unpadded base64url', () => {
    expect(toBase64Url('a+b/c==')).toBe('a-b_c');
  });

  it('encodes bytes without introducing unsafe URL characters', () => {
    expect(bytesToBase64Url(new Uint8Array([0xfb, 0xff, 0xef]))).toBe('-__v');
  });

  it('accepts a successful return only when state matches', () => {
    expect(
      parseNativeAuthReturn('https://mobile.example/auth/return?code=cloud-code&state=state-example', 'state-example'),
    ).toEqual({ status: 'success', code: 'cloud-code' });
  });

  it('discards a return with a mismatched state before consuming its code', () => {
    expect(
      parseNativeAuthReturn('https://mobile.example/auth/return?code=cloud-code&state=wrong-state', 'state-example'),
    ).toEqual({ status: 'error', reason: 'state-mismatch' });
  });

  it('treats provider cancellation as a normal retryable outcome', () => {
    expect(
      parseNativeAuthReturn('https://mobile.example/auth/return?error=access_denied&state=state-example', 'state-example'),
    ).toEqual({ status: 'canceled' });
  });

  it('does not expose provider error details to the UI', () => {
    expect(
      parseNativeAuthReturn('https://mobile.example/auth/return?error=provider_secret&state=state-example', 'state-example'),
    ).toEqual({ status: 'error', reason: 'flow-failed' });
  });
});
