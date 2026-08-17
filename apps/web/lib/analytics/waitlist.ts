import posthog from "posthog-js";

const POSTHOG_CLOUD_HOSTS = new Set([
  "https://eu.i.posthog.com",
  "https://us.i.posthog.com",
]);

type WaitlistPresentation = "drawer" | "route";
type WaitlistStep = "name" | "look" | "job" | "personality" | "preview";

type WaitlistEvents = {
  waitlist_ally_created: undefined;
  waitlist_follow_clicked: { source: "completion" | "landing" };
  waitlist_joined: undefined;
  waitlist_onboarding_started: { presentation: WaitlistPresentation };
  waitlist_onboarding_step_viewed: {
    presentation: WaitlistPresentation;
    step: WaitlistStep;
  };
};

export function parsePostHogConfig(
  tokenValue: unknown,
  hostValue: unknown,
): Readonly<{ host: string; token: string }> | null {
  if (typeof tokenValue !== "string" || typeof hostValue !== "string") return null;
  const token = tokenValue.trim();
  if (!token) return null;

  try {
    const url = new URL(hostValue);
    if (url.href !== `${url.origin}/` || !POSTHOG_CLOUD_HOSTS.has(url.origin)) return null;
    return Object.freeze({ host: url.origin, token });
  } catch {
    return null;
  }
}

function getPostHogConfig() {
  return parsePostHogConfig(
    process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN,
    process.env.NEXT_PUBLIC_POSTHOG_HOST,
  );
}

export function initializeWaitlistAnalytics(): void {
  const config = getPostHogConfig();
  if (!config) return;

  try {
    posthog.init(config.token, {
      api_host: config.host,
      autocapture: { dom_event_allowlist: ["click"] },
      capture_pageleave: true,
      capture_pageview: "history_change",
      defaults: "2026-05-30",
      disable_session_recording: true,
      mask_all_text: true,
      persistence: "memory",
      person_profiles: "identified_only",
    });
  } catch {
    return;
  }
}

export function captureWaitlistEvent<Event extends keyof WaitlistEvents>(
  event: Event,
  ...properties: WaitlistEvents[Event] extends undefined
    ? []
    : [properties: WaitlistEvents[Event]]
): void {
  if (!getPostHogConfig()) return;

  try {
    posthog.capture(event, properties[0]);
  } catch {
    return;
  }
}

export function identifyWaitlistSubscriber(
  waitlistAttemptId: string,
  email: string,
): void {
  if (!getPostHogConfig()) return;

  try {
    posthog.identify(waitlistAttemptId, { email });
  } catch {
    return;
  }
}
