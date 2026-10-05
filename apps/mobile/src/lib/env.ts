import { parsePublicCloudUrl } from '@allies/cloud-client';

export type NativeAuthCompletionMode = 'redirect' | 'manual_code';

export interface MobileEnvironment {
  cloudApiUrl: string;
  nativeAuthRedirectUri: string | null;
  nativeAuthCompletionMode: NativeAuthCompletionMode;
}

function parseNativeAuthRedirectUri(value: unknown): string | null {
  if (value === undefined || value === null || value === '') return null;
  if (typeof value !== 'string') throw new Error('Native auth redirect URI must be a string');

  const url = new URL(value);
  if (
    url.protocol !== 'https:' ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    value.includes('*')
  ) {
    throw new Error('Native auth redirect URI must be an exact HTTPS URL without query or fragment');
  }

  return value;
}

function parseNativeAuthCompletionMode(value: unknown): NativeAuthCompletionMode {
  if (value === undefined || value === null || (typeof value === 'string' && value.trim() === '')) {
    return 'redirect';
  }
  if (value === 'redirect' || value === 'manual_code') return value;
  throw new Error('Native auth completion mode must be redirect or manual_code');
}

export function parseMobileEnvironment(
  value: unknown,
  nativeAuthRedirectUri?: unknown,
  nativeAuthCompletionMode?: unknown,
): Readonly<MobileEnvironment> {
  return Object.freeze({
    cloudApiUrl: value === undefined ? 'https://cloud.invalid' : parsePublicCloudUrl(value),
    nativeAuthRedirectUri: parseNativeAuthRedirectUri(nativeAuthRedirectUri),
    nativeAuthCompletionMode: parseNativeAuthCompletionMode(nativeAuthCompletionMode),
  });
}

export function getMobileEnvironment(): Readonly<MobileEnvironment> {
  return parseMobileEnvironment(
    process.env.EXPO_PUBLIC_CLOUD_API_URL,
    process.env.EXPO_PUBLIC_NATIVE_AUTH_REDIRECT_URI,
    process.env.EXPO_PUBLIC_NATIVE_AUTH_COMPLETION_MODE,
  );
}
