// @vitest-environment jsdom

import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, StrictMode, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useComposingRuntimeIntent, type RuntimeIntentRequester } from "./runtime-intent";

describe("useComposingRuntimeIntent", () => {
  it("exposes confirmed readiness without treating an outstanding request as ready", async () => {
    let resolveIntent!: (value: { status: "ready" }) => void;
    const request = vi.fn<RuntimeIntentRequester>(() => new Promise(resolve => { resolveIntent = resolve; }));
    const { result } = renderHook(() => useComposingRuntimeIntent("ally-1", request));
    act(() => result.current.observeEdit("hello"));
    expect(result.current.status).toBe("requesting");
    await act(async () => resolveIntent({ status: "ready" }));
    expect(result.current.status).toBe("ready");
  });

  it("ignores late readiness from the previous Ally", async () => {
    let resolveOld!: (value: { status: "ready" }) => void;
    const request = vi.fn<RuntimeIntentRequester>((id) => id === "ally-1"
      ? new Promise(resolve => { resolveOld = resolve; })
      : Promise.resolve({ status: "waking" }));
    const { result, rerender } = renderHook(({ id }) => useComposingRuntimeIntent(id, request), { initialProps: { id: "ally-1" } });
    act(() => result.current.observeEdit("hello"));
    rerender({ id: "ally-2" });
    act(() => result.current.observeEdit("hello"));
    await waitFor(() => expect(result.current.status).toBe("waking"));
    await act(async () => resolveOld({ status: "ready" }));
    expect(result.current.status).toBe("waking");
  });

  it("emits one content-free intent on the first meaningful edit", () => {
    const requestIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: "waking" as const }));
    const { result } = renderHook(() => useComposingRuntimeIntent("ally-1", requestIntent));

    act(() => {
      result.current.observeEdit("   ");
      result.current.observeEdit("hello");
      result.current.observeEdit("hello again");
    });

    expect(requestIntent).toHaveBeenCalledOnce();
    expect(requestIntent.mock.calls[0]?.[0]).toBe("ally-1");
    expect(requestIntent.mock.calls[0]?.[1]).toMatch(/Z$/);
    expect(requestIntent.mock.calls[0]?.[2]).toMatch(/^[0-9a-f-]{36}$/);
    expect(requestIntent.mock.calls[0]).toHaveLength(4);
    expect(requestIntent.mock.calls[0]?.[3]).toBeInstanceOf(AbortSignal);
  });

  it("emits the same one-shot intent when an attachment is added first", () => {
    const requestIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: "waking" as const }));
    const { result } = renderHook(() => useComposingRuntimeIntent("ally-1", requestIntent));

    act(() => {
      result.current.observeAttachment();
      result.current.observeEdit("message after the file");
    });

    expect(requestIntent).toHaveBeenCalledOnce();
    expect(requestIntent.mock.calls[0]?.[0]).toBe("ally-1");
  });

  it("waits until IME composition ends before emitting", () => {
    const requestIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: "waking" as const }));
    const { result } = renderHook(() => useComposingRuntimeIntent("ally-1", requestIntent));

    act(() => {
      result.current.compositionStart();
      result.current.observeEdit("日");
    });
    expect(requestIntent).not.toHaveBeenCalled();

    act(() => result.current.compositionEnd("日本語"));
    expect(requestIntent).toHaveBeenCalledOnce();
  });

  it("keeps the one-shot guard across rerenders", () => {
    const requestIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: "waking" as const }));
    const { result, rerender } = renderHook(
      ({ request }) => useComposingRuntimeIntent("ally-1", request),
      { initialProps: { request: requestIntent } },
    );

    act(() => result.current.observeEdit("hello"));
    rerender({ request: vi.fn<RuntimeIntentRequester>(async () => ({ status: "ready" as const })) });
    act(() => result.current.observeEdit("still hello"));

    expect(requestIntent).toHaveBeenCalledOnce();
  });

  it("does not double-emit when mounted under Strict Mode", () => {
    const requestIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: "waking" as const }));
    const wrapper = ({ children }: { children: ReactNode }) => createElement(StrictMode, null, children);
    const { result } = renderHook(() => useComposingRuntimeIntent("ally-1", requestIntent), { wrapper });

    act(() => result.current.observeEdit("hello"));

    expect(requestIntent).toHaveBeenCalledOnce();
  });

  it("does not let a synchronous requester failure escape the edit handler", () => {
    const requestIntent = vi.fn<RuntimeIntentRequester>(() => {
      throw new Error("offline");
    });
    const { result } = renderHook(() => useComposingRuntimeIntent("ally-1", requestIntent));

    expect(() => act(() => result.current.observeEdit("hello"))).not.toThrow();
    expect(requestIntent).toHaveBeenCalledOnce();
  });

  it("aborts an in-flight intent when the view unmounts", () => {
    let signal: AbortSignal | undefined;
    const requestIntent = vi.fn<RuntimeIntentRequester>(
      async (_allyId, _occurredAt, _idempotencyKey, operationSignal) => {
        signal = operationSignal;
        return new Promise(() => undefined);
      },
    );
    const { result, unmount } = renderHook(() =>
      useComposingRuntimeIntent("ally-1", requestIntent),
    );

    act(() => result.current.observeEdit("hello"));
    expect(signal?.aborted).toBe(false);

    unmount();

    expect(signal?.aborted).toBe(true);
  });

  it("aborts the old request and allows one intent for the next ally", () => {
    const signals: AbortSignal[] = [];
    const requestIntent = vi.fn<RuntimeIntentRequester>(
      async (_allyId, _occurredAt, _idempotencyKey, signal) => {
        if (signal) signals.push(signal);
        return { status: "waking" as const };
      },
    );
    const { result, rerender } = renderHook(
      ({ allyId }) => useComposingRuntimeIntent(allyId, requestIntent),
      { initialProps: { allyId: "ally-1" } },
    );

    act(() => result.current.observeEdit("hello"));
    rerender({ allyId: "ally-2" });
    act(() => result.current.observeEdit("bonjour"));

    expect(signals[0]?.aborted).toBe(true);
    expect(requestIntent).toHaveBeenCalledTimes(2);
    expect(requestIntent.mock.calls[1]?.[0]).toBe("ally-2");
  });
});
