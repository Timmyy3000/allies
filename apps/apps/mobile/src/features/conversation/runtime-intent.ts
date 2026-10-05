import * as Crypto from 'expo-crypto';
import { useCallback, useEffect, useRef } from 'react';

import type { RuntimeIntentViewModel } from '@allies/cloud-client';

export type RuntimeIntentRequester = (
  allyId: string,
  occurredAt: string,
  idempotencyKey: string,
  signal?: AbortSignal,
) => Promise<RuntimeIntentViewModel>;

export function useComposingRuntimeIntent(
  allyId: string,
  requestIntent: RuntimeIntentRequester,
) {
  const sentRef = useRef(false);
  const composingRef = useRef(false);
  const requestRef = useRef<{ occurredAt: string; idempotencyKey: string } | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    sentRef.current = false;
    composingRef.current = false;
    requestRef.current = null;

    return () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [allyId]);

  const observeEdit = useCallback((value: string) => {
    if (composingRef.current || sentRef.current || !value.trim()) return;

    sentRef.current = true;
    const request = requestRef.current ?? {
      occurredAt: new Date().toISOString(),
      idempotencyKey: Crypto.randomUUID(),
    };
    requestRef.current = request;
    const controller = new AbortController();
    controllerRef.current = controller;

    try {
      void requestIntent(
        allyId,
        request.occurredAt,
        request.idempotencyKey,
        controller.signal,
      ).catch(() => undefined);
    } catch {
      // Speculative wake must never affect the composer or message send path.
    }
  }, [allyId, requestIntent]);

  const compositionStart = useCallback(() => {
    composingRef.current = true;
  }, []);

  const compositionEnd = useCallback((value: string) => {
    composingRef.current = false;
    observeEdit(value);
  }, [observeEdit]);

  return { observeEdit, compositionStart, compositionEnd };
}
