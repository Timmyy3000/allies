// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sessionMock = vi.hoisted(() => ({ useSession: vi.fn() }));
vi.mock("../../lib/session/session-context", () => sessionMock);

import { SignInClient } from "./sign-in-client";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  sessionMock.useSession.mockReset();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
});

describe("SignInClient", () => {
  it("offers Google as the only provider and blocks duplicate starts", async () => {
    const beginSignIn = vi.fn(
      () => new Promise<string>(() => undefined),
    );
    const runCloudOperation = vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>) => operation());
    sessionMock.useSession.mockReturnValue({
      client: { beginSignIn },
      runCloudOperation,
    });

    render(<SignInClient returnTo="/account" />);

    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /password|apple|microsoft/i })).toBeNull();

    const button = screen.getByRole("button", { name: "Continue with Google" });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(runCloudOperation).toHaveBeenCalledOnce());
    expect(beginSignIn).toHaveBeenCalledOnce();
    expect(beginSignIn).toHaveBeenCalledWith("/account", undefined);
    expect((button as HTMLButtonElement).disabled).toBe(true);

  });

  it("maps provider failures to safe recovery copy", async () => {
    const beginSignIn = vi.fn(async () => {
      throw { kind: "not-found", code: "provider_unavailable" };
    });
    const runCloudOperation = vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>) => operation());
    sessionMock.useSession.mockReturnValue({
      client: { beginSignIn },
      runCloudOperation,
    });

    render(<SignInClient returnTo="/account" />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Google sign-in is temporarily unavailable. Try again.");
    expect((screen.getByRole("button", { name: "Continue with Google" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText("Google sign-in is temporarily unavailable. Try again.").textContent)
      .not.toContain("provider_unavailable");
  });
});
