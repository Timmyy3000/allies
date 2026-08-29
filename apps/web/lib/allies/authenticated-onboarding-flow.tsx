"use client";

import { isCloudError, type AllyViewModel, type CloudError } from "@allies/cloud-client";
import { useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { useSession } from "../session/session-context";
import { useQueryClient } from "@tanstack/react-query";
import {
  AllyPreviewFlowContext,
  type AllyPreviewFlowValue,
  type AllyPreviewSnapshot,
} from "../waitlist/flow";
import { WaitlistMappingError, type WaitlistConfigurationPayload } from "../waitlist/catalog";
import { alliesQueryKey } from "./query-keys";

const EMPTY_SNAPSHOT: AllyPreviewSnapshot = {
  lifecycle: "configuring",
  configuration: {
    name: null,
    appearanceCatalogVersion: null,
    appearanceKey: null,
    job: null,
    personality: null,
  },
  greeting: null,
  reply: null,
  join: null,
};

function newIdempotencyKey(): string {
  return `ally-create-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;
}

function normalizeError(error: unknown): CloudError {
  if (isCloudError(error)) return error;
  if (error instanceof WaitlistMappingError) {
    return {
      kind: "validation",
      code: error.code,
      fieldIssues: [{ code: error.code, message: error.message }],
    };
  }
  return { kind: "network", code: "ally_onboarding_request_failed" };
}

export interface AuthenticatedAllyFlowProviderProps {
  workspaceId: string;
  onCreated: (ally: AllyViewModel) => void;
  children: ReactNode;
}

export function AuthenticatedAllyFlowProvider({
  workspaceId,
  onCreated,
  children,
}: AuthenticatedAllyFlowProviderProps) {
  const { client, runCloudOperation } = useSession();
  const queryClient = useQueryClient();
  const [snapshot, setSnapshot] = useState<AllyPreviewSnapshot>(EMPTY_SNAPSHOT);
  const [pendingAction, setPendingAction] = useState<"configuration" | "join" | null>(null);
  const [lastAction, setLastAction] = useState<"configuration" | "join" | null>(null);
  const [error, setError] = useState<CloudError | null>(null);
  const retryAction = useRef<(() => Promise<unknown>) | null>(null);
  const inFlightAction = useRef<Promise<unknown> | null>(null);
  const createIntent = useRef<{ signature: string; key: string } | null>(null);
  const attemptToken = useRef<string | null>(null);

  const run = useCallback(<T,>(
    action: "configuration" | "join",
    operation: () => Promise<T>,
  ): Promise<T> => {
    if (inFlightAction.current) return inFlightAction.current as Promise<T>;

    const promise = (async () => {
      setPendingAction(action);
      setLastAction(null);
      setError(null);
      retryAction.current = operation;
      try {
        return await operation();
      } catch (candidate) {
        setError(normalizeError(candidate));
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

  const saveConfiguration = useCallback(
    (payload: WaitlistConfigurationPayload) =>
      run("configuration", async () => {
        if (!payload.personality) {
          throw new WaitlistMappingError(
            "personality_required",
            "Choose an Ally personality.",
          );
        }
        const attempt = await runCloudOperation(
          (signal) =>
            client.beginOnboarding(
              {
                name: payload.name,
                job: payload.job,
                personality: payload.personality!,
                appearanceCatalogVersion: payload.appearance_catalog_version,
                appearanceKey: payload.appearance_key,
              },
              signal,
            ),
          { csrf: true },
        );
        attemptToken.current = attempt.attemptToken;
        const next: AllyPreviewSnapshot = {
          lifecycle: "greeting_ready",
          configuration: {
            name: payload.name,
            appearanceCatalogVersion: payload.appearance_catalog_version,
            appearanceKey: payload.appearance_key,
            job: payload.job,
            personality: payload.personality,
          },
          greeting: { text: attempt.greeting },
          reply: null,
          join: null,
        };
        setSnapshot(next);
        return next;
      }),
    [client, run, runCloudOperation],
  );

  const recordReply = useCallback(
    (text: string) => {
      const reply = text.trim();
      if (!reply) {
        return Promise.reject(
          new WaitlistMappingError("reply_required", "Write a reply first."),
        );
      }
      const configuration = snapshot.configuration;
      if (
        !configuration.name ||
        !configuration.job ||
        !configuration.personality ||
        !configuration.appearanceCatalogVersion ||
        !configuration.appearanceKey
      ) {
        return Promise.reject(
          new WaitlistMappingError(
            "onboarding_configuration_missing",
            "Finish shaping your Ally before replying.",
          ),
        );
      }

      const signature = JSON.stringify({ workspaceId, configuration, reply });
      const key =
        createIntent.current?.signature === signature
          ? createIntent.current.key
          : newIdempotencyKey();
      createIntent.current = { signature, key };
      setSnapshot((current) => ({
        ...current,
        lifecycle: "reply_pending",
        reply: { text: reply, status: "pending" },
        join: null,
      }));

      return run("join", async () => {
        const onboardingAttempt = attemptToken.current;
        if (!onboardingAttempt) {
          throw new WaitlistMappingError(
            "onboarding_attempt_missing",
            "Start your Ally preview before replying.",
          );
        }
        const ally = await runCloudOperation(
          (signal) =>
            client.createAlly(
              workspaceId,
              {
                name: configuration.name!,
                job: configuration.job!,
                personality: configuration.personality!,
                appearanceCatalogVersion: configuration.appearanceCatalogVersion!,
                appearanceKey: configuration.appearanceKey!,
                onboardingAttempt,
                reply,
              },
              key,
              signal,
            ),
          { csrf: true },
        );
        setSnapshot((current) => ({
          ...current,
          lifecycle: "pending_claim",
          reply: { text: reply, status: "pending" },
        }));
        await queryClient.invalidateQueries({ queryKey: alliesQueryKey(workspaceId) });
        onCreated(ally);
        const next: AllyPreviewSnapshot = {
          ...snapshot,
          lifecycle: "pending_claim",
          reply: { text: reply, status: "pending" as const },
        };
        return next;
      });
    }, [client, onCreated, queryClient, run, runCloudOperation, snapshot, workspaceId],
  );

  const retry = useCallback(async () => {
    if (retryAction.current && lastAction) {
      await run(lastAction, retryAction.current);
    }
  }, [lastAction, run]);

  const value = useMemo<AllyPreviewFlowValue>(
    () => ({
      completionMode: "authenticated",
      featureEnabled: true,
      consentVersion: null,
      status: error ? "error" : "ready",
      snapshot,
      error,
      pendingAction,
      lastAction,
      saveConfiguration,
      recordReply,
      retry,
    }),
    [error, lastAction, pendingAction, recordReply, retry, saveConfiguration, snapshot],
  );

  return (
    <AllyPreviewFlowContext.Provider value={value}>
      {children}
    </AllyPreviewFlowContext.Provider>
  );
}

export function useAuthenticatedAllyFlow(): AllyPreviewFlowValue {
  const value = useContext(AllyPreviewFlowContext);
  if (!value || value.completionMode !== "authenticated") {
    throw new Error(
      "useAuthenticatedAllyFlow must be used within AuthenticatedAllyFlowProvider",
    );
  }
  return value;
}
