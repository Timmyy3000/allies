import { parsePublicCloudUrl } from "@allies/cloud-client";

export interface WebEnvironment {
  cloudApiUrl: string | null;
  waitlistEnabled: boolean;
  waitlistConsentVersion: string | null;
}

export interface WebEnvironmentOptions {
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
  const waitlistEnabled = parseBoolean(waitlistEnabledValue);
  let cloudApiUrl: string | null = null;
  if (waitlistEnabled) {
    cloudApiUrl = parsePublicCloudUrl(value);
  } else if (value !== undefined && value !== null && value !== "") {
    try {
      cloudApiUrl = parsePublicCloudUrl(value);
    } catch {
      // The static story must remain renderable while the waitlist is off.
    }
  }

  return Object.freeze({
    cloudApiUrl,
    waitlistEnabled,
    waitlistConsentVersion: parseOptionalString(consentVersionValue),
  });
}

export function getWebEnvironment(): Readonly<WebEnvironment> {
  return parseWebEnvironment(process.env.NEXT_PUBLIC_CLOUD_API_URL);
}
