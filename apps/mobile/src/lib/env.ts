import { parsePublicCloudUrl } from '@allies/cloud-client';

export interface MobileEnvironment {
  cloudApiUrl: string;
}

export function parseMobileEnvironment(value: unknown): Readonly<MobileEnvironment> {
  return Object.freeze({ cloudApiUrl: parsePublicCloudUrl(value) });
}

export function getMobileEnvironment(): Readonly<MobileEnvironment> {
  return parseMobileEnvironment(process.env.EXPO_PUBLIC_CLOUD_API_URL);
}
