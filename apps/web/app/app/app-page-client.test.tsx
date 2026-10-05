// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sessionMock = vi.hoisted(() => ({ useSession: vi.fn() }));
const routerMock = vi.hoisted(() => ({ replace: vi.fn() }));
const searchParamsMock = vi.hoisted(() => ({
  get: vi.fn((_: string): string | null => null),
}));

vi.mock("../../lib/session/session-context", () => sessionMock);
vi.mock("../../lib/allies/onboarding-handoff-screen", () => ({
  OnboardingHandoffScreen: () => <div data-testid="onboarding-handoff" />,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
  useSearchParams: () => searchParamsMock,
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));
vi.mock("next/image", () => ({
  default: ({ priority, ...props }: Record<string, unknown>) => {
    void priority;
    return createElement("img", { ...props, alt: props.alt ?? "" });
  },
}));

import { metadata } from "./page";
import { AppPageClient } from "./app-page-client";

type SessionStatus = "unknown" | "restoring" | "signed-in" | "signed-out" | "unavailable";

function setupSession(status: SessionStatus, overrides: Record<string, unknown> = {}) {
  const restore = vi.fn(async () => undefined);
  const beginSignIn = vi.fn(() => new Promise<string>(() => undefined));
  const runCloudOperation = vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>) => operation());
  const session = {
    state: { status },
    restore,
    client: { beginSignIn },
    runCloudOperation,
    ...overrides,
  };
  sessionMock.useSession.mockReturnValue(session);
  return { beginSignIn, restore, runCloudOperation, session };
}

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.clearAllMocks();
});

beforeEach(() => {
  window.sessionStorage.clear();
  sessionMock.useSession.mockReset();
  routerMock.replace.mockReset();
  searchParamsMock.get.mockReturnValue(null);
});

describe("AppPageClient", () => {
  it("waits during session restoration and starts restore once", async () => {
    const { restore } = setupSession("unknown");

    render(<AppPageClient />);

    expect(screen.getByRole("status").textContent).toContain("Checking your secure session");
    await waitFor(() => expect(restore).toHaveBeenCalledOnce());
    expect(screen.queryByRole("link", { name: "Make your first ally" })).toBeNull();
  });

  it("shows a retryable error when restoration is unavailable", () => {
    const { restore } = setupSession("unavailable");

    render(<AppPageClient />);

    expect(screen.getByRole("status").textContent).toContain("couldn't reach your Allies");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(restore).toHaveBeenCalledOnce();
  });

  it("shows a retryable error when restoration rejects", async () => {
    const restore = vi.fn(async () => {
      throw new Error("offline");
    });
    setupSession("unknown", { restore });

    render(<AppPageClient />);

    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("couldn't reach your Allies"));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(restore).toHaveBeenCalledTimes(2);
  });

  it("shows the welcome actions to a signed-out visitor", () => {
    setupSession("signed-out");

    render(<AppPageClient />);

    expect(screen.getByRole("link", { name: "Make your first ally" }).getAttribute("href")).toBe("/onboarding");
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeTruthy();
  });

  it("shows unconfirmed sign-out recovery without restoring private session content", () => {
    searchParamsMock.get.mockImplementation((key) => key === "signout" ? "unconfirmed" : null);
    const { restore } = setupSession("unknown");

    render(<AppPageClient />);

    expect(screen.getByRole("heading", { name: "Let’s finish signing you out" })).toBeTruthy();
    expect(restore).not.toHaveBeenCalled();
  });

  it("starts CSRF-protected Google sign-in and blocks duplicate starts", async () => {
    const { beginSignIn, runCloudOperation } = setupSession("signed-out");

    render(<AppPageClient />);

    const button = screen.getByRole("button", { name: "Continue with Google" });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(runCloudOperation).toHaveBeenCalledOnce());
    expect(beginSignIn).toHaveBeenCalledOnce();
    expect(beginSignIn).toHaveBeenCalledWith("/home", undefined);
  });

  it("lets the visitor retry Google sign-in after a failed handoff", async () => {
    const runCloudOperation = vi.fn().mockRejectedValue(new Error("network unavailable"));
    setupSession("signed-out", { runCloudOperation });
    render(<AppPageClient />);

    const button = screen.getByRole("button", { name: "Continue with Google" });
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect((button as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(runCloudOperation).toHaveBeenCalledTimes(2));
  });

  it("routes an ordinary signed-in visitor to Home without welcome content", async () => {
    setupSession("signed-in");

    render(<AppPageClient />);

    expect(screen.getByRole("status").textContent).toContain("Opening your home");
    await waitFor(() => expect(routerMock.replace).toHaveBeenCalledWith("/home"));
    expect(screen.queryByRole("link", { name: "Make your first ally" })).toBeNull();
  });

  it("keeps a pending onboarding resume on the handoff screen", () => {
    window.sessionStorage.setItem("allies.onboarding.resume.pending", "welcome");
    setupSession("signed-in");

    render(<AppPageClient />);

    expect(screen.getByTestId("onboarding-handoff")).toBeTruthy();
    expect(routerMock.replace).not.toHaveBeenCalled();
  });

  it("honors an explicit onboarding resume query for signed-in returns", () => {
    searchParamsMock.get.mockImplementation((key) => key === "resume" ? "welcome" : null);
    setupSession("signed-in");

    render(<AppPageClient />);

    expect(screen.getByTestId("onboarding-handoff")).toBeTruthy();
    expect(routerMock.replace).not.toHaveBeenCalled();
  });
});

describe("/app metadata", () => {
  it("overrides the root canonical route", () => {
    expect(metadata.alternates?.canonical).toBe("/app");
    expect(metadata.title).toEqual({ absolute: "Allies" });
    expect(metadata.openGraph?.url).toBe("/app");
  });
});
