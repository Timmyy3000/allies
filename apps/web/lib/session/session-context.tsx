"use client";

import { isCloudError, type CloudClient } from "@allies/cloud-client";
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { CURRENT_ACCOUNT_QUERY_KEY, removePrivateAccountQueries } from "../account/account-query";
import { createPushLifecycle, type PushLifecycle } from "../pwa/push-lifecycle";
import type { CloudCsrfTokenOwner } from "../cloud/csrf-token";
import { createWebSessionAdapter, type LogoutResult, type RunCloudOperation, type SessionState } from "./web-session";

type RootSessionState = { status: "unknown" | "restoring" } | SessionState;

export interface SessionContextValue {
  client: CloudClient;
  push?: PushLifecycle;
  state: RootSessionState;
  restore(): Promise<void>;
  logout(): Promise<LogoutResult & { pushCleanupConfirmed: boolean }>;
  runCloudOperation: ReturnType<typeof createWebSessionAdapter>["runCloudOperation"];
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  client,
  csrf,
  children,
}: {
  client: CloudClient;
  csrf: CloudCsrfTokenOwner;
  children: ReactNode;
}) {
  const adapter = useMemo(() => createWebSessionAdapter(client, csrf), [client, csrf]);
  const queryClient = useQueryClient();
  const [state, setState] = useState<RootSessionState>({ status: "unknown" });
  const operationGeneration = useRef(0);
  const push = useMemo(() => createPushLifecycle(client, adapter.runCloudOperation), [client, adapter]);
  useEffect(() => push.start(), [push]);

  const restore = useCallback(async () => {
    const restoreGeneration = ++operationGeneration.current;
    setState({ status: "restoring" });
    const nextState = await adapter.restore();
    if (restoreGeneration !== operationGeneration.current) return;
    if (nextState.status === "signed-in") {
      void push.recover(nextState.account);
      queryClient.setQueryData(CURRENT_ACCOUNT_QUERY_KEY, nextState.account);
      setState({ status: "signed-in" });
      return;
    }
    if (nextState.status === "signed-out") {
      await push.logout();
      if (restoreGeneration !== operationGeneration.current) return;
      removePrivateAccountQueries(queryClient);
    }
    setState(nextState);
  }, [adapter, queryClient, push]);

  const logout = useCallback(async () => {
    const logoutGeneration = ++operationGeneration.current;
    const pushCleanupConfirmed = await push.logout();
    if (logoutGeneration !== operationGeneration.current) return { status: "signed-out" as const, serverConfirmed: false, pushCleanupConfirmed };
    const result = { ...await adapter.logout(), pushCleanupConfirmed };
    if (logoutGeneration !== operationGeneration.current) return result;
    removePrivateAccountQueries(queryClient);
    setState({ status: "signed-out" });
    return result;
  }, [adapter, queryClient, push]);

  const runCloudOperation = useCallback<RunCloudOperation>(async (operation, options) => {
    const operationGenerationAtStart = operationGeneration.current;
    try {
      return await adapter.runCloudOperation(operation, options);
    } catch (error) {
      if (
        operationGenerationAtStart === operationGeneration.current
        && isCloudError(error)
        && (error.kind === "unauthorized" || error.status === 401)
      ) {
        const cleanupGeneration = ++operationGeneration.current;
        await push.logout();
        if (cleanupGeneration === operationGeneration.current) {
          removePrivateAccountQueries(queryClient);
          setState({ status: "signed-out" });
        }
      }
      throw error;
    }
  }, [adapter, queryClient, push]);

  const value = useMemo<SessionContextValue>(
    () => ({ client, push, state, restore, logout, runCloudOperation }),
    [client, push, logout, restore, runCloudOperation, state],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used within SessionProvider");
  return value;
}

export function useCloudClient(): CloudClient {
  return useSession().client;
}
