"use client";

import { isCloudError, type CloudError, type WaitlistCompletionViewModel } from "@allies/cloud-client";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { useCloudClient } from "../session/session-context";
import {
  captureWaitlistEvent,
  identifyWaitlistSubscriber,
} from "../analytics/waitlist";
import { greetingFingerprintForSerialized, serializeConfiguration, type WaitlistConfigurationInput, type WaitlistConfigurationPayload, WaitlistMappingError } from "./catalog";

export type WaitlistAction = "configuration" | "join";
export type WaitlistFlowStatus = "disabled" | "ready" | "error";

export type AllyPreviewAction = WaitlistAction;
export type AllyPreviewFlowStatus = WaitlistFlowStatus;

export interface AllyPreviewSnapshot {
  lifecycle: "configuring" | "greeting_ready" | "reply_pending" | "pending_claim";
  configuration: { name: string | null; appearanceCatalogVersion: string | null; appearanceKey: string | null; job: string | null; personality: string | null };
  greeting: { text: string } | null;
  reply: { text: string; status: "pending" } | null;
  join: { email: string } | null;
}

export interface AllyPreviewFlowValue {
  completionMode: "waitlist" | "authenticated";
  featureEnabled: boolean;
  consentVersion: string | null;
  status: AllyPreviewFlowStatus;
  snapshot: AllyPreviewSnapshot;
  error: CloudError | null;
  pendingAction: AllyPreviewAction | null;
  lastAction: AllyPreviewAction | null;
  saveConfiguration(payload: WaitlistConfigurationPayload): Promise<AllyPreviewSnapshot>;
  recordReply(text: string): Promise<AllyPreviewSnapshot>;
  join?: (email: string) => Promise<WaitlistCompletionViewModel>;
  retry(): Promise<void>;
}

export interface WaitlistFlowValue extends AllyPreviewFlowValue {
  completionMode: "waitlist";
  join: (email: string) => Promise<WaitlistCompletionViewModel>;
}

type LocalSnapshot = AllyPreviewSnapshot;

const EMPTY_SNAPSHOT: AllyPreviewSnapshot = {
  lifecycle: "configuring",
  configuration: { name: null, appearanceCatalogVersion: null, appearanceKey: null, job: null, personality: null },
  greeting: null,
  reply: null,
  join: null,
};

export const AllyPreviewFlowContext = createContext<AllyPreviewFlowValue | null>(null);

function normalizeFlowError(error: unknown): CloudError {
  if (isCloudError(error)) return error;
  if (error instanceof WaitlistMappingError) {
    return { kind: "validation", code: error.code, fieldIssues: [{ code: error.code, message: error.message }] };
  }
  return { kind: "network", code: "waitlist_request_failed" };
}

function newAttemptId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `attempt-${Date.now()}-${Math.random()}`;
}

export function WaitlistFlowProvider({ featureEnabled, consentVersion, children }: { featureEnabled: boolean; consentVersion: string | null; children: ReactNode }) {
  const client = useCloudClient();
  const attemptId = useRef(newAttemptId());
  const attemptToken = useRef<string | null>(null);
  const [snapshot, setSnapshot] = useState<LocalSnapshot>(EMPTY_SNAPSHOT);
  const [pendingAction, setPendingAction] = useState<WaitlistAction | null>(null);
  const [lastAction, setLastAction] = useState<WaitlistAction | null>(null);
  const [error, setError] = useState<CloudError | null>(null);
  const retryAction = useRef<(() => Promise<unknown>) | null>(null);
  const inFlightAction = useRef<Promise<unknown> | null>(null);

  const run = useCallback(<T,>(action: WaitlistAction, operation: () => Promise<T>): Promise<T> => {
    if (inFlightAction.current) return inFlightAction.current as Promise<T>;

    const promise = (async () => {
      setPendingAction(action);
      setLastAction(null);
      setError(null);
      retryAction.current = operation;
      try {
        return await operation();
      } catch (candidate) {
        setError(normalizeFlowError(candidate));
        setLastAction(action);
        throw candidate;
      } finally {
        setPendingAction(null);
        inFlightAction.current = null;
      }
    })();

    inFlightAction.current = promise;
    return promise;
  }, []);

  const saveConfiguration = useCallback(async (payload: WaitlistConfigurationPayload) => run("configuration", async () => {
    const entry = await client.createWaitlistEntry({
      attemptId: attemptId.current,
      name: payload.name,
      appearanceCatalogVersion: payload.appearance_catalog_version,
      appearanceKey: payload.appearance_key,
      job: payload.job,
      personality: payload.personality ?? "",
    });
    attemptToken.current = entry.attemptToken;
    const next: AllyPreviewSnapshot = {
      lifecycle: "greeting_ready",
      configuration: {
        name: payload.name,
        appearanceCatalogVersion: payload.appearance_catalog_version,
        appearanceKey: payload.appearance_key,
        job: payload.job,
        personality: payload.personality ?? null,
      },
      greeting: { text: entry.greeting },
      reply: null,
      join: null,
    };
    setSnapshot(next);
    captureWaitlistEvent("waitlist_ally_created");
    return next;
  }), [client, run]);

  const recordReply = useCallback(async (text: string) => {
    const reply = text.trim();
    if (!reply) throw new WaitlistMappingError("reply_required", "Write a reply first.");
    const next = { ...snapshot, lifecycle: "reply_pending" as const, reply: { text: reply, status: "pending" as const } };
    setSnapshot(next);
    return next;
  }, [snapshot]);

  const join = useCallback(async (email: string) => run("join", async () => {
    if (!attemptToken.current || !snapshot.reply || !consentVersion) {
      throw new WaitlistMappingError("waitlist_entry_incomplete", "Finish your Ally preview before joining.");
    }
    const confirmation = await client.completeWaitlistEntry({
      attemptToken: attemptToken.current,
      reply: snapshot.reply.text,
      email,
      consentVersion,
    });
    setSnapshot((current) => ({ ...current, lifecycle: "pending_claim", join: { email: confirmation.email } }));
    identifyWaitlistSubscriber(attemptId.current, email);
    captureWaitlistEvent("waitlist_joined");
    return confirmation;
  }), [client, consentVersion, run, snapshot.reply]);

  const retry = useCallback(async () => {
    if (retryAction.current && lastAction) await run(lastAction, retryAction.current);
  }, [lastAction, run]);

  const value = useMemo<WaitlistFlowValue>(() => ({
    completionMode: "waitlist",
    featureEnabled,
    consentVersion,
    status: featureEnabled ? (error ? "error" : "ready") : "disabled",
    snapshot,
    error,
    pendingAction,
    lastAction,
    saveConfiguration,
    recordReply,
    join,
    retry,
  }), [consentVersion, error, featureEnabled, join, lastAction, pendingAction, recordReply, retry, saveConfiguration, snapshot]);

  return <AllyPreviewFlowContext.Provider value={value}>{children}</AllyPreviewFlowContext.Provider>;
}

export function useAllyPreviewFlow(): AllyPreviewFlowValue {
  const value = useContext(AllyPreviewFlowContext);
  if (!value) throw new Error("useAllyPreviewFlow must be used within an Ally preview flow provider");
  return value;
}

export function useWaitlistFlow(): WaitlistFlowValue {
  const value = useAllyPreviewFlow();
  if (!value) throw new Error("useWaitlistFlow must be used within WaitlistFlowProvider");
  if (value.completionMode !== "waitlist" || !value.join) {
    throw new Error("useWaitlistFlow must be used within WaitlistFlowProvider");
  }
  return value as WaitlistFlowValue;
}

export function serializeOnboardingConfiguration(input: WaitlistConfigurationInput) {
  return serializeConfiguration(input);
}

export function waitlistGreetingFingerprint(name: string, job: string, personality: string | null): string {
  return greetingFingerprintForSerialized(name, job, personality);
}
