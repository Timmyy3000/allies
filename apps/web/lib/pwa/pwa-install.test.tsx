// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  InstallInvitation,
  PWA_INSTALL_COOLDOWN_MS,
  PWA_INSTALL_DISMISSAL_KEY,
  PwaInstallProvider,
  type BeforeInstallPromptEvent,
} from "./pwa-install";

const originalMatchMedia = window.matchMedia;
const originalStorage = window.localStorage;
const originalUserAgent = navigator.userAgent;
const originalPlatform = navigator.platform;
const originalMaxTouchPoints = navigator.maxTouchPoints;
const originalStandalone = (navigator as Navigator & { standalone?: boolean }).standalone;

function setDisplayMode(standalone: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const media = {
    get matches() { return standalone; },
    media: "(display-mode: standalone)",
    onchange: null,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
    addListener: (listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
    removeListener: (listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
    dispatchEvent: (event: Event) => {
      listeners.forEach((listener) => listener(event as MediaQueryListEvent));
      return true;
    },
  } as unknown as MediaQueryList;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => media),
  });
  return media;
}

function setIOS(ios: boolean) {
  Object.defineProperty(navigator, "userAgent", {
    configurable: true,
    value: ios
      ? "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
      : originalUserAgent,
  });
  Object.defineProperty(navigator, "platform", { configurable: true, value: ios ? "iPhone" : originalPlatform });
  Object.defineProperty(navigator, "maxTouchPoints", { configurable: true, value: ios ? 5 : originalMaxTouchPoints });
  Object.defineProperty(navigator, "standalone", { configurable: true, value: false });
}

function setStorage(storage: Storage) {
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
}

function makeInstallEvent(
  choice: Promise<{ outcome: "accepted" | "dismissed" }> = Promise.resolve({ outcome: "accepted" }),
) {
  const event = new Event("beforeinstallprompt", { cancelable: true });
  const prompt = vi.fn();
  Object.defineProperties(event, {
    prompt: { configurable: true, value: prompt },
    userChoice: { configurable: true, value: choice },
  });
  return { event: event as BeforeInstallPromptEvent, prompt };
}

function renderInvitation(children: ReactNode = <InstallInvitation />) {
  return render(<PwaInstallProvider>{children}</PwaInstallProvider>);
}

async function dispatchInstallEvent(event: Event) {
  await act(async () => {
    window.dispatchEvent(event);
  });
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  Object.defineProperty(window, "matchMedia", { configurable: true, value: originalMatchMedia });
  Object.defineProperty(window, "localStorage", { configurable: true, value: originalStorage });
  Object.defineProperty(navigator, "userAgent", { configurable: true, value: originalUserAgent });
  Object.defineProperty(navigator, "platform", { configurable: true, value: originalPlatform });
  Object.defineProperty(navigator, "maxTouchPoints", { configurable: true, value: originalMaxTouchPoints });
  if (originalStandalone === undefined) delete (navigator as Navigator & { standalone?: boolean }).standalone;
  else Object.defineProperty(navigator, "standalone", { configurable: true, value: originalStandalone });
});

beforeEach(() => {
  window.localStorage.clear();
  setDisplayMode(false);
  setIOS(false);
});

describe("PwaInstallProvider", () => {
  it("is server-safe and renders no invitation without an actionable capability", () => {
    const { container } = renderInvitation();
    expect(container.textContent).not.toContain("Install Allies");
  });

  it("cancels and captures a native event before the home screen settles", async () => {
    const { event, prompt } = makeInstallEvent();
    renderInvitation();

    await dispatchInstallEvent(event);
    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(screen.getByRole("button", { name: "Install Allies" })).toBeTruthy(), { timeout: 4_000 });

    fireEvent.click(screen.getByRole("button", { name: "Install Allies" }));
    await waitFor(() => expect(prompt).toHaveBeenCalledOnce());
  });

  it("uses the newest captured event", async () => {
    const first = makeInstallEvent();
    const second = makeInstallEvent();
    renderInvitation();
    await dispatchInstallEvent(first.event);
    await dispatchInstallEvent(second.event);
    await waitFor(() => expect(screen.getByRole("button", { name: "Install Allies" })).toBeTruthy(), { timeout: 4_000 });

    fireEvent.click(screen.getByRole("button", { name: "Install Allies" }));
    await waitFor(() => expect(second.prompt).toHaveBeenCalledOnce());
    expect(first.prompt).not.toHaveBeenCalled();
  });

  it("clears an accepted native prompt and prevents a second attempt", async () => {
    let resolveChoice!: (choice: { outcome: "accepted" | "dismissed" }) => void;
    const choice = new Promise<{ outcome: "accepted" | "dismissed" }>((resolve) => { resolveChoice = resolve; });
    const { event, prompt } = makeInstallEvent(choice);
    renderInvitation();
    await dispatchInstallEvent(event);
    await waitFor(() => expect(screen.getByRole("button", { name: "Install Allies" })).toBeTruthy(), { timeout: 4_000 });

    fireEvent.click(screen.getByRole("button", { name: "Install Allies" }));
    fireEvent.click(screen.getByRole("button", { name: "Install Allies" }));
    expect(prompt).toHaveBeenCalledOnce();
    resolveChoice({ outcome: "accepted" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull());
    expect(window.localStorage.getItem(PWA_INSTALL_DISMISSAL_KEY)).toBeNull();
  });

  it("records a dismissed native prompt and applies the seven-day cooldown", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const { event } = makeInstallEvent(Promise.resolve({ outcome: "dismissed" }));
    renderInvitation();
    await dispatchInstallEvent(event);
    act(() => { vi.advanceTimersByTime(3_000); });
    fireEvent.click(screen.getByRole("button", { name: "Install Allies" }));

    await act(async () => { await Promise.resolve(); });
    expect(window.localStorage.getItem(PWA_INSTALL_DISMISSAL_KEY)).toBe("13000");
    expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull();
  });

  it("shows again exactly at the seven-day boundary", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(20_000);
    const { event } = makeInstallEvent();
    renderInvitation();
    await dispatchInstallEvent(event);
    act(() => { vi.advanceTimersByTime(3_000); });
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull();

    act(() => { vi.advanceTimersByTime(PWA_INSTALL_COOLDOWN_MS - 1); });
    expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull();
    act(() => { vi.advanceTimersByTime(1); });
    expect(screen.getByRole("button", { name: "Install Allies" })).toBeTruthy();
  });

  it("clamps a valid future timestamp to a seven-day cooldown from now", async () => {
    vi.useFakeTimers();
    const now = 30_000;
    vi.setSystemTime(now);
    window.localStorage.setItem(PWA_INSTALL_DISMISSAL_KEY, String(now + PWA_INSTALL_COOLDOWN_MS * 2));
    const { event } = makeInstallEvent();
    const firstRender = renderInvitation();
    await dispatchInstallEvent(event);
    act(() => { vi.advanceTimersByTime(3_000); });

    expect(window.localStorage.getItem(PWA_INSTALL_DISMISSAL_KEY)).toBe("30000");
    expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull();
    firstRender.unmount();
    renderInvitation();
    const remountEvent = makeInstallEvent();
    await dispatchInstallEvent(remountEvent.event);
    act(() => { vi.advanceTimersByTime(3_000); });
    act(() => { vi.advanceTimersByTime(PWA_INSTALL_COOLDOWN_MS - 6_000 - 1); });
    expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull();
    act(() => { vi.advanceTimersByTime(1); });
    expect(screen.getByRole("button", { name: "Install Allies" })).toBeTruthy();
  });

  it("consumes a failed native prompt without recording a dismissal", async () => {
    let rejectChoice!: (error: Error) => void;
    const choice = new Promise<{ outcome: "accepted" | "dismissed" }>((_resolve, reject) => { rejectChoice = reject; });
    const { event, prompt } = makeInstallEvent(choice);
    renderInvitation();
    await dispatchInstallEvent(event);
    await waitFor(() => expect(screen.getByRole("button", { name: "Install Allies" })).toBeTruthy(), { timeout: 4_000 });
    fireEvent.click(screen.getByRole("button", { name: "Install Allies" }));
    rejectChoice(new Error("prompt failed"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull());
    expect(prompt).toHaveBeenCalledOnce();
    expect(window.localStorage.getItem(PWA_INSTALL_DISMISSAL_KEY)).toBeNull();
  });

  it("suppresses the invitation for standalone and installed signals", async () => {
    setDisplayMode(true);
    const standalone = makeInstallEvent();
    renderInvitation();
    await dispatchInstallEvent(standalone.event);
    expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull();
    cleanup();

    setDisplayMode(false);
    const { event } = makeInstallEvent();
    renderInvitation();
    await dispatchInstallEvent(event);
    await waitFor(() => expect(screen.getByRole("button", { name: "Install Allies" })).toBeTruthy(), { timeout: 4_000 });
    act(() => { window.dispatchEvent(new Event("appinstalled")); });
    expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull();
  });

  it("shows iOS instructions only after the user activates installation", async () => {
    setIOS(true);
    renderInvitation();
    await waitFor(() => expect(screen.getByRole("button", { name: "Install Allies" })).toBeTruthy(), { timeout: 4_000 });
    expect(screen.queryByRole("status")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Install Allies" }));
    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Add Allies to your Home Screen" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Got it" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull();
  });

  it("fails closed for denied or corrupt local storage", async () => {
    const denied = {
      getItem: vi.fn(() => { throw new Error("storage denied"); }),
      setItem: vi.fn(() => { throw new Error("storage denied"); }),
    } as unknown as Storage;
    setStorage(denied);
    const deniedEvent = makeInstallEvent();
    renderInvitation();
    await dispatchInstallEvent(deniedEvent.event);
    expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull();
    cleanup();

    const corrupt = {
      getItem: () => "not-a-timestamp",
      setItem: vi.fn(),
    } as unknown as Storage;
    setStorage(corrupt);
    const corruptEvent = makeInstallEvent();
    renderInvitation();
    await dispatchInstallEvent(corruptEvent.event);
    expect(screen.queryByRole("button", { name: "Install Allies" })).toBeNull();
  });

  it("removes listeners on unmount", async () => {
    const { unmount } = renderInvitation();
    unmount();
    const { event } = makeInstallEvent();
    await dispatchInstallEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });
});
