import type { AllySettingsInput, AllyViewModel, CloudError, RoutineDiscoveryPage } from '@allies/cloud-client';
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import { useNativeSession } from '@/lib/session/session-context';

import { allyKeys } from './queries';

function accountUnavailable(): CloudError {
  return { kind: 'client', code: 'account_unavailable' };
}

export function useAllyRoutines(allyId: string): UseQueryResult<RoutineDiscoveryPage, CloudError> {
  const session = useNativeSession();
  const workspaceId = session.account?.workspace.id ?? '';
  return useQuery({
    queryKey: [...allyKeys.detail(workspaceId, allyId), 'routines'],
    enabled: session.status === 'signed-in' && Boolean(workspaceId && session.accountClient && session.adapter),
    queryFn: ({ signal }) => {
      if (!session.accountClient || !session.adapter) return Promise.reject(accountUnavailable());
      return session.adapter.withRefresh(() => session.accountClient!.listRoutines(workspaceId, { allyId, signal }));
    },
    retry: false,
  });
}

export function useUpdateAllySettings(allyId: string) {
  const session = useNativeSession();
  const queryClient = useQueryClient();
  const workspaceId = session.account?.workspace.id ?? '';

  return useMutation<AllyViewModel, CloudError, AllySettingsInput>({
    mutationFn: (input) => {
      if (!session.accountClient || !session.adapter) return Promise.reject(accountUnavailable());
      return session.adapter.withRefresh(() => session.accountClient!.updateAllySettings(workspaceId, allyId, input));
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(allyKeys.detail(workspaceId, allyId), updated);
      queryClient.setQueryData<AllyViewModel[]>(allyKeys.all(workspaceId), (allies) =>
        allies?.map((ally) => (ally.id === updated.id ? updated : ally)));
    },
    onError: (error) => {
      if (error.kind === 'conflict' || error.status === 409) {
        void queryClient.invalidateQueries({ queryKey: allyKeys.detail(workspaceId, allyId), exact: true });
        void queryClient.invalidateQueries({ queryKey: allyKeys.all(workspaceId), exact: true });
      }
    },
  });
}

export function allySettingsErrorMessage(error: CloudError | null, subject: 'label' | 'look'): string | null {
  if (!error) return null;
  if (error.kind === 'conflict' || error.status === 409) return 'This Ally changed elsewhere. We refreshed it. Try again.';
  if (error.kind === 'validation' || error.status === 422 || error.kind === 'bad-request') return `Check the ${subject} and try again.`;
  if (error.kind === 'unauthorized' || error.status === 401) return 'Your session has ended. Sign in again to continue.';
  if (error.kind === 'forbidden' || error.status === 403) return "You don't have permission to change this Ally.";
  return "We couldn't save that. Try again.";
}

export function normalizeAllyLabel(value: string): string {
  return value.trim().replace(/\s+/gu, ' ');
}

export function allyLabelError(value: string): string | null {
  if (/[\p{Cc}\p{Cf}]/u.test(value)) return 'Use a single-line label.';
  const label = normalizeAllyLabel(value);
  if (!label) return null;
  return [2, 3].includes(label.split(' ').length) ? null : 'Use two or three words.';
}
