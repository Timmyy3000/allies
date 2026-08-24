import type { AvatarViewModel, CloudClient, AccountViewModel } from "@allies/cloud-client";
import type { QueryClient, QueryObserverOptions } from "@tanstack/react-query";

import type { RunCloudOperation } from "../session/web-session";

export const CURRENT_ACCOUNT_QUERY_KEY = ["account", "current"] as const;
export const AVATAR_READ_QUERY_KEY = ["account", "avatar", "read"] as const;

export function currentAccountQueryOptions(
  client: Pick<CloudClient, "getCurrentAccount">,
  runCloudOperation: RunCloudOperation,
): QueryObserverOptions<
  AccountViewModel,
  unknown,
  AccountViewModel,
  AccountViewModel,
  typeof CURRENT_ACCOUNT_QUERY_KEY
> {
  return {
    queryKey: CURRENT_ACCOUNT_QUERY_KEY,
    queryFn: ({ signal }) =>
      runCloudOperation((operationSignal) => client.getCurrentAccount(operationSignal), { signal }),
  };
}

export function avatarReadQueryOptions(
  client: Pick<CloudClient, "getAvatarRead">,
  runCloudOperation: RunCloudOperation,
): QueryObserverOptions<AvatarViewModel, unknown, AvatarViewModel, AvatarViewModel, typeof AVATAR_READ_QUERY_KEY> {
  return {
    queryKey: AVATAR_READ_QUERY_KEY,
    queryFn: ({ signal }) => runCloudOperation((operationSignal) => client.getAvatarRead(operationSignal), { signal }),
    refetchInterval: (query) => {
      const avatar = query.state.data;
      if (!avatar?.url || !avatar.expiresAt || query.state.errorUpdatedAt > query.state.dataUpdatedAt) return false;
      const expiresAt = Date.parse(avatar.expiresAt);
      if (!Number.isFinite(expiresAt)) return false;
      return Math.max(1_000, expiresAt - Date.now() - 30_000);
    },
    refetchIntervalInBackground: true,
  };
}

export function removePrivateAccountQueries(queryClient: QueryClient): void {
  queryClient.removeQueries({ queryKey: ["account"] });
}
