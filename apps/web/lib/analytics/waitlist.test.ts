import { beforeEach, describe, expect, it, vi } from "vitest";

const posthogMock = vi.hoisted(() => ({
  capture: vi.fn(),
  identify: vi.fn(),
  init: vi.fn(),
}));

vi.mock("posthog-js", () => ({ default: posthogMock }));

import {
  captureWaitlistEvent,
  identifyWaitlistSubscriber,
  initializeWaitlistAnalytics,
  parsePostHogConfig,
} from "./waitlist";

describe("waitlist analytics", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllEnvs();
  });

  it("accepts only configured PostHog Cloud ingestion hosts", () => {
    expect(parsePostHogConfig(" project-token ", "https://us.i.posthog.com")).toEqual({
      host: "https://us.i.posthog.com",
      token: "project-token",
    });
    expect(parsePostHogConfig("project-token", "http://us.i.posthog.com")).toBeNull();
    expect(parsePostHogConfig("project-token", "https://analytics.example.com")).toBeNull();
    expect(parsePostHogConfig("", "https://us.i.posthog.com")).toBeNull();
  });

  it("initializes privacy-minimized pageview and click tracking", () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN", "project-token");
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_HOST", "https://us.i.posthog.com");

    initializeWaitlistAnalytics();

    expect(posthogMock.init).toHaveBeenCalledWith(
      "project-token",
      expect.objectContaining({
        api_host: "https://us.i.posthog.com",
        autocapture: { dom_event_allowlist: ["click"] },
        capture_pageview: "history_change",
        disable_session_recording: true,
        mask_all_text: true,
        persistence: "memory",
      }),
    );
  });

  it("is a safe no-op without valid configuration", () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN", "project-token");
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_HOST", "https://analytics.example.com");

    initializeWaitlistAnalytics();
    captureWaitlistEvent("waitlist_onboarding_started", { presentation: "route" });
    identifyWaitlistSubscriber("attempt-id", "person@example.com");

    expect(posthogMock.init).not.toHaveBeenCalled();
    expect(posthogMock.capture).not.toHaveBeenCalled();
    expect(posthogMock.identify).not.toHaveBeenCalled();
  });

  it("keeps SDK failures outside the waitlist flow", () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN", "project-token");
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_HOST", "https://us.i.posthog.com");
    posthogMock.init.mockImplementationOnce(() => {
      throw new Error("blocked");
    });
    posthogMock.capture.mockImplementationOnce(() => {
      throw new Error("blocked");
    });
    posthogMock.identify.mockImplementationOnce(() => {
      throw new Error("blocked");
    });

    expect(() => initializeWaitlistAnalytics()).not.toThrow();
    expect(() =>
      captureWaitlistEvent("waitlist_onboarding_step_viewed", {
        presentation: "drawer",
        step: "name",
      }),
    ).not.toThrow();
    expect(() => identifyWaitlistSubscriber("attempt-id", "person@example.com")).not.toThrow();
  });

  it("captures typed events and keeps email out of completion properties", () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN", "project-token");
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_HOST", "https://eu.i.posthog.com");

    captureWaitlistEvent("waitlist_follow_clicked", { source: "completion" });
    identifyWaitlistSubscriber("attempt-id", "person@example.com");
    captureWaitlistEvent("waitlist_joined");

    expect(posthogMock.capture).toHaveBeenNthCalledWith(1, "waitlist_follow_clicked", {
      source: "completion",
    });
    expect(posthogMock.identify).toHaveBeenCalledWith("attempt-id", {
      email: "person@example.com",
    });
    expect(posthogMock.capture).toHaveBeenNthCalledWith(2, "waitlist_joined", undefined);
  });
});
