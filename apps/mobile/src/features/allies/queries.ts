import type { AllyViewModel, CloudError, MessageViewModel } from '@allies/cloud-client';
import { useQueries, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { useMemo, useRef } from 'react';

import { useNativeSession } from '@/lib/session/session-context';

const PROVISIONING_REFETCH_INTERVAL_MS = 1_000;
const PROVISIONING_REFETCH_LIMIT = 120;
const ROSTER_PREVIEW_LIMIT = 32;

export const allyKeys = {
  all: (workspaceId: string) => ['allies', workspaceId] as const,
  detail: (workspaceId: string, allyId: string) => ['allies', workspaceId, allyId] as const,
  conversation: (workspaceId: string, allyId: string) => ['allies', 'conversation', workspaceId, allyId] as const,
};

function accountUnavailable(): CloudError {
  return { kind: 'client', code: 'account_unavailable' };
}

export function useAllies(): UseQueryResult<AllyViewModel[], CloudError> {
  const session = useNativeSession();
  const workspaceId = session.account?.workspace.id ?? '';
  const provisioningRefetches = useRef(0);
  const enabled = session.status === 'signed-in'
    && Boolean(workspaceId && session.accountClient && session.adapter);

  return useQuery({
    queryKey: allyKeys.all(workspaceId),
    enabled,
    queryFn: ({ signal }) => {
      if (!session.accountClient || !session.adapter) return Promise.reject(accountUnavailable());
      return session.adapter.withRefresh(() => session.accountClient!.listAllies(workspaceId, signal));
    },
    refetchInterval: (query) => {
      const hasPendingAlly = query.state.data?.some((ally) => ally.provisioningState === 'pending') ?? false;
      if (!hasPendingAlly) {
        provisioningRefetches.current = 0;
        return false;
      }
      if (provisioningRefetches.current >= PROVISIONING_REFETCH_LIMIT) return false;
      provisioningRefetches.current += 1;
      return PROVISIONING_REFETCH_INTERVAL_MS;
    },
    refetchIntervalInBackground: false,
  });
}

export function useAlly(allyId: string | null): UseQueryResult<AllyViewModel, CloudError> {
  const session = useNativeSession();
  const workspaceId = session.account?.workspace.id ?? '';
  const enabled = session.status === 'signed-in'
    && Boolean(allyId && workspaceId && session.accountClient && session.adapter);

  return useQuery({
    queryKey: allyKeys.detail(workspaceId, allyId ?? ''),
    enabled,
    queryFn: ({ signal }) => {
      if (!allyId || !session.accountClient || !session.adapter) return Promise.reject(accountUnavailable());
      return session.adapter.withRefresh(() => session.accountClient!.getAlly(workspaceId, allyId, signal));
    },
  });
}

export function useAllyPreviews(
  workspaceId: string,
  allies: readonly AllyViewModel[],
): Map<string, { latestMessage: MessageViewModel | null; isPending: boolean; isError: boolean }> {
  const session = useNativeSession();
  const queries = useQueries({
    queries: allies.slice(0, ROSTER_PREVIEW_LIMIT).map((ally) => ({
      queryKey: [...allyKeys.conversation(workspaceId, ally.id), 'preview'] as const,
      enabled: Boolean(workspaceId && session.status === 'signed-in' && session.accountClient && session.adapter),
      queryFn: ({ signal }: { signal: AbortSignal }) => {
        if (!session.accountClient || !session.adapter) return Promise.reject(accountUnavailable());
        return session.adapter.withRefresh(() => session.accountClient!.getAllyConversation(workspaceId, ally.id, {
          limit: 1,
          signal,
        }));
      },
      retry: false,
      staleTime: 30_000,
    })),
  });

  return useMemo(() => new Map(allies.slice(0, ROSTER_PREVIEW_LIMIT).map((ally, index) => {
    const query = queries[index];
    const messages = query?.data?.messages ?? [];
    const latestMessage = messages.reduce<MessageViewModel | null>(
      (latest, message) => (!latest || message.sequence > latest.sequence ? message : latest),
      null,
    );
    return [ally.id, {
      latestMessage,
      isPending: Boolean(query?.isPending),
      isError: Boolean(query?.isError),
    }] as const;
  })), [allies, queries]);
}

export function formatAllyTime(createdAt: string | undefined): string {
  if (!createdAt) return '';
  const timestamp = Date.parse(createdAt);
  if (Number.isNaN(timestamp)) return '';
  return new Date(timestamp).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}
