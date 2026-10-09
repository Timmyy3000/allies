import { describe, expect, it, vi } from "vitest";

import type { CloudClient } from "@allies/cloud-client";
import {
  ALLY_ACTIVITY_REFETCH_INTERVAL_MS,
  ALLY_PROVISIONING_REFETCH_INTERVAL_MS,
  ALLY_PROVISIONING_REFETCH_LIMIT,
  alliesQueryOptions,
  conversationQueryKey,
} from "./queries";

describe("Ally query ownership", () => {
  it("scopes list and conversation keys to their Workspace", async () => {
    const listAllies = vi.fn(async () => []);
    const runCloudOperation = vi.fn(
      async <T>(operation: (signal?: AbortSignal) => Promise<T>) => operation(),
    ) as unknown as Parameters<typeof alliesQueryOptions>[1];
    const options = alliesQueryOptions(
      { listAllies } as Pick<CloudClient, "listAllies">,
      runCloudOperation,
      "workspace",
    );

    expect(options.queryKey).toEqual(["workspaces", "workspace", "allies"]);
    expect(conversationQueryKey("workspace", "ally")).toEqual([
      "workspaces",
      "workspace",
      "allies",
      "ally",
      "conversation",
    ]);
    const queryFn = options.queryFn;
    if (typeof queryFn !== "function") throw new Error("query function missing");
    await expect(queryFn({ signal: new AbortController().signal } as never)).resolves.toEqual([]);
    expect(listAllies).toHaveBeenCalledOnce();
  });

  it("refetches while any Ally is getting ready, then keeps the sleep state current", () => {
    const options = alliesQueryOptions(
      { listAllies: vi.fn(async () => []) } as Pick<CloudClient, "listAllies">,
      vi.fn() as never,
      "workspace",
    );
    const refetchInterval = options.refetchInterval;
    if (typeof refetchInterval !== "function") throw new Error("refetch interval missing");

    const pendingQuery = {
      state: {
        data: [{ provisioningState: "pending" }],
      },
    } as unknown as Parameters<typeof refetchInterval>[0];
    const retryableQuery = {
      state: {
        data: [{ provisioningState: "retryable" }],
      },
    } as unknown as Parameters<typeof refetchInterval>[0];
    const readyQuery = {
      state: {
        data: [{ provisioningState: "bound" }],
      },
    } as unknown as Parameters<typeof refetchInterval>[0];

    expect(refetchInterval(pendingQuery)).toBe(ALLY_PROVISIONING_REFETCH_INTERVAL_MS);
    expect(refetchInterval(retryableQuery)).toBe(ALLY_PROVISIONING_REFETCH_INTERVAL_MS);
    expect(refetchInterval(readyQuery)).toBe(ALLY_ACTIVITY_REFETCH_INTERVAL_MS);
    expect(refetchInterval(pendingQuery)).toBe(ALLY_PROVISIONING_REFETCH_INTERVAL_MS);
    for (let attempt = 1; attempt < ALLY_PROVISIONING_REFETCH_LIMIT; attempt += 1) {
      refetchInterval(pendingQuery);
    }
    expect(refetchInterval(pendingQuery)).toBe(ALLY_ACTIVITY_REFETCH_INTERVAL_MS);
  });
});
