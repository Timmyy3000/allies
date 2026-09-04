// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sessionMock = vi.hoisted(() => ({ useSession: vi.fn() }));
const navigationMock = vi.hoisted(() => ({
  useRouter: vi.fn(),
}));
vi.mock("../../../lib/session/session-context", () => sessionMock);
vi.mock("next/navigation", () => navigationMock);
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

import { AuthReturnClient } from "./auth-return-client";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  sessionMock.useSession.mockReset();
  navigationMock.useRouter.mockReturnValue({ replace: vi.fn() });
});

describe("AuthReturnClient", () => {
  it("restores once and does not flash signed-out controls while pending", async () => {
    const restore = vi.fn(async () => undefined);
    sessionMock.useSession.mockReturnValue({ state: { status: "unknown" }, restore });

    const { rerender } = render(<AuthReturnClient returnTo="/account" />);

    expect(screen.getByRole("status").textContent).toContain("Restoring your session");
    expect(screen.queryByRole("link", { name: /sign in/i })).toBeNull();
    await waitFor(() => expect(restore).toHaveBeenCalledOnce());

    sessionMock.useSession.mockReturnValue({ state: { status: "signed-out" }, restore });
    rerender(<AuthReturnClient returnTo="/account" />);
    expect(screen.getByRole("link", { name: "Sign in again" }).getAttribute("href"))
      .toBe("/sign-in?returnTo=%2Faccount");
  });

  it("replaces only with the server-selected safe return path", async () => {
    const replace = vi.fn();
    const restore = vi.fn(async () => undefined);
    navigationMock.useRouter.mockReturnValue({ replace });
    sessionMock.useSession.mockReturnValue({ state: { status: "signed-in" }, restore });

    render(<AuthReturnClient returnTo="/workspace?view=home#top" />);

    await waitFor(() => expect(restore).toHaveBeenCalledOnce());
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/workspace?view=home#top"));
  });

  it("maps callback error categories without rendering raw query text", () => {
    const restore = vi.fn(async () => undefined);
    sessionMock.useSession.mockReturnValue({ state: { status: "signed-out" }, restore });

    render(<AuthReturnClient returnTo="/account" errorCode="access_denied" />);

    expect(screen.getByRole("alert").textContent).toBe("Google sign-in was cancelled.");
    expect(screen.queryByText("access_denied")).toBeNull();
  });
});
