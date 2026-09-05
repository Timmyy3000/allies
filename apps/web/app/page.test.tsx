// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ONBOARDING_RESUME_PENDING_KEY,
  ONBOARDING_RESUME_PENDING_VALUE,
} from "./(onboarding)/_store/onboarding-resume";

const routerMock = vi.hoisted(() => ({ replace: vi.fn() }));
const sessionMock = vi.hoisted(() => ({ useSession: vi.fn() }));
const searchParamsMock = vi.hoisted(() => ({
  get: vi.fn((_: string): string | null => null),
}));

vi.mock("./(onboarding)/_components", () => ({
  default: ({ resumeAfterAuth }: { resumeAfterAuth?: boolean }) => (
    <div data-testid="public-onboarding" data-resume={resumeAfterAuth ? "true" : "false"} />
  ),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
  useSearchParams: () => searchParamsMock,
}));
vi.mock("./(onboarding)/_store/onboarding-store", () => ({
  OnboardingStateProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("../lib/env", () => ({
  getWebEnvironment: () => ({ waitlistEnabled: false, waitlistConsentVersion: null }),
}));
vi.mock("../lib/waitlist/flow", () => ({
  WaitlistFlowProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("../lib/session/session-context", () => sessionMock);

import { HomePageClient } from "./home-page-client";

function setupSession(status: "unknown" | "signed-in" | "signed-out") {
  const restore = vi.fn(async () => undefined);
  sessionMock.useSession.mockReturnValue({
    state: { status },
    restore,
  });
  return { restore };
}

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.clearAllMocks();
});

beforeEach(() => {
  window.sessionStorage.clear();
  routerMock.replace.mockReset();
  searchParamsMock.get.mockReturnValue(null);
});

describe("public homepage sign-in entry", () => {
  it("returns Google sign-in to the authenticated Home surface", () => {
    setupSession("signed-out");

    render(<HomePageClient />);

    expect(screen.getByRole("link", { name: "Continue with Google" }).getAttribute("href"))
      .toBe("/sign-in?returnTo=%2Fhome");
  });

  it("sends a signed-in visitor from the base route to Home", async () => {
    setupSession("signed-in");

    render(<HomePageClient />);

    expect(screen.getByRole("status").textContent).toContain("Opening your home");
    await waitFor(() => expect(routerMock.replace).toHaveBeenCalledWith("/home"));
    expect(screen.queryByTestId("public-onboarding")).toBeNull();
  });

  it("keeps a signed-in Google return on the landing overlay", () => {
    window.sessionStorage.setItem(ONBOARDING_RESUME_PENDING_KEY, ONBOARDING_RESUME_PENDING_VALUE);
    setupSession("signed-in");

    render(<HomePageClient />);

    expect(screen.getByTestId("public-onboarding").getAttribute("data-resume")).toBe("true");
    expect(routerMock.replace).not.toHaveBeenCalled();
  });
});
