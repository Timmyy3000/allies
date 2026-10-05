// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
vi.mock("../lib/allies/onboarding-handoff-screen", () => ({
  OnboardingHandoffScreen: () => <div data-testid="onboarding-handoff" />,
}));

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
  it("does not restore an unconfirmed logout and offers a server retry", async () => {
    const { restore } = setupSession("unknown");
    const logout = vi.fn(async () => ({ serverConfirmed: true }));
    sessionMock.useSession.mockReturnValue({ state: { status: "unknown" }, restore, logout });
    searchParamsMock.get.mockImplementation((key) => key === "signout" ? "unconfirmed" : null);
    render(<HomePageClient />);
    expect(screen.getByRole("alert").textContent).toContain("may still be signed in");
    expect(restore).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry sign out" }));
    await waitFor(() => expect(routerMock.replace).toHaveBeenCalledWith("/"));
  });
  it("shows onboarding to a signed-out visitor", () => {
    setupSession("signed-out");

    render(<HomePageClient />);

    expect(screen.getByTestId("public-onboarding")).toBeTruthy();
  });

  it("sends a signed-in visitor from the base route to Home", async () => {
    setupSession("signed-in");

    render(<HomePageClient />);

    expect(screen.getByRole("status", { name: "Opening your home…" })).toBeTruthy();
    await waitFor(() => expect(routerMock.replace).toHaveBeenCalledWith("/home"));
    expect(screen.queryByTestId("public-onboarding")).toBeNull();
  });

  it("finishes the saved Ally before redirecting a signed-in Google return", () => {
    window.sessionStorage.setItem(ONBOARDING_RESUME_PENDING_KEY, ONBOARDING_RESUME_PENDING_VALUE);
    setupSession("signed-in");

    render(<HomePageClient />);

    expect(screen.getByTestId("onboarding-handoff")).toBeTruthy();
    expect(screen.queryByTestId("public-onboarding")).toBeNull();
    expect(routerMock.replace).not.toHaveBeenCalled();
    act(() => {
      window.sessionStorage.clear();
      window.dispatchEvent(new StorageEvent("storage"));
    });
    expect(routerMock.replace).not.toHaveBeenCalled();
  });
});
