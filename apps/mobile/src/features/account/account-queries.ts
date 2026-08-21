import {
  type AccountViewModel,
  type AvatarViewModel,
  type CloudError,
  type ProfileViewModel,
  type WorkspaceViewModel,
} from '@allies/cloud-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';

import { useNativeSession } from '@/lib/session/session-context';

import { profileFormSchema } from './profile-schema';

export const accountKeys = {
  avatar: ['account', 'avatar'] as const,
  current: ['account', 'current'] as const,
  workspace: (workspaceId: string) => ['account', 'workspace', workspaceId] as const,
};

function accountUnavailable(): CloudError {
  return { kind: 'client', code: 'account_unavailable' };
}

function useAccountRequest<T>(request: () => Promise<T>, enabled: boolean): UseQueryResult<T, CloudError> {
  return useQuery({
    queryKey: accountKeys.current,
    queryFn: request,
    enabled,
  });
}

export function useCurrentAccount(): UseQueryResult<AccountViewModel, CloudError> {
  const session = useNativeSession();
  const enabled = session.status === 'signed-in' && Boolean(session.accountClient && session.adapter);

  return useAccountRequest(
    () => {
      if (!session.accountClient || !session.adapter) return Promise.reject(accountUnavailable());
      return session.adapter.withRefresh(() => session.accountClient!.getCurrentAccount());
    },
    enabled,
  );
}

export function useWorkspace(workspaceId: string): UseQueryResult<WorkspaceViewModel, CloudError> {
  const session = useNativeSession();
  const enabled = Boolean(workspaceId && session.status === 'signed-in' && session.accountClient && session.adapter);

  return useQuery({
    queryKey: accountKeys.workspace(workspaceId),
    queryFn: () => {
      if (!session.accountClient || !session.adapter) return Promise.reject(accountUnavailable());
      return session.adapter.withRefresh(() => session.accountClient!.getWorkspace(workspaceId));
    },
    enabled,
  });
}

export function useUpdateProfile() {
  const session = useNativeSession();
  const queryClient = useQueryClient();

  return useMutation<ProfileViewModel, CloudError, { displayName: string }>({
    mutationFn: async (input) => {
      const values = profileFormSchema.parse(input);
      if (!session.accountClient || !session.adapter) throw accountUnavailable();
      return session.adapter.withRefresh(() => session.accountClient!.updateProfile(values.displayName));
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: accountKeys.current });
    },
  });
}

export function useAvatar(): UseQueryResult<AvatarViewModel, CloudError> {
  const session = useNativeSession();
  const enabled = session.status === 'signed-in' && Boolean(session.accountClient && session.adapter);

  return useQuery({
    queryKey: accountKeys.avatar,
    queryFn: () => {
      if (!session.accountClient || !session.adapter) return Promise.reject(accountUnavailable());
      return session.adapter.withRefresh(() => session.accountClient!.getAvatarRead());
    },
    enabled,
  });
}

export function useDeleteAvatar() {
  const session = useNativeSession();
  const queryClient = useQueryClient();

  return useMutation<void, CloudError>({
    mutationFn: async () => {
      if (!session.accountClient || !session.adapter) throw accountUnavailable();
      await session.adapter.withRefresh(() => session.accountClient!.deleteAvatar());
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: accountKeys.current }),
        queryClient.invalidateQueries({ queryKey: accountKeys.avatar }),
      ]);
    },
  });
}
