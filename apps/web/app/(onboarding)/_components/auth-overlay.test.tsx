// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sessionMock = vi.hoisted(() => ({ useSession: vi.fn() }));
vi.mock("../../../lib/session/session-context", () => sessionMock);
vi.mock("next/image", () => ({
  default: ({ alt }: { alt: string }) => <span>{alt}</span>,
}));
vi.mock("./persistent-ally", () => ({
  AUTH_SIGNUP_ALLY_LAYOUT_ID: "auth-signup-ally",
  PersistentAllyAvatar: () => <div data-testid="ally" />,
}));

import { AuthOverlay } from "./auth-overlay";
import { ONBOARDING_GOOGLE_RETURN_TO } from "../_store/onboarding-resume";

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
  sessionMock.useSession.mockReset();
});

describe("AuthOverlay Google sign-in", () => {
  it("starts Cloud Google sign-in and keeps the ally draft hook in front", async () => {
    const beginSignIn = vi.fn(async () => "https://accounts.google.com/auth");
    const runCloudOperation = vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>) => operation());
    const assign = vi.fn();
    const onPrepareGoogleSignIn = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { assign },
    });
    sessionMock.useSession.mockReturnValue({
      client: { beginSignIn },
      runCloudOperation,
    });

    render(
      <AuthOverlay
        shape="ghosty"
        color="#3446e9"
        onClose={() => undefined}
        onSignUp={() => undefined}
        onPrepareGoogleSignIn={onPrepareGoogleSignIn}
      />,
    );

    fireEvent.click(screen.getByTestId("signup-google"));
    fireEvent.click(screen.getByTestId("signup-google"));

    await waitFor(() => expect(runCloudOperation).toHaveBeenCalledOnce());
    expect(onPrepareGoogleSignIn).toHaveBeenCalledOnce();
    expect(beginSignIn).toHaveBeenCalledWith(ONBOARDING_GOOGLE_RETURN_TO, undefined);
    expect(assign).toHaveBeenCalledWith("https://accounts.google.com/auth");
    expect((screen.getByTestId("signup-google") as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows recovery copy when Google sign-in cannot start", async () => {
    const beginSignIn = vi.fn(async () => {
      throw { kind: "not-found", code: "provider_unavailable" };
    });
    const runCloudOperation = vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>) => operation());
    sessionMock.useSession.mockReturnValue({
      client: { beginSignIn },
      runCloudOperation,
    });

    render(
      <AuthOverlay
        shape="ghosty"
        color="#3446e9"
        onClose={() => undefined}
        onSignUp={() => undefined}
        onPrepareGoogleSignIn={() => undefined}
      />,
    );

    fireEvent.click(screen.getByTestId("signup-google"));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Google sign-in is temporarily unavailable. Try again.",
    );
    expect((screen.getByTestId("signup-google") as HTMLButtonElement).disabled).toBe(false);
  });
});
