// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { registerPushWorker } from "./push-worker";
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
it("a never-activated worker fails after the bounded wait so settings can retry", async () => {
  vi.useFakeTimers();
  Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { register: vi.fn(async () => ({ active: null })), ready: new Promise(() => undefined) } });
  const result = expect(registerPushWorker()).rejects.toThrow("not ready");
  await vi.advanceTimersByTimeAsync(5000); await result;
});
