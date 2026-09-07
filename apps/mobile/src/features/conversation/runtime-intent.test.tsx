// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react';
import { createElement, StrictMode, type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { useComposingRuntimeIntent, type RuntimeIntentRequester } from './runtime-intent';

vi.mock('expo-crypto', () => ({ randomUUID: () => '00000000-0000-4000-8000-000000000001' }));

describe('useComposingRuntimeIntent', () => {
  it('emits one content-free intent on the first meaningful edit', () => {
    const requestIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: 'waking' }));
    const { result } = renderHook(() => useComposingRuntimeIntent('ally-1', requestIntent));

    act(() => {
      result.current.observeEdit('   ');
      result.current.observeEdit('hello');
      result.current.observeEdit('hello again');
    });

    expect(requestIntent).toHaveBeenCalledOnce();
    expect(requestIntent.mock.calls[0]?.[0]).toBe('ally-1');
    expect(requestIntent.mock.calls[0]?.[1]).toMatch(/Z$/);
    expect(requestIntent.mock.calls[0]?.[2]).toBe('00000000-0000-4000-8000-000000000001');
    expect(requestIntent.mock.calls[0]).toHaveLength(4);
    expect(requestIntent.mock.calls[0]?.[3]).toBeInstanceOf(AbortSignal);
  });

  it('waits until IME composition ends before emitting', () => {
    const requestIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: 'waking' }));
    const { result } = renderHook(() => useComposingRuntimeIntent('ally-1', requestIntent));

    act(() => {
      result.current.compositionStart();
      result.current.observeEdit('日');
    });
    expect(requestIntent).not.toHaveBeenCalled();

    act(() => result.current.compositionEnd('日本語'));
    expect(requestIntent).toHaveBeenCalledOnce();
  });

  it('keeps the one-shot guard across rerenders', () => {
    const requestIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: 'waking' }));
    const { result, rerender } = renderHook(
      ({ request }) => useComposingRuntimeIntent('ally-1', request),
      { initialProps: { request: requestIntent } },
    );

    act(() => result.current.observeEdit('hello'));
    rerender({ request: vi.fn<RuntimeIntentRequester>(async () => ({ status: 'ready' })) });
    act(() => result.current.observeEdit('still hello'));

    expect(requestIntent).toHaveBeenCalledOnce();
  });

  it('does not double-emit when mounted under Strict Mode', () => {
    const requestIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: 'waking' }));
    const wrapper = ({ children }: { children: ReactNode }) => createElement(StrictMode, null, children);
    const { result } = renderHook(() => useComposingRuntimeIntent('ally-1', requestIntent), { wrapper });

    act(() => result.current.observeEdit('hello'));

    expect(requestIntent).toHaveBeenCalledOnce();
  });

  it('does not let a synchronous requester failure escape the edit handler', () => {
    const requestIntent = vi.fn<RuntimeIntentRequester>(() => {
      throw new Error('offline');
    });
    const { result } = renderHook(() => useComposingRuntimeIntent('ally-1', requestIntent));

    expect(() => act(() => result.current.observeEdit('hello'))).not.toThrow();
    expect(requestIntent).toHaveBeenCalledOnce();
  });

  it('aborts an in-flight intent when the view unmounts', () => {
    let signal: AbortSignal | undefined;
    const requestIntent = vi.fn<RuntimeIntentRequester>(
      async (_allyId, _occurredAt, _idempotencyKey, operationSignal) => {
        signal = operationSignal;
        return new Promise(() => undefined);
      },
    );
    const { result, unmount } = renderHook(() => useComposingRuntimeIntent('ally-1', requestIntent));

    act(() => result.current.observeEdit('hello'));
    expect(signal?.aborted).toBe(false);

    unmount();

    expect(signal?.aborted).toBe(true);
  });

  it('aborts the old request and allows one intent for the next Ally', () => {
    const signals: AbortSignal[] = [];
    const requestIntent = vi.fn<RuntimeIntentRequester>(
      async (_allyId, _occurredAt, _idempotencyKey, operationSignal) => {
        if (operationSignal) signals.push(operationSignal);
        return { status: 'waking' };
      },
    );
    const { result, rerender } = renderHook(
      ({ allyId }) => useComposingRuntimeIntent(allyId, requestIntent),
      { initialProps: { allyId: 'ally-1' } },
    );

    act(() => result.current.observeEdit('hello'));
    rerender({ allyId: 'ally-2' });
    act(() => result.current.observeEdit('bonjour'));

    expect(signals[0]?.aborted).toBe(true);
    expect(requestIntent).toHaveBeenCalledTimes(2);
    expect(requestIntent.mock.calls[1]?.[0]).toBe('ally-2');
  });
});
