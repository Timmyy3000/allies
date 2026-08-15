"use client";

import type { CloudClient } from "@allies/cloud-client";
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { createWebSessionAdapter, type LogoutResult, type SessionState } from "./web-session";

type RootSessionState = { status: "unknown" | "restoring" } | SessionState;

interface SessionContextValue {
  client: CloudClient;
  state: RootSessionState;
  restore(): Promise<void>;
  logout(): Promise<LogoutResult>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  client,
  children,
  restoreOnMount = true,
}: {
  client: CloudClient;
  children: ReactNode;
  restoreOnMount?: boolean;
}) {
  const adapter = useMemo(() => createWebSessionAdapter(client), [client]);
  const queryClient = useQueryClient();
  const [state, setState] = useState<RootSessionState>(() =>
    restoreOnMount ? { status: "restoring" } : { status: "signed-out" },
  );
  const operationGeneration = useRef(0);

  const restore = async () => {
    if (!restoreOnMount) {
      setState({ status: "signed-out" });
      return;
    }
    const restoreGeneration = ++operationGeneration.current;
    setState({ status: "restoring" });
    const nextState = await adapter.restore();
    if (restoreGeneration !== operationGeneration.current) return;
    if (nextState.status === "signed-out") queryClient.clear();
    setState(nextState);
  };

  const logout = async () => {
    const logoutGeneration = ++operationGeneration.current;
    const result = await adapter.logout();
    if (logoutGeneration !== operationGeneration.current) return result;
    queryClient.clear();
    setState(result);
    return result;
  };

  useEffect(() => {
    if (!restoreOnMount) return;
    const controller = new AbortController();
    const restoreGeneration = ++operationGeneration.current;
    void adapter.restore(controller.signal).then((nextState) => {
      if (!controller.signal.aborted && restoreGeneration === operationGeneration.current) {
        if (nextState.status === "signed-out") queryClient.clear();
        setState(nextState);
      }
    });
    return () => controller.abort();
  }, [adapter, queryClient, restoreOnMount]);

  return <SessionContext.Provider value={{ client, state, restore, logout }}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used within SessionProvider");
  return value;
}

export function useCloudClient(): CloudClient {
  return useSession().client;
}
