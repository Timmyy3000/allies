// @vitest-environment jsdom

import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { bindOnboardingHandoff, readOnboardingHandoff, saveOnboardingHandoff } from "./onboarding-handoff";
import { OnboardingHandoffScreen } from "./onboarding-handoff-screen";
import { writeOnboardingResume } from "../../app/(onboarding)/_store/onboarding-resume";
import { useOnboardingStore } from "../../app/(onboarding)/_store/onboarding-store";

const mocks = vi.hoisted(() => ({ session: vi.fn(), replace: vi.fn() }));
vi.mock("../../app/(onboarding)/_components/persistent-ally", () => ({
  AUTH_SIGNUP_ALLY_LAYOUT_ID: "test-ally",
  PersistentAllyAvatar: ({ shape, color }: { shape: string; color: string }) => <span data-testid="welcome-avatar" data-shape={shape} data-color={color} />,
}));
vi.mock("../session/session-context", () => ({ useSession: mocks.session }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: mocks.replace }) }));
vi.mock("../../app/(onboarding)/_components/waitlist-preview", () => ({ WaitlistPreviewScreen: function LegacyPreview() { return <div data-testid="legacy-preview">{useOnboardingStore((state) => state.name)}</div>; } }));

const input = {
  name: "Mira", job: "Help me plan", personality: "Calm and curious",
  appearanceCatalogVersion: "v1", appearanceKey: "ghosty:fd304f",
  onboardingAttempt: "a".repeat(32), reply: "Help me plan tomorrow.",
};

beforeEach(() => { window.sessionStorage.clear(); vi.clearAllMocks(); });
afterEach(cleanup);

describe("guest onboarding handoff", () => {
  it("welcomes the signed-in person with their chosen ally while saving", async () => {
    saveOnboardingHandoff(input);
    writeOnboardingResume({ name: "Mira", shape: "boxy", color: "#fd304f", job: "Help me plan", personalities: [], personalityNote: "Calm", personalityRaw: null });
    mocks.session.mockReturnValue({
      client: { getCurrentAccount: vi.fn(async () => ({ userId: "user-1", displayName: "Tolani Example", workspace: { id: "workspace-1" } })), createAlly: vi.fn(() => new Promise(() => {})) },
      runCloudOperation: async (operation: () => Promise<unknown>) => operation(),
    });
    render(<QueryClientProvider client={new QueryClient()}><OnboardingHandoffScreen /></QueryClientProvider>);
    await screen.findByRole("heading", { name: "Looking good, Tolani" });
    expect(screen.getByText("We’re done with the basics, one more thing")).toBeTruthy();
    expect(screen.getByTestId("welcome-avatar").getAttribute("data-shape")).toBe("boxy");
    expect(screen.getByTestId("welcome-avatar").getAttribute("data-color")).toBe("#fd304f");
    expect(screen.queryByText("Coming alive....")).toBeNull();
    expect(mocks.replace).not.toHaveBeenCalled();
  });
  it("allows an account mismatch to sign out without losing the saved command", async () => {
    saveOnboardingHandoff(input);
    const command = bindOnboardingHandoff("original-user", "original-workspace");
    const logout = vi.fn(async () => ({ serverConfirmed: true }));
    mocks.session.mockReturnValue({
      client: { getCurrentAccount: vi.fn(async () => ({ userId: "other-user", workspace: { id: "other-workspace" } })) },
      runCloudOperation: async (operation: () => Promise<unknown>) => operation(), logout,
    });
    render(<QueryClientProvider client={new QueryClient()}><OnboardingHandoffScreen /></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Sign out to switch accounts" }));
    await waitFor(() => expect(logout).toHaveBeenCalledOnce());
    expect(readOnboardingHandoff()).toEqual(command);
    expect(screen.getByRole("link", { name: "Back to chats" }).getAttribute("href")).toBe("/home");
  });
  it("restores an older config-only preview without inventing or submitting a first reply", async () => {
    writeOnboardingResume({ name: "Mira", shape: "ghosty", color: "#fd304f", job: "Help me plan", personalities: [], personalityNote: "Calm", personalityRaw: null });
    const createAlly = vi.fn();
    mocks.session.mockReturnValue({
      client: { getCurrentAccount: vi.fn(async () => ({ userId: "user-1", workspace: { id: "workspace-1" } })), createAlly },
      runCloudOperation: async (operation: () => Promise<unknown>) => operation(),
    });
    render(<QueryClientProvider client={new QueryClient()}><OnboardingHandoffScreen /></QueryClientProvider>);
    expect((await screen.findByTestId("legacy-preview")).textContent).toBe("Mira");
    expect(createAlly).not.toHaveBeenCalled();
  });

  it("preserves the exact attempt and reply with one key across storage reads", () => {
    saveOnboardingHandoff(input);
    const command = readOnboardingHandoff();
    saveOnboardingHandoff(input);
    expect(readOnboardingHandoff()).toEqual(command);
    expect(command?.input).toEqual(input);
  });

  it("binds the command before submission and rejects a different account or workspace", () => {
    saveOnboardingHandoff(input);
    const command = bindOnboardingHandoff("user-1", "workspace-1");
    expect(bindOnboardingHandoff("user-1", "workspace-1")).toEqual(command);
    expect(() => bindOnboardingHandoff("user-2", "workspace-1")).toThrow("another account");
    expect(() => bindOnboardingHandoff("user-1", "workspace-2")).toThrow("another account");
    expect(() => saveOnboardingHandoff({ ...input, reply: "Changed" })).toThrow("Finish your saved Ally");
  });

  it("rejects invalid persisted commands", () => {
    window.sessionStorage.setItem("allies.onboarding.handoff.v1", JSON.stringify({ input: { ...input, reply: "" }, key: "ally-create-test", owner: null }));
    expect(readOnboardingHandoff()).toBeNull();
  });

  it("keeps failed creation for retry, then opens that Ally once and clears the handoff", async () => {
    saveOnboardingHandoff(input);
    const key = readOnboardingHandoff()!.key;
    const createAlly = vi.fn().mockRejectedValueOnce({ kind: "network" }).mockResolvedValue({ id: "ally-1" });
    mocks.session.mockReturnValue({
      client: { getCurrentAccount: vi.fn(async () => ({ userId: "user-1", workspace: { id: "workspace-1" } })), createAlly },
      runCloudOperation: async (operation: () => Promise<unknown>) => operation(),
    });
    const queryClient = new QueryClient();
    render(<StrictMode><QueryClientProvider client={queryClient}><OnboardingHandoffScreen /></QueryClientProvider></StrictMode>);
    await screen.findByRole("alert");
    expect(createAlly).toHaveBeenCalledTimes(1);
    expect(mocks.replace).not.toHaveBeenCalled();
    expect(readOnboardingHandoff()?.key).toBe(key);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/home/ally-1"));
    expect(createAlly.mock.calls.map((call) => call.slice(0, 3))).toEqual([
      ["workspace-1", input, key], ["workspace-1", input, key],
    ]);
    expect(readOnboardingHandoff()).toBeNull();
  });
});
