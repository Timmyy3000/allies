import { describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";

import type { AvatarViewModel, CloudClient } from "@allies/cloud-client";
import {
  AVATAR_READ_QUERY_KEY,
  CURRENT_ACCOUNT_QUERY_KEY,
  avatarReadQueryOptions,
  currentAccountQueryOptions,
  removePrivateAccountQueries,
} from "./account-query";

const account = {
  userId: "usr_example",
  displayName: "Example User",
  avatarUrl: null,
  session: { id: "ses_example", expiresAt: "2026-08-13T12:00:00Z" },
  workspace: { id: "wsp_example", name: "Personal Workspace", role: "owner", capabilities: [] },
};

const avatar: AvatarViewModel = {
  assetId: "avt_example",
  url: "https://media.example/avatar",
  expiresAt: "2026-08-13T12:01:00Z",
};

describe("account query options", () => {
  it("uses the shared operation runner and query-owned account key", async () => {
    const getCurrentAccount = vi.fn(async () => account);
    const runCloudOperation = vi.fn(
      async <T>(operation: (signal?: AbortSignal) => Promise<T>) => operation(),
    ) as unknown as Parameters<typeof currentAccountQueryOptions>[1];
    const options = currentAccountQueryOptions(
      { getCurrentAccount } as Pick<CloudClient, "getCurrentAccount">,
      runCloudOperation,
    );

    const queryFn = options.queryFn as Exclude<typeof options.queryFn, symbol>;
    if (typeof queryFn !== "function") throw new Error("queryFn missing");
    await expect(queryFn({ queryKey: options.queryKey, signal: new AbortController().signal } as never))
      .resolves.toEqual(account);
    expect(options.queryKey).toEqual(CURRENT_ACCOUNT_QUERY_KEY);
    expect(getCurrentAccount).toHaveBeenCalledOnce();
  });

  it("renews observed signed avatar metadata before expiry and stops after an error", () => {
    const options = avatarReadQueryOptions(
      { getAvatarRead: vi.fn(async () => avatar) } as Pick<CloudClient, "getAvatarRead">,
      vi.fn() as never,
    );
    const query = {
      state: {
        data: avatar,
        errorUpdatedAt: 0,
        dataUpdatedAt: 1,
      },
    } as never;

    expect(options.queryKey).toEqual(AVATAR_READ_QUERY_KEY);
    expect(typeof options.refetchInterval === "function" ? options.refetchInterval(query) : undefined)
      .toBeGreaterThanOrEqual(1_000);
    expect(options.refetchIntervalInBackground).toBe(true);
    expect(typeof options.refetchInterval === "function" ? options.refetchInterval({
      state: { data: avatar, errorUpdatedAt: 2, dataUpdatedAt: 1 },
    } as never) : undefined).toBe(false);
  });

  it("removes only private account queries", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(CURRENT_ACCOUNT_QUERY_KEY, account);
    queryClient.setQueryData(AVATAR_READ_QUERY_KEY, avatar);
    queryClient.setQueryData(["waitlist", "entry"], { greeting: "Hello" });

    removePrivateAccountQueries(queryClient);

    expect(queryClient.getQueryData(CURRENT_ACCOUNT_QUERY_KEY)).toBeUndefined();
    expect(queryClient.getQueryData(AVATAR_READ_QUERY_KEY)).toBeUndefined();
    expect(queryClient.getQueryData(["waitlist", "entry"])).toEqual({ greeting: "Hello" });
  });
});
