// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sessionMock = vi.hoisted(() => ({ useSession: vi.fn() }));
const routerMock = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("../_components", () => ({
  default: () => <div data-testid="public-onboarding">Public waitlist</div>,
}));
vi.mock("../_store/onboarding-store", () => ({
  OnboardingStateProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("../../../lib/env", () => ({
  getWebEnvironment: () => ({ waitlistEnabled: true, waitlistConsentVersion: "waitlist-v1" }),
}));
vi.mock("../../../lib/session/session-context", () => sessionMock);
vi.mock("../../../lib/waitlist/flow", () => ({
  WaitlistFlowProvider: ({ children }: { children: ReactNode }) => (
    <div data-testid="waitlist-provider">{children}</div>
  ),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
}));

import { OnboardingPageClient } from "./onboarding-page-client";

function setupSession(status: "unknown" | "signed-in" | "signed-out" | "unavailable", restore = vi.fn(async () => undefined)) {
  const session = {
    state: { status },
    restore,
    client: {},
    runCloudOperation: vi.fn(),
    logout: vi.fn(),
  };
  sessionMock.useSession.mockReturnValue(session);
  return { restore, session };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  sessionMock.useSession.mockReset();
  routerMock.replace.mockReset();
});

describe("OnboardingPageClient", () => {
  it("routes an authenticated visitor into the new-Ally flow", async () => {
    setupSession("signed-in");

    render(<OnboardingPageClient />);

    expect(screen.getByRole("status").textContent).toContain("Opening your Ally space");
    await waitFor(() => expect(routerMock.replace).toHaveBeenCalledWith("/home/new"));
    expect(screen.queryByTestId("public-onboarding")).toBeNull();
  });

  it("keeps a signed-out visitor on the public waitlist flow", () => {
    const { restore } = setupSession("signed-out");

    render(<OnboardingPageClient />);

    expect(screen.getByTestId("waitlist-provider")).toBeTruthy();
    expect(screen.getByTestId("public-onboarding")).toBeTruthy();
    expect(restore).not.toHaveBeenCalled();
    expect(routerMock.replace).not.toHaveBeenCalled();
  });

  it("shows a retryable unavailable state when session restoration cannot reach Cloud", () => {
    const { restore } = setupSession("unavailable");

    render(<OnboardingPageClient />);

    expect(screen.getByRole("status").textContent)
      .toContain("We couldn't reach your Allies");
    expect(screen.queryByTestId("waitlist-provider")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(restore).toHaveBeenCalledOnce();
  });

  it("falls back to the public flow when session restoration is unavailable", async () => {
    const restore = vi.fn(async () => {
      throw new Error("session unavailable");
    });
    setupSession("unknown", restore);

    render(<OnboardingPageClient />);

    expect(screen.getByRole("status").textContent).toContain("Checking your secure session");
    await waitFor(() => expect(screen.getByTestId("public-onboarding")).toBeTruthy());
    expect(screen.queryByText("Preparing your Ally space")).toBeNull();
    expect(routerMock.replace).not.toHaveBeenCalled();
  });
});
