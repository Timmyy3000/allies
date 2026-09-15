// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sessionMock = vi.hoisted(() => ({
  useSession: vi.fn(),
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: sessionMock.replace }),
}));
vi.stubGlobal("scrollTo", vi.fn());
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);
vi.mock("../../lib/session/session-context", () => sessionMock);
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import { ClaimInviteClient } from "./claim-invite-client";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  sessionMock.useSession.mockReset();
});

describe("ClaimInviteClient", () => {
  it("reveals email and claim together while keeping the code editable and making no early request", async () => {
    const claimInvite = vi.fn(async () => undefined);
    sessionMock.useSession.mockReturnValue({
      client: { claimInvite },
      runCloudOperation: vi.fn(),
    });
    render(<ClaimInviteClient />);
    expect(screen.queryByLabelText("Email for Google sign-in")).toBeNull();
    expect(screen.queryByRole("button", { name: "Claim invite" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Invite code"), {
      target: { value: "ALLIES23" },
    });
    const email = await screen.findByLabelText("Email for Google sign-in");
    fireEvent.change(email, { target: { value: "person@example.com" } });
    expect(
      (screen.getByLabelText("Invite code") as HTMLInputElement).value,
    ).toBe("ALLIES23");
    expect(screen.getByRole("button", { name: "Claim invite" })).toBeTruthy();
    expect(claimInvite).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Invite code"), {
      target: { value: "ALLIES2" },
    });
    await waitFor(() =>
      expect(screen.queryByLabelText("Email for Google sign-in")).toBeNull(),
    );
    fireEvent.change(screen.getByLabelText("Invite code"), {
      target: { value: "ALLIES24" },
    });
    expect(
      (
        (await screen.findByLabelText(
          "Email for Google sign-in",
        )) as HTMLInputElement
      ).value,
    ).toBe("person@example.com");
  });

  it("submits the code and email once, then confirms and returns home", async () => {
    const claimInvite = vi.fn(async () => undefined);
    const runCloudOperation = vi.fn(
      async (operation: (signal?: AbortSignal) => Promise<unknown>) =>
        operation(),
    );
    sessionMock.useSession.mockReturnValue({
      client: { claimInvite },
      runCloudOperation,
    });

    render(<ClaimInviteClient />);
    fireEvent.change(screen.getByLabelText("Invite code"), {
      target: { value: "ALLIES23" },
    });
    await screen.findByLabelText("Email for Google sign-in");
    fireEvent.change(screen.getByLabelText("Email for Google sign-in"), {
      target: { value: " person@example.com " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Claim invite" }));

    await waitFor(() => expect(claimInvite).toHaveBeenCalledOnce());
    expect(claimInvite).toHaveBeenCalledWith(
      { code: "ALLIES23", email: "person@example.com" },
      { signal: undefined },
    );
    expect(runCloudOperation).toHaveBeenCalledWith(
      expect.any(Function),
      expect.objectContaining({ csrf: true }),
    );
    expect(
      (await screen.findByRole("link", { name: "Go home" })).getAttribute(
        "href",
      ),
    ).toBe("/");
    await waitFor(() => expect(sessionMock.replace).toHaveBeenCalledWith("/"), {
      timeout: 2500,
    });
    expect(
      screen
        .getByRole("heading", { name: "You're in" })
        .closest(".ph-no-capture"),
    ).toBeTruthy();
  });

  it("disables duplicate submissions while keeping local fields in memory", async () => {
    let resolveClaim!: () => void;
    const claimInvite = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveClaim = resolve;
        }),
    );
    const runCloudOperation = vi.fn(
      async (operation: (signal?: AbortSignal) => Promise<unknown>) =>
        operation(),
    );
    sessionMock.useSession.mockReturnValue({
      client: { claimInvite },
      runCloudOperation,
    });

    render(<ClaimInviteClient />);
    fireEvent.change(screen.getByLabelText("Invite code"), {
      target: { value: "ALLIES23" },
    });
    await screen.findByLabelText("Email for Google sign-in");
    fireEvent.change(screen.getByLabelText("Email for Google sign-in"), {
      target: { value: "person@example.com" },
    });
    const button = screen.getByRole("button", { name: "Claim invite" });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(claimInvite).toHaveBeenCalledOnce());
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(
      (screen.getByLabelText("Email for Google sign-in") as HTMLInputElement)
        .disabled,
    ).toBe(true);
    resolveClaim();
  });

  it.each([
    [
      { kind: "conflict", code: "invite_unavailable" },
      "This invite is unavailable.",
    ],
    [{ kind: "validation", status: 422 }, "Enter a valid invite code"],
    [{ kind: "throttled", status: 429 }, "Too many attempts."],
    [{ kind: "server", status: 503 }, "temporarily unavailable"],
  ] as const)("maps %o to safe recovery copy", async (error, message) => {
    const claimInvite = vi.fn(async () => {
      throw error;
    });
    const runCloudOperation = vi.fn(
      async (operation: (signal?: AbortSignal) => Promise<unknown>) =>
        operation(),
    );
    sessionMock.useSession.mockReturnValue({
      client: { claimInvite },
      runCloudOperation,
    });

    render(<ClaimInviteClient />);
    fireEvent.change(screen.getByLabelText("Invite code"), {
      target: { value: "ALLIES23" },
    });
    await screen.findByLabelText("Email for Google sign-in");
    fireEvent.change(screen.getByLabelText("Email for Google sign-in"), {
      target: { value: "person@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Claim invite" }));

    expect((await screen.findByRole("alert")).textContent).toContain(message);
    expect(
      (screen.getByLabelText("Email for Google sign-in") as HTMLInputElement)
        .value,
    ).toBe("person@example.com");
  });

  it("aborts an in-flight claim when the form unmounts", async () => {
    let operationSignal: AbortSignal | undefined;
    const claimInvite = vi.fn(
      (_input: unknown, options?: { signal?: AbortSignal }) => {
        operationSignal = options?.signal;
        return new Promise<void>(() => undefined);
      },
    );
    const runCloudOperation = vi.fn(
      async (
        operation: (signal?: AbortSignal) => Promise<unknown>,
        options?: { signal?: AbortSignal },
      ) => operation(options?.signal),
    );
    sessionMock.useSession.mockReturnValue({
      client: { claimInvite },
      runCloudOperation,
    });

    const { unmount } = render(<ClaimInviteClient />);
    fireEvent.change(screen.getByLabelText("Invite code"), {
      target: { value: "ALLIES23" },
    });
    await screen.findByLabelText("Email for Google sign-in");
    fireEvent.change(screen.getByLabelText("Email for Google sign-in"), {
      target: { value: "person@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Claim invite" }));
    await waitFor(() => expect(operationSignal).toBeInstanceOf(AbortSignal));

    unmount();

    expect(operationSignal?.aborted).toBe(true);
  });
});
