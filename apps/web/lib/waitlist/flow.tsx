"use client";

import {
  isCloudError,
  type CloudError,
  type WaitlistConfigurationInput as CloudWaitlistConfigurationInput,
  type WaitlistJoinConfirmationViewModel,
  type WaitlistSnapshotViewModel,
} from "@allies/cloud-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useOnboardingStore } from "../../app/(onboarding)/_store/onboarding-store";
import { useCloudClient } from "../session/session-context";
import {
  greetingFingerprintForSerialized,
  parsePersonality,
  serializeConfiguration,
  type WaitlistConfigurationInput,
  type WaitlistConfigurationPayload,
  type WaitlistShape,
  WAITLIST_COLORS,
  WAITLIST_SHAPES,
  WaitlistMappingError,
} from "./catalog";

const WAITLIST_QUERY_KEY = ["waitlist", "draft"] as const;
const GREETING_RECONCILIATION_DELAYS_MS = [250, 500, 1_000, 2_000] as const;

export type WaitlistAction = "configuration" | "greeting" | "reply" | "join";
export type WaitlistFlowStatus = "disabled" | "idle" | "loading" | "ready" | "error";

interface WaitlistFlowFailure {
  action: WaitlistAction;
  error: CloudError;
}

interface WaitlistFlowValue {
  featureEnabled: boolean;
  consentVersion: string | null;
  active: boolean;
  status: WaitlistFlowStatus;
  snapshot: WaitlistSnapshotViewModel | null;
  error: CloudError | null;
  pendingAction: WaitlistAction | null;
  lastAction: WaitlistAction | null;
  saveConfiguration(payload: WaitlistConfigurationPayload): Promise<WaitlistSnapshotViewModel>;
  generateGreeting(fingerprint: string): Promise<WaitlistSnapshotViewModel>;
  recordReply(text: string): Promise<WaitlistSnapshotViewModel>;
  join(email: string): Promise<WaitlistJoinConfirmationViewModel>;
  refreshDraft(): Promise<WaitlistSnapshotViewModel | null>;
  retry(): Promise<void>;
}

const WaitlistFlowContext = createContext<WaitlistFlowValue | null>(null);

function localError(code: string, message: string): CloudError {
  return { kind: "client", code, fieldIssues: [{ code, message }] };
}

function normalizeFlowError(error: unknown): CloudError {
  if (isCloudError(error)) return error;
  if (error instanceof WaitlistMappingError) {
    return {
      kind: "validation",
      code: error.code,
      fieldIssues: [{ code: error.code, message: error.message }],
    };
  }
  return { kind: "network", code: "waitlist_request_failed" };
}

function newIdempotencyKey(counter: number): string {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  return randomUuid ? `int-009-${randomUuid}` : `int-009-${Date.now()}-${counter}`;
}

function decodeAppearance(
  appearanceKey: string | null,
  fallbackShape: WaitlistShape,
  fallbackColor: string | null,
): { shape: WaitlistShape; color: string | null } {
  if (!appearanceKey) return { shape: fallbackShape, color: fallbackColor };
  const [shape, hex] = appearanceKey.split(":");
  const color = `#${hex ?? ""}`.toLowerCase();
  if (
    WAITLIST_SHAPES.includes(shape as WaitlistShape) &&
    WAITLIST_COLORS.includes(color as (typeof WAITLIST_COLORS)[number])
  ) {
    return { shape: shape as WaitlistShape, color };
  }
  return { shape: fallbackShape, color: fallbackColor };
}

function greetingReconciliationKey(snapshot: WaitlistSnapshotViewModel): string {
  return JSON.stringify([
    snapshot.id,
    snapshot.configuration.name,
    snapshot.configuration.job,
    snapshot.configuration.personality,
  ]);
}

function generationOutcomeUnknown(): CloudError {
  return localError("generation_outcome_unknown", "Your Ally is still preparing a hello. Try again shortly.");
}

function waitForGreetingReconciliationDelay(delayMs: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}

export function WaitlistFlowProvider({
  featureEnabled,
  consentVersion,
  children,
}: {
  featureEnabled: boolean;
  consentVersion: string | null;
  children: ReactNode;
}) {
  const client = useCloudClient();
  const queryClient = useQueryClient();
  const active = useOnboardingStore((state) => state.step !== "welcome");
  const hydrate = useOnboardingStore((state) => state.hydrate);
  const goTo = useOnboardingStore((state) => state.goTo);
  const fallbackShape = useOnboardingStore((state) => state.shape);
  const fallbackColor = useOnboardingStore((state) => state.color);
  const [pendingAction, setPendingAction] = useState<WaitlistAction | null>(null);
  const [failure, setFailure] = useState<WaitlistFlowFailure | null>(null);
  const pendingActionRef = useRef<WaitlistAction | null>(null);
  const failureRef = useRef<WaitlistFlowFailure | null>(null);
  const bootstrapCompleteRef = useRef(false);
  const operationCounter = useRef(0);
  const operationKeys = useRef(new Map<string, { fingerprint: string; key: string }>());
  const lastOperationsRef = useRef(new Map<WaitlistAction, () => Promise<unknown>>());
  const greetingReconciliationRef = useRef<{
    key: string;
    authoritativeFirstRead: boolean;
    promise: Promise<WaitlistSnapshotViewModel>;
  } | null>(null);
  const hydratedSnapshotRef = useRef<string | null>(null);
  const hasEnteredFlowRef = useRef(false);

  const idempotencyKey = useCallback((operation: string, fingerprint: string): string => {
    const existing = operationKeys.current.get(operation);
    if (existing?.fingerprint === fingerprint) return existing.key;
    operationCounter.current += 1;
    const key = newIdempotencyKey(operationCounter.current);
    operationKeys.current.set(operation, { fingerprint, key });
    return key;
  }, []);

  const clearIdempotencyKey = useCallback((operation: string, fingerprint: string) => {
    const current = operationKeys.current.get(operation);
    if (current?.fingerprint === fingerprint) operationKeys.current.delete(operation);
  }, []);

  const ensureDraft = useCallback(
    async (signal: AbortSignal | undefined, createIfMissing: boolean): Promise<WaitlistSnapshotViewModel | null> => {
      if (!bootstrapCompleteRef.current) {
        await client.getWaitlistSession(signal);
        try {
          const existing = await client.getWaitlistDraft(signal);
          clearIdempotencyKey("bootstrap", "anonymous-draft");
          bootstrapCompleteRef.current = true;
          return existing;
        } catch (candidate) {
          if (!isCloudError(candidate) || candidate.kind !== "not-found" || !createIfMissing) throw candidate;
          const fingerprint = "anonymous-draft";
          const key = idempotencyKey("bootstrap", fingerprint);
          await client.createWaitlistDraft(key, signal);
          const existing = await client.getWaitlistDraft(signal);
          clearIdempotencyKey("bootstrap", fingerprint);
          bootstrapCompleteRef.current = true;
          return existing;
        }
      }

      try {
        const existing = await client.getWaitlistDraft(signal);
        clearIdempotencyKey("bootstrap", "anonymous-draft");
        return existing;
      } catch (candidate) {
        if (!createIfMissing || !isCloudError(candidate) || candidate.kind !== "not-found") throw candidate;
        const fingerprint = "anonymous-draft";
        const key = idempotencyKey("bootstrap", fingerprint);
        await client.createWaitlistDraft(key, signal);
        const existing = await client.getWaitlistDraft(signal);
        clearIdempotencyKey("bootstrap", fingerprint);
        return existing;
      }
    },
    [clearIdempotencyKey, client, idempotencyKey],
  );

  const queryMode = active ? "flow" : "landing";
  const queryKey = useMemo(() => [...WAITLIST_QUERY_KEY, queryMode] as const, [queryMode]);
  const draftQuery = useQuery<WaitlistSnapshotViewModel | null, unknown>({
    queryKey,
    enabled: featureEnabled,
    queryFn: ({ signal }) => ensureDraft(signal, active),
  });
  const snapshot = draftQuery.data ?? null;

  const fetchDraft = useCallback(
    async (cancelInFlight: boolean): Promise<WaitlistSnapshotViewModel | null> => {
      if (cancelInFlight) await queryClient.cancelQueries({ queryKey, exact: true });
      return queryClient.fetchQuery<WaitlistSnapshotViewModel | null, unknown>({
        queryKey,
        queryFn: ({ signal }) => ensureDraft(signal, true),
        // Mutations need a server-authoritative snapshot, even while the normal query remains fresh.
        staleTime: 0,
      });
    },
    [ensureDraft, queryClient, queryKey],
  );

  const refreshDraft = useCallback(() => fetchDraft(true), [fetchDraft]);
  const refreshDraftForReconciliation = useCallback(() => fetchDraft(false), [fetchDraft]);

  useEffect(() => {
    if (active) {
      hasEnteredFlowRef.current = true;
      return;
    }
    if (
      hasEnteredFlowRef.current ||
      !snapshot ||
      hydratedSnapshotRef.current === `${snapshot.id}:${snapshot.revision}`
    ) {
      return;
    }
    const appearance = decodeAppearance(snapshot.configuration.appearanceKey, fallbackShape, fallbackColor);
    const personality = parsePersonality(snapshot.configuration.personality);
    hydrate({
      name: snapshot.configuration.name ?? "",
      shape: appearance.shape,
      color: appearance.color,
      job: snapshot.configuration.job ?? "",
      personalities: personality.personalities,
      personalityNote: personality.personalityNote,
      personalityRaw: snapshot.configuration.personality,
    });
    hydratedSnapshotRef.current = `${snapshot.id}:${snapshot.revision}`;
    goTo("preview");
  }, [active, fallbackColor, fallbackShape, goTo, hydrate, snapshot]);

  const clearFailure = useCallback((action: WaitlistAction) => {
    if (failureRef.current?.action === action) failureRef.current = null;
    setFailure((current) => (current?.action === action ? null : current));
  }, []);

  const recordFailure = useCallback((action: WaitlistAction, error: CloudError) => {
    const nextFailure = { action, error };
    failureRef.current = nextFailure;
    setFailure(nextFailure);
  }, []);

  const reconcileGreeting = useCallback(
    async (
      seed: WaitlistSnapshotViewModel,
      authoritativeFirstRead = false,
    ): Promise<WaitlistSnapshotViewModel> => {
      const key = greetingReconciliationKey(seed);
      const current = greetingReconciliationRef.current;
      if (current?.key === key && (!authoritativeFirstRead || current.authoritativeFirstRead)) {
        return current.promise;
      }

      const promise = (async () => {
        let next = await (authoritativeFirstRead ? refreshDraft() : refreshDraftForReconciliation());
        for (const delayMs of GREETING_RECONCILIATION_DELAYS_MS) {
          if (next?.greeting || next?.lifecycle !== "greeting_pending") break;
          await waitForGreetingReconciliationDelay(delayMs);
          next = await refreshDraftForReconciliation();
        }
        if (!next) throw localError("draft_not_ready", "Your Ally draft could not be restored.");
        return next;
      })();

      const entry = { key, authoritativeFirstRead, promise };
      greetingReconciliationRef.current = entry;
      try {
        return await promise;
      } finally {
        if (greetingReconciliationRef.current === entry) greetingReconciliationRef.current = null;
      }
    },
    [refreshDraft, refreshDraftForReconciliation],
  );

  const ensureGreetingOutcome = useCallback((next: WaitlistSnapshotViewModel): WaitlistSnapshotViewModel => {
    if (!next.greeting) throw generationOutcomeUnknown();
    return next;
  }, []);

  const pendingGreetingKey =
    snapshot && !snapshot.greeting && snapshot.lifecycle === "greeting_pending"
      ? greetingReconciliationKey(snapshot)
      : null;

  useEffect(() => {
    if (!featureEnabled || !active || !pendingGreetingKey) return;
    const current = queryClient.getQueryData<WaitlistSnapshotViewModel | null>(queryKey);
    if (!current) return;

    let cancelled = false;
    void reconcileGreeting(current)
      .then((next) => {
        if (cancelled) return;
        ensureGreetingOutcome(next);
        clearFailure("greeting");
        lastOperationsRef.current.delete("greeting");
      })
      .catch((candidate) => {
        if (cancelled) return;
        recordFailure("greeting", normalizeFlowError(candidate));
      });

    return () => {
      cancelled = true;
    };
  }, [
    active,
    clearFailure,
    ensureGreetingOutcome,
    featureEnabled,
    pendingGreetingKey,
    queryClient,
    queryKey,
    recordFailure,
    reconcileGreeting,
  ]);

  const runAction = useCallback(
    async <T,>(
      action: WaitlistAction,
      operation: string,
      fingerprint: string,
      task: (key: string) => Promise<T>,
    ): Promise<T> => {
      if (pendingActionRef.current) {
        throw localError("operation_in_flight", "Finish the current waitlist action first.");
      }
      const key = idempotencyKey(operation, fingerprint);
      pendingActionRef.current = action;
      setPendingAction(action);
      clearFailure(action);
      try {
        const result = await task(key);
        clearIdempotencyKey(operation, fingerprint);
        clearFailure(action);
        lastOperationsRef.current.delete(action);
        return result;
      } catch (candidate) {
        const normalized = normalizeFlowError(candidate);
        if (normalized.kind === "conflict") {
          await refreshDraft().catch(() => undefined);
        }
        const nextFailure = { action, error: normalized };
        failureRef.current = nextFailure;
        setFailure(nextFailure);
        throw normalized;
      } finally {
        pendingActionRef.current = null;
        setPendingAction(null);
      }
    },
    [clearFailure, clearIdempotencyKey, idempotencyKey, refreshDraft],
  );

  const saveConfiguration = useCallback(
    async (payload: WaitlistConfigurationPayload): Promise<WaitlistSnapshotViewModel> => {
      const execute = async () => {
        const current = queryClient.getQueryData<WaitlistSnapshotViewModel | null>(queryKey);
        if (!current) throw localError("draft_not_ready", "Your Ally draft is still loading.");
        const refreshed = await runAction("configuration", "configuration", JSON.stringify(payload), async (key) => {
          const input: CloudWaitlistConfigurationInput = {
            revision: current.revision,
            idempotencyKey: key,
            name: payload.name,
            appearanceCatalogVersion: payload.appearance_catalog_version,
            appearanceKey: payload.appearance_key,
            job: payload.job,
            ...(payload.personality !== undefined ? { personality: payload.personality } : {}),
          };
          await client.updateWaitlistConfiguration(input);
          const next = await refreshDraft();
          if (!next) throw localError("draft_not_ready", "Your Ally draft could not be restored.");
          return next;
        });
        return refreshed;
      };
      lastOperationsRef.current.set("configuration", execute);
      return execute();
    },
    [client, queryClient, queryKey, refreshDraft, runAction],
  );

  const generateGreeting = useCallback(
    async (fingerprint: string): Promise<WaitlistSnapshotViewModel> => {
      const execute = async () => {
        const current = queryClient.getQueryData<WaitlistSnapshotViewModel | null>(queryKey);
        if (!current) throw localError("draft_not_ready", "Your Ally draft is still loading.");
        const refreshed = await runAction("greeting", "greeting", fingerprint, async (key) => {
          await client.generateWaitlistGreeting({ revision: current.revision, idempotencyKey: key });
          return ensureGreetingOutcome(await reconcileGreeting(current, true));
        });
        return refreshed;
      };
      lastOperationsRef.current.set("greeting", execute);
      return execute();
    },
    [client, ensureGreetingOutcome, queryClient, queryKey, reconcileGreeting, runAction],
  );

  const recordReply = useCallback(
    async (text: string): Promise<WaitlistSnapshotViewModel> => {
      const execute = async () => {
        const current = queryClient.getQueryData<WaitlistSnapshotViewModel | null>(queryKey);
        if (!current) throw localError("draft_not_ready", "Your Ally draft is still loading.");
        const refreshed = await runAction("reply", "reply", text, async (key) => {
          await client.recordWaitlistReply({ revision: current.revision, idempotencyKey: key, text });
          const next = await refreshDraft();
          if (!next) throw localError("draft_not_ready", "Your Ally draft could not be restored.");
          return next;
        });
        return refreshed;
      };
      lastOperationsRef.current.set("reply", execute);
      return execute();
    },
    [client, queryClient, queryKey, refreshDraft, runAction],
  );

  const join = useCallback(
    async (email: string): Promise<WaitlistJoinConfirmationViewModel> => {
      const execute = async () => {
        if (!consentVersion) throw localError("consent_missing", "Joining is not available yet.");
        const current = queryClient.getQueryData<WaitlistSnapshotViewModel | null>(queryKey);
        if (!current) throw localError("draft_not_ready", "Your Ally draft is still loading.");
        return runAction("join", "join", `${email}\u0000${consentVersion}`, async (key) => {
          const confirmation = await client.joinWaitlist({
            revision: current.revision,
            idempotencyKey: key,
            email,
            consentVersion,
          });
          const refreshed = await refreshDraft();
          if (!refreshed) throw localError("draft_not_ready", "Your Ally draft could not be restored.");
          return confirmation;
        });
      };
      lastOperationsRef.current.set("join", execute);
      return execute();
    },
    [client, consentVersion, queryClient, queryKey, refreshDraft, runAction],
  );

  const retry = useCallback(async () => {
    const failedAction = failureRef.current?.action;
    if (failedAction === "greeting") {
      const current = queryClient.getQueryData<WaitlistSnapshotViewModel | null>(queryKey);
      if (current && !current.greeting && current.lifecycle === "greeting_pending") {
        try {
          ensureGreetingOutcome(await reconcileGreeting(current));
          clearFailure("greeting");
          lastOperationsRef.current.delete("greeting");
        } catch (candidate) {
          recordFailure("greeting", normalizeFlowError(candidate));
        }
        return;
      }
    }
    const operation = failedAction ? lastOperationsRef.current.get(failedAction) : undefined;
    if (operation) {
      await operation().then(() => undefined).catch(() => undefined);
      return;
    }
    await draftQuery.refetch().then(() => undefined).catch(() => undefined);
  }, [clearFailure, draftQuery, ensureGreetingOutcome, queryClient, queryKey, recordFailure, reconcileGreeting]);

  const status: WaitlistFlowStatus = !featureEnabled
    ? "disabled"
    : draftQuery.isPending || draftQuery.isFetching
      ? "loading"
      : draftQuery.error
        ? "error"
        : snapshot
          ? "ready"
          : "idle";

  const value = useMemo<WaitlistFlowValue>(
    () => ({
      featureEnabled,
      consentVersion,
      active,
      status,
      snapshot,
      error: failure?.error ?? (draftQuery.error ? normalizeFlowError(draftQuery.error) : null),
      pendingAction,
      lastAction: failure?.action ?? null,
      saveConfiguration,
      generateGreeting,
      recordReply,
      join,
      refreshDraft,
      retry,
    }),
    [
      active,
      consentVersion,
      draftQuery.error,
      featureEnabled,
      failure,
      generateGreeting,
      join,
      pendingAction,
      recordReply,
      refreshDraft,
      retry,
      saveConfiguration,
      snapshot,
      status,
    ],
  );

  return <WaitlistFlowContext.Provider value={value}>{children}</WaitlistFlowContext.Provider>;
}

export function useWaitlistFlow(): WaitlistFlowValue {
  const value = useContext(WaitlistFlowContext);
  if (!value) throw new Error("useWaitlistFlow must be used within WaitlistFlowProvider");
  return value;
}

export function waitlistGreetingFingerprint(
  name: string,
  job: string,
  personality: string | null,
): string {
  return greetingFingerprintForSerialized(name, job, personality);
}

export function serializeOnboardingConfiguration(input: WaitlistConfigurationInput): WaitlistConfigurationPayload {
  return serializeConfiguration(input);
}
