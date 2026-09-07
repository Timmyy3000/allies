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

  it('encodes bytes without unsafe URL characters', () => {
    expect(bytesToBase64Url(new Uint8Array([0xfb, 0xff, 0xef]))).toBe('-__v');
  });

  it('accepts a successful return only when state and redirect match', () => {
    expect(parseNativeAuthReturn(
      'https://mobile.example/auth/return?code=cloud-code&state=state-example',
      'state-example',
      'https://mobile.example/auth/return',
    )).toEqual({ status: 'success', code: 'cloud-code' });
  });

  it('rejects a mismatched state or redirect before consuming a code', () => {
    expect(parseNativeAuthReturn(
      'https://mobile.example/auth/return?code=cloud-code&state=wrong-state',
      'state-example',
      'https://mobile.example/auth/return',
    )).toEqual({ status: 'error', reason: 'state-mismatch' });
    expect(parseNativeAuthReturn(
      'https://evil.example/auth/return?code=cloud-code&state=state-example',
      'state-example',
      'https://mobile.example/auth/return',
    )).toEqual({ status: 'error', reason: 'invalid-return' });
  });

  it('treats provider cancellation as a normal retryable outcome', () => {
    expect(parseNativeAuthReturn(
      'https://mobile.example/auth/return?error=access_denied&state=state-example',
      'state-example',
      'https://mobile.example/auth/return',
    )).toEqual({ status: 'canceled' });
  });

  it('rejects duplicate callback parameters without exposing provider details', () => {
    expect(parseNativeAuthReturn(
      'https://mobile.example/auth/return?code=one&code=two&state=state-example',
      'state-example',
      'https://mobile.example/auth/return',
    )).toEqual({ status: 'error', reason: 'invalid-return' });
    expect(parseNativeAuthReturn(
      'https://mobile.example/auth/return?error=provider_secret&state=state-example',
      'state-example',
      'https://mobile.example/auth/return',
    )).toEqual({ status: 'error', reason: 'flow-failed' });
  });
});
