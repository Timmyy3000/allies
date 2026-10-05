// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AllyPreviewFlowContext, type AllyPreviewFlowValue } from "../../../lib/waitlist/flow";
import { WaitlistPreviewScreen } from "./waitlist-preview";
import { readOnboardingHandoff } from "../../../lib/allies/onboarding-handoff";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("motion/react", async (importOriginal) => ({
  ...await importOriginal<typeof import("motion/react")>(),
  useReducedMotion: () => true,
}));
vi.mock("./persistent-ally", () => ({ ONBOARDING_ALLY_LAYOUT_ID: "test-ally", PersistentAllyAvatar: ({ state }: { state: string }) => <span data-testid="preview-avatar" data-state={state} /> }));
vi.mock("./auth-overlay", () => ({ AuthOverlay: ({ onPrepareGoogleSignIn }: { onPrepareGoogleSignIn: () => void }) => <div>Create your account<button onClick={onPrepareGoogleSignIn}>Continue with Google</button></div> }));
vi.mock("../_store/onboarding-store", () => ({
  useOnboardingStore: (select: (state: object) => unknown) => select({
    name: "Test", shape: "ghosty", color: "#fd304f", job: "Testing",
    personalities: [], personalityNote: "Concise", personalityRaw: "Concise",
  }),
}));

afterEach(() => { cleanup(); window.sessionStorage.clear(); });

function setup(completionMode: "authenticated" | "waitlist", pendingAction: "join" | null = null, greeting: "current" | "stale" | "missing" | "empty" = "current") {
  const recordReply = vi.fn(async () => snapshot);
  const snapshot = {
    onboardingAttempt: "a".repeat(32),
    lifecycle: "greeting_ready" as const,
    configuration: { name: greeting === "stale" ? "Previous Ally" : "Test", appearanceCatalogVersion: "v1", appearanceKey: "ghosty:fd304f", job: "Testing", personality: "Concise" },
    greeting: greeting === "missing" ? null : { text: greeting === "empty" ? "" : "A real greeting", status: "completed" }, reply: null, join: null,
  };
  const flow = {
    completionMode, snapshot, status: "ready", pendingAction, lastAction: null,
    error: null, featureEnabled: true, consentVersion: null,
    saveConfiguration: vi.fn(async () => snapshot), recordReply, retry: vi.fn(),
  } as unknown as AllyPreviewFlowValue;
  render(<AllyPreviewFlowContext.Provider value={flow}><WaitlistPreviewScreen /></AllyPreviewFlowContext.Provider>);
  return recordReply;
}

describe("preview completion", () => {
  it("places one idle avatar below the greeting without navigation controls", async () => {
    setup("waitlist");
    const greeting = await screen.findByText("A real greeting");
    const avatar = screen.getByTestId("preview-avatar");
    expect(screen.getAllByTestId("preview-avatar")).toHaveLength(1);
    expect(avatar.dataset.state).toBe("idle");
    expect(greeting.compareDocumentPosition(avatar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("button", { name: /back|settings/i })).toBeNull();
  });

  it("shows a thinking avatar and text while waiting for the greeting", async () => {
    setup("waitlist", null, "missing");
    expect(await screen.findByText("Thinking")).toBeTruthy();
    expect(screen.getAllByTestId("preview-avatar")).toHaveLength(1);
    expect(screen.getByTestId("preview-avatar").dataset.state).toBe("thinking");
  });

  it("submits an authenticated reply without reopening sign-up", async () => {
    const recordReply = setup("authenticated");
    const input = await screen.findByRole("textbox", { name: "Reply to your Ally" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "  Hello  " } });
    expect(screen.queryByText("Create your account")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    expect(recordReply).toHaveBeenCalledExactlyOnceWith("Hello");
  });

  it.each([null, "join"] as const)("guards empty or busy authenticated creation (%s)", async (pending) => {
    const recordReply = setup("authenticated", pending);
    const input = await screen.findByRole("textbox", { name: "Reply to your Ally" });
    if (pending) fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.submit(input.closest("form")!);
    expect(recordReply).not.toHaveBeenCalled();
  });

  it.each(["stale", "missing", "empty"] as const)("waits for a current Cloud greeting (%s)", async (greeting) => {
    const recordReply = setup("authenticated", null, greeting);
    const input = await screen.findByRole("textbox", { name: "Reply to your Ally" });
    fireEvent.change(input, { target: { value: "Hello" } });
    expect((screen.getByRole("button", { name: "Send reply" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.submit(input.closest("form")!);
    expect(recordReply).not.toHaveBeenCalled();
  });

  it("retains the sign-up gate for anonymous previews", async () => {
    const recordReply = setup("waitlist");
    const input = await screen.findByRole("textbox", { name: "Reply to your Ally" });
    fireEvent.focus(input);
    expect(screen.queryByText("Create your account")).toBeNull();
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    expect(screen.getByText("Create your account")).toBeTruthy();
    expect(recordReply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
    expect(readOnboardingHandoff()?.input).toEqual({
      name: "Test", job: "Testing", personality: "Concise", appearanceCatalogVersion: "v1",
      appearanceKey: "ghosty:fd304f", onboardingAttempt: "a".repeat(32), reply: "Hello",
    });
  });
});
