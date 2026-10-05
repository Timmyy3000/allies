import { describe, expect, it } from 'vitest';

import { parseMobileEnvironment } from './env';

describe('parseMobileEnvironment', () => {
  it('keeps the Cloud origin and exact native return URL separate', () => {
    expect(
      parseMobileEnvironment('https://cloud.example.com', 'https://mobile.example/auth/return'),
    ).toEqual({
      cloudApiUrl: 'https://cloud.example.com',
      nativeAuthRedirectUri: 'https://mobile.example/auth/return',
      nativeAuthCompletionMode: 'redirect',
    });
  });

  it('opts into the temporary manual browser completion mode', () => {
    expect(
      parseMobileEnvironment('https://cloud.example.com', undefined, 'manual_code'),
    ).toMatchObject({ nativeAuthCompletionMode: 'manual_code' });
  });

  it('defaults blank completion mode to redirect and rejects unknown values', () => {
    expect(parseMobileEnvironment('https://cloud.example.com', undefined, ''))
      .toMatchObject({ nativeAuthCompletionMode: 'redirect' });
    expect(() => parseMobileEnvironment('https://cloud.example.com', undefined, 'device_code')).toThrow();
  });

  it('fails closed for unsafe native return URLs', () => {
    expect(() => parseMobileEnvironment('https://cloud.example.com', 'http://mobile.example/auth/return')).toThrow();
    expect(() => parseMobileEnvironment('https://cloud.example.com', 'https://mobile.example/auth/return?state=unsafe')).toThrow();
  });

  it('allows local onboarding to run without auth configuration', () => {
    expect(parseMobileEnvironment(undefined, undefined)).toEqual({
      cloudApiUrl: 'https://cloud.invalid',
      nativeAuthRedirectUri: null,
      nativeAuthCompletionMode: 'redirect',
    });
  });
});
