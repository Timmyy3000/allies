"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { RuntimeIntentViewModel } from "@allies/cloud-client";

export type RuntimeIntentRequester = (
  allyId: string,
  occurredAt: string,
  idempotencyKey: string,
  signal?: AbortSignal,
) => Promise<RuntimeIntentViewModel>;

function newIdempotencyKey(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi?.randomUUID) return cryptoApi.randomUUID();

  const bytes = new Uint8Array(16);
  if (cryptoApi?.getRandomValues) {
    cryptoApi.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function useComposingRuntimeIntent(
  allyId: string,
  requestIntent: RuntimeIntentRequester,
) {
  const sentRef = useRef(false);
  const composingRef = useRef(false);
  const requestRef = useRef<{ occurredAt: string; idempotencyKey: string } | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const [status, setStatus] = useState<RuntimeIntentViewModel["status"] | "requesting" | null>(null);
  const [statusAllyId, setStatusAllyId] = useState(allyId);
  if (statusAllyId !== allyId) {
    setStatusAllyId(allyId);
    setStatus(null);
  }

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

  const observeInteraction = useCallback(() => {
    if (sentRef.current) return;
    sentRef.current = true;
    const request = requestRef.current ?? {
      occurredAt: new Date().toISOString(),
      idempotencyKey: newIdempotencyKey(),
    };
    requestRef.current = request;
    const controller = new AbortController();
    controllerRef.current = controller;
    setStatus("requesting");

    try {
      void requestIntent(
        allyId,
        request.occurredAt,
        request.idempotencyKey,
        controller.signal,
      ).then((result) => {
        if (!controller.signal.aborted) setStatus(result.status);
      }).catch(() => {
        if (!controller.signal.aborted) setStatus("failed");
      });
    } catch {
      setStatus("failed");
      // Speculative wake must never affect the composer or message send path.
    }
  }, [allyId, requestIntent]);

  const observeEdit = useCallback((value: string) => {
    if (composingRef.current || !value.trim()) return;
    observeInteraction();
  }, [observeInteraction]);

  const compositionStart = useCallback(() => {
    composingRef.current = true;
  }, []);

  const compositionEnd = useCallback((value: string) => {
    composingRef.current = false;
    observeEdit(value);
  }, [observeEdit]);

  return { observeEdit, observeAttachment: observeInteraction, compositionStart, compositionEnd, status };
}
