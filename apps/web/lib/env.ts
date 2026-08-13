import { parsePublicCloudUrl } from "@allies/cloud-client";

export interface WebEnvironment {
  cloudApiUrl: string;
}

export function parseWebEnvironment(value: unknown): Readonly<WebEnvironment> {
  return Object.freeze({ cloudApiUrl: parsePublicCloudUrl(value) });
}

export function getWebEnvironment(): Readonly<WebEnvironment> {
  return parseWebEnvironment(process.env.NEXT_PUBLIC_CLOUD_API_URL);
}
