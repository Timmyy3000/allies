import { parsePublicCloudUrl } from "@allies/cloud-client";

export interface WebEnvironment {
  cloudApiUrl: string | null;
  siteUrl: string | null;
  waitlistEnabled: boolean;
  waitlistConsentVersion: string | null;
}

export interface WebEnvironmentOptions {
  siteUrl?: unknown;
  waitlistEnabled?: unknown;
  waitlistConsentVersion?: unknown;
}

function parseBoolean(value: unknown): boolean {
  return value === true || value === "true";
}

function parseOptionalString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function parseWebEnvironment(
  value: unknown,
  options: WebEnvironmentOptions = {},
): Readonly<WebEnvironment> {
  const waitlistEnabledValue = Object.prototype.hasOwnProperty.call(options, "waitlistEnabled")
    ? options.waitlistEnabled
    : process.env.NEXT_PUBLIC_WAITLIST_ENABLED;
  const consentVersionValue = Object.prototype.hasOwnProperty.call(options, "waitlistConsentVersion")
    ? options.waitlistConsentVersion
    : process.env.NEXT_PUBLIC_WAITLIST_CONSENT_VERSION;
  const siteUrlValue = Object.prototype.hasOwnProperty.call(options, "siteUrl")
    ? options.siteUrl
    : process.env.NEXT_PUBLIC_SITE_URL;
  const waitlistEnabled = parseBoolean(waitlistEnabledValue);
  let cloudApiUrl: string | null = null;
  let siteUrl: string | null = null;
  if (waitlistEnabled) {
    cloudApiUrl = parsePublicCloudUrl(value);
  } else if (value !== undefined && value !== null && value !== "") {
    try {
      cloudApiUrl = parsePublicCloudUrl(value);
    } catch {
      // The static story must remain renderable while the waitlist is off.
    }
  }
  if (siteUrlValue !== undefined && siteUrlValue !== null && siteUrlValue !== "") {
    siteUrl = parsePublicCloudUrl(siteUrlValue);
  }

  return Object.freeze({
    cloudApiUrl,
    siteUrl,
    waitlistEnabled,
    waitlistConsentVersion: parseOptionalString(consentVersionValue),
  });
}

export function getWebEnvironment(): Readonly<WebEnvironment> {
  return parseWebEnvironment(process.env.NEXT_PUBLIC_CLOUD_API_URL);
}

export function getActivitySseEnabled(): boolean {
  return process.env.NEXT_PUBLIC_ACTIVITY_SSE_ENABLED === "true";
}

export function getCreationWakeEnabled(): boolean {
  return process.env.NEXT_PUBLIC_CREATION_WAKE_ENABLED === "true";
}
