import { parsePublicCloudUrl } from '@allies/cloud-client';

export interface MobileEnvironment {
  cloudApiUrl: string;
  nativeAuthRedirectUri: string | null;
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

export function parseMobileEnvironment(
  value: unknown,
  nativeAuthRedirectUri?: unknown,
): Readonly<MobileEnvironment> {
  return Object.freeze({
    cloudApiUrl: value === undefined ? 'https://cloud.invalid' : parsePublicCloudUrl(value),
    nativeAuthRedirectUri: parseNativeAuthRedirectUri(nativeAuthRedirectUri),
  });
}

export function getMobileEnvironment(): Readonly<MobileEnvironment> {
  return parseMobileEnvironment(
    process.env.EXPO_PUBLIC_CLOUD_API_URL,
    process.env.EXPO_PUBLIC_NATIVE_AUTH_REDIRECT_URI,
  );
}
