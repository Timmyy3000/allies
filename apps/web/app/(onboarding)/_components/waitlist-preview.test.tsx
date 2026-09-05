// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AllyPreviewFlowContext, type AllyPreviewFlowValue } from "../../../lib/waitlist/flow";
import { WaitlistPreviewScreen } from "./waitlist-preview";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("motion/react", async (importOriginal) => ({
  ...await importOriginal<typeof import("motion/react")>(),
  useReducedMotion: () => true,
}));
vi.mock("./persistent-ally", () => ({ ONBOARDING_ALLY_LAYOUT_ID: "test-ally", PersistentAllyAvatar: () => null }));
vi.mock("./auth-overlay", () => ({ AuthOverlay: () => <div>Create your account</div> }));
vi.mock("../_store/onboarding-store", () => ({
  useOnboardingStore: (select: (state: object) => unknown) => select({
    name: "Test", shape: "ghosty", color: "#fd304f", job: "Testing",
    personalities: [], personalityNote: "Concise", personalityRaw: "Concise",
  }),
}));

afterEach(cleanup);

function setup(completionMode: "authenticated" | "waitlist", pendingAction: "join" | null = null, greeting: "current" | "stale" | "missing" | "empty" = "current") {
  const recordReply = vi.fn(async () => snapshot);
  const snapshot = {
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
    fireEvent.focus(await screen.findByRole("textbox", { name: "Reply to your Ally" }));
    expect(screen.getByText("Create your account")).toBeTruthy();
    expect(recordReply).not.toHaveBeenCalled();
  });
});
