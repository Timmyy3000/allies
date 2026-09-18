import { describe, expect, it, vi } from "vitest";

import {
  getActivitySseEnabled,
  getCreationWakeEnabled,
  getResponsePresentationMode,
  parseWebEnvironment,
} from "./env";

describe("web environment", () => {
  it("defaults waitlist enablement off and consent empty", () => {
    const environment = parseWebEnvironment("https://cloud.example.com", {
      siteUrl: undefined,
      waitlistEnabled: undefined,
      waitlistConsentVersion: undefined,
    });

    expect(environment.waitlistEnabled).toBe(false);
    expect(environment.siteUrl).toBeNull();
    expect(environment.waitlistConsentVersion).toBeNull();
  });

  it("accepts explicit waitlist enablement and trims consent", () => {
    const environment = parseWebEnvironment("https://cloud.example.com", {
      siteUrl: "http://localhost:3000",
      waitlistEnabled: "true",
      waitlistConsentVersion: "  waitlist-v1  ",
    });

    expect(environment.waitlistEnabled).toBe(true);
    expect(environment.siteUrl).toBe("http://localhost:3000");
    expect(environment.waitlistConsentVersion).toBe("waitlist-v1");
  });

  it("keeps the static story renderable without a Cloud URL when disabled", () => {
    const environment = parseWebEnvironment(undefined, {
      siteUrl: undefined,
      waitlistEnabled: false,
      waitlistConsentVersion: undefined,
    });

    expect(environment.cloudApiUrl).toBeNull();
    expect(environment.waitlistEnabled).toBe(false);
  });

  it("requires a valid Cloud URL when the waitlist is enabled", () => {
    expect(() =>
      parseWebEnvironment(undefined, {
        siteUrl: undefined,
        waitlistEnabled: true,
        waitlistConsentVersion: "waitlist-v1",
      }),
    ).toThrow();
  });

  it("keeps activity SSE opt-in", () => {
    vi.stubEnv("NEXT_PUBLIC_ACTIVITY_SSE_ENABLED", "");
    expect(getActivitySseEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_ACTIVITY_SSE_ENABLED", "true");
    expect(getActivitySseEnabled()).toBe(true);
    vi.stubEnv("NEXT_PUBLIC_ACTIVITY_SSE_ENABLED", "false");
    expect(getActivitySseEnabled()).toBe(false);
    vi.unstubAllEnvs();
  });

  it("defaults response presentation to stream and accepts only aggregate as rollback", () => {
    vi.stubEnv("NEXT_PUBLIC_RESPONSE_PRESENTATION_MODE", "");
    expect(getResponsePresentationMode()).toBe("stream");
    vi.stubEnv("NEXT_PUBLIC_RESPONSE_PRESENTATION_MODE", "aggregate");
    expect(getResponsePresentationMode()).toBe("aggregate");
    vi.stubEnv("NEXT_PUBLIC_RESPONSE_PRESENTATION_MODE", "stream");
    expect(getResponsePresentationMode()).toBe("stream");
    vi.stubEnv("NEXT_PUBLIC_RESPONSE_PRESENTATION_MODE", "AGGREGATE");
    expect(getResponsePresentationMode()).toBe("stream");
    vi.unstubAllEnvs();
  });

  it("keeps creation wake opt-in", () => {
    vi.stubEnv("NEXT_PUBLIC_CREATION_WAKE_ENABLED", "");
    expect(getCreationWakeEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_CREATION_WAKE_ENABLED", "true");
    expect(getCreationWakeEnabled()).toBe(true);
    vi.stubEnv("NEXT_PUBLIC_CREATION_WAKE_ENABLED", "false");
    expect(getCreationWakeEnabled()).toBe(false);
    vi.unstubAllEnvs();
  });
});
