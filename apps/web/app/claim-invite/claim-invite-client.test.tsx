// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sessionMock = vi.hoisted(() => ({ useSession: vi.fn() }));
vi.mock("../../lib/session/session-context", () => sessionMock);
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

import { ClaimInviteClient } from "./claim-invite-client";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  sessionMock.useSession.mockReset();
});

describe("ClaimInviteClient", () => {
  it("submits the code and email once, then links to Google sign-in", async () => {
    const claimInvite = vi.fn(async () => undefined);
    const runCloudOperation = vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>) => operation());
    sessionMock.useSession.mockReturnValue({ client: { claimInvite }, runCloudOperation });

    render(<ClaimInviteClient returnTo="/home?from=onboarding" />);
    fireEvent.change(screen.getByLabelText("Invite code"), { target: { value: " invite-code " } });
    fireEvent.change(screen.getByLabelText("Email for Google sign-in"), { target: { value: " person@example.com " } });
    fireEvent.click(screen.getByRole("button", { name: "Claim invite" }));

    await waitFor(() => expect(claimInvite).toHaveBeenCalledOnce());
    expect(claimInvite).toHaveBeenCalledWith({ code: "invite-code", email: "person@example.com" }, { signal: undefined });
    expect(runCloudOperation).toHaveBeenCalledWith(expect.any(Function), expect.objectContaining({ csrf: true }));
    expect(screen.getByRole("link", { name: "Continue with Google" }).getAttribute("href"))
      .toBe("/sign-in?returnTo=%2Fhome%3Ffrom%3Donboarding");
    expect(screen.getByText("person@example.com")).toBeTruthy();
    expect(screen.getByText("person@example.com").closest(".ph-no-capture")).toBeTruthy();
  });

  it("disables duplicate submissions while keeping local fields in memory", async () => {
    let resolveClaim!: () => void;
    const claimInvite = vi.fn(() => new Promise<void>((resolve) => { resolveClaim = resolve; }));
    const runCloudOperation = vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>) => operation());
    sessionMock.useSession.mockReturnValue({ client: { claimInvite }, runCloudOperation });

    render(<ClaimInviteClient returnTo="/home" />);
    fireEvent.change(screen.getByLabelText("Invite code"), { target: { value: "invite-code" } });
    fireEvent.change(screen.getByLabelText("Email for Google sign-in"), { target: { value: "person@example.com" } });
    const button = screen.getByRole("button", { name: "Claim invite" });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(claimInvite).toHaveBeenCalledOnce());
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("Invite code") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText("Email for Google sign-in") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText("Invite code") as HTMLInputElement).value).toBe("invite-code");
    resolveClaim();
  });

  it.each([
    [{ kind: "conflict", code: "invite_unavailable" }, "This invite is unavailable."],
    [{ kind: "validation", status: 422 }, "Enter a valid invite code"],
    [{ kind: "throttled", status: 429 }, "Too many attempts."],
    [{ kind: "server", status: 503 }, "temporarily unavailable"],
  ] as const)("maps %o to safe recovery copy", async (error, message) => {
    const claimInvite = vi.fn(async () => { throw error; });
    const runCloudOperation = vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>) => operation());
    sessionMock.useSession.mockReturnValue({ client: { claimInvite }, runCloudOperation });

    render(<ClaimInviteClient returnTo="/home" />);
    fireEvent.change(screen.getByLabelText("Invite code"), { target: { value: "invite-code" } });
    fireEvent.change(screen.getByLabelText("Email for Google sign-in"), { target: { value: "person@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Claim invite" }));

    expect((await screen.findByRole("alert")).textContent).toContain(message);
    expect((screen.getByLabelText("Invite code") as HTMLInputElement).value).toBe("invite-code");
    expect((screen.getByLabelText("Email for Google sign-in") as HTMLInputElement).value).toBe("person@example.com");
  });

  it("aborts an in-flight claim when the form unmounts", async () => {
    let operationSignal: AbortSignal | undefined;
    const claimInvite = vi.fn((_input: unknown, options?: { signal?: AbortSignal }) => {
      operationSignal = options?.signal;
      return new Promise<void>(() => undefined);
    });
    const runCloudOperation = vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>, options?: { signal?: AbortSignal }) =>
      operation(options?.signal));
    sessionMock.useSession.mockReturnValue({ client: { claimInvite }, runCloudOperation });

    const { unmount } = render(<ClaimInviteClient returnTo="/home" />);
    fireEvent.change(screen.getByLabelText("Invite code"), { target: { value: "invite-code" } });
    fireEvent.change(screen.getByLabelText("Email for Google sign-in"), { target: { value: "person@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Claim invite" }));
    await waitFor(() => expect(operationSignal).toBeInstanceOf(AbortSignal));

    unmount();

    expect(operationSignal?.aborted).toBe(true);
  });
});
