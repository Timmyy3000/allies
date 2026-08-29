// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("./(onboarding)/_components", () => ({ default: () => null }));
vi.mock("./(onboarding)/_store/onboarding-store", () => ({
  OnboardingStateProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("../lib/env", () => ({
  getWebEnvironment: () => ({ waitlistEnabled: false, waitlistConsentVersion: null }),
}));
vi.mock("../lib/waitlist/flow", () => ({
  WaitlistFlowProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import Home from "./page";

describe("public homepage sign-in entry", () => {
  it("returns Google sign-in to the authenticated Home surface", () => {
    render(<Home />);

    expect(screen.getByRole("link", { name: "Continue with Google" }).getAttribute("href"))
      .toBe("/sign-in?returnTo=%2Fhome");
  });
});
