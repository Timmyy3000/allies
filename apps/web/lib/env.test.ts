import { describe, expect, it } from "vitest";

import { parseWebEnvironment } from "./env";

describe("web environment", () => {
  it("defaults waitlist enablement off and consent empty", () => {
    const environment = parseWebEnvironment("https://cloud.example.com", {
      waitlistEnabled: undefined,
      waitlistConsentVersion: undefined,
    });

    expect(environment.waitlistEnabled).toBe(false);
    expect(environment.waitlistConsentVersion).toBeNull();
  });

  it("accepts explicit waitlist enablement and trims consent", () => {
    const environment = parseWebEnvironment("https://cloud.example.com", {
      waitlistEnabled: "true",
      waitlistConsentVersion: "  waitlist-v1  ",
    });

    expect(environment.waitlistEnabled).toBe(true);
    expect(environment.waitlistConsentVersion).toBe("waitlist-v1");
  });

  it("keeps the static story renderable without a Cloud URL when disabled", () => {
    const environment = parseWebEnvironment(undefined, {
      waitlistEnabled: false,
      waitlistConsentVersion: undefined,
    });

    expect(environment.cloudApiUrl).toBeNull();
    expect(environment.waitlistEnabled).toBe(false);
  });

  it("requires a valid Cloud URL when the waitlist is enabled", () => {
    expect(() =>
      parseWebEnvironment(undefined, {
        waitlistEnabled: true,
        waitlistConsentVersion: "waitlist-v1",
      }),
    ).toThrow();
  });
});
