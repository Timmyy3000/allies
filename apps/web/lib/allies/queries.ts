import type { CloudClient } from "@allies/cloud-client";
import type { AllyViewModel } from "@allies/cloud-client";
import type { QueryObserverOptions } from "@tanstack/react-query";

import type { RunCloudOperation } from "../session/web-session";
import { alliesQueryKey } from "./query-keys";

export const ALLY_PROVISIONING_REFETCH_INTERVAL_MS = 1_000;
export const ALLY_PROVISIONING_REFETCH_LIMIT = 120;
// Routine and browser work starts without this client, so refresh to keep sleep current.
export const ALLY_ACTIVITY_REFETCH_INTERVAL_MS = 30_000;

export function alliesQueryOptions(
  client: Pick<CloudClient, "listAllies">,
  runCloudOperation: RunCloudOperation,
  workspaceId: string,
): QueryObserverOptions<
  AllyViewModel[],
  unknown,
  AllyViewModel[],
  AllyViewModel[],
  ReturnType<typeof alliesQueryKey>
> {
  let provisioningRefetches = 0;

  return {
    queryKey: alliesQueryKey(workspaceId),
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      runCloudOperation(
        (operationSignal) => client.listAllies(workspaceId, operationSignal),
        { signal },
      ),
    refetchInterval: (query) => {
      const hasPendingAlly = query.state.data?.some(
        (ally) => ally.provisioningState === "pending" || ally.provisioningState === "retryable",
      ) ?? false;
      if (!hasPendingAlly) {
        provisioningRefetches = 0;
        return ALLY_ACTIVITY_REFETCH_INTERVAL_MS;
      }
      if (provisioningRefetches >= ALLY_PROVISIONING_REFETCH_LIMIT) return ALLY_ACTIVITY_REFETCH_INTERVAL_MS;
      provisioningRefetches += 1;
      return ALLY_PROVISIONING_REFETCH_INTERVAL_MS;
    },
    refetchIntervalInBackground: false,
  };
}

export const conversationQueryKey = (workspaceId: string, allyId: string) =>
  ["workspaces", workspaceId, "allies", allyId, "conversation"] as const;
