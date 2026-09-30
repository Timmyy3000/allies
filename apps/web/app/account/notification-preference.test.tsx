// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { PushLifecycle, PushView } from "../../lib/pwa/push-lifecycle";
import { NotificationPreference } from "./notification-preference";
afterEach(cleanup);
it("exposes off, busy, unsupported, failure/retry and enabled switch states", () => {
  let state: PushView = { status: "off", message: "Approvals, routines and replies.", available: true };
  const enable = vi.fn(); const disable = vi.fn(); const retry = vi.fn();
  const push = { subscribe: () => () => undefined, getSnapshot: () => state, getServerSnapshot: () => state, enable, disable, retry } as unknown as PushLifecycle;
  const view = render(<NotificationPreference push={push} />);
  fireEvent.click(screen.getByRole("switch")); expect(enable).toHaveBeenCalledOnce();
  state = { ...state, status: "enabling" }; view.rerender(<NotificationPreference push={push} />); expect((screen.getByRole("switch") as HTMLButtonElement).disabled).toBe(true);
  state = { ...state, status: "failed", message: "Notifications need recovery. Try again." }; view.rerender(<NotificationPreference push={push} />); expect(screen.getByRole("alert").textContent).toContain("Try again");
  state = { ...state, available: false }; view.rerender(<NotificationPreference push={push} />); fireEvent.click(screen.getByRole("switch")); expect(retry).toHaveBeenCalledOnce();
  state = { ...state, available: true, status: "enabled" }; view.rerender(<NotificationPreference push={push} />); fireEvent.click(screen.getByRole("switch")); expect(disable).toHaveBeenCalledOnce(); expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("true");
  state = { ...state, status: "unsupported", available: false }; view.rerender(<NotificationPreference push={push} />); expect((screen.getByRole("switch") as HTMLButtonElement).disabled).toBe(true);
});
