// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OnboardingDrawer from "./onboarding-drawer";

afterEach(cleanup);
beforeEach(() => {
  window.matchMedia = vi.fn(() => ({
    matches: false,
    media: "",
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
});

describe("OnboardingDrawer", () => {
  it("focuses the dialog, closes on Escape, and restores its trigger", async () => {
    const onClose = vi.fn();
    const trigger = document.createElement("button");
    trigger.textContent = "Open";
    document.body.append(trigger);
    trigger.focus();

    const { rerender } = render(
      <OnboardingDrawer open onClose={onClose}>
        <button type="button">First field</button>
      </OnboardingDrawer>,
    );

    await waitFor(() => expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();

    rerender(
      <OnboardingDrawer open={false} onClose={onClose}>
        <button type="button">First field</button>
      </OnboardingDrawer>,
    );
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });
});
