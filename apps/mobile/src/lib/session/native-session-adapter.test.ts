import { describe, expect, it, vi } from "vitest";

import type { AccountViewModel } from "@allies/cloud-client";

import {
  createNativeSessionAdapter,
  type NativeSessionClient,
} from "./native-session-adapter";
import type { NativeSessionStore } from "./secure-session-store";

const account: AccountViewModel = {
  userId: "usr_example",
  displayName: "Example User",
  avatarUrl: null,
  session: { id: "ses_example", expiresAt: "2026-08-21T12:00:00Z" },
  workspace: { id: "wsp_example", name: "Personal Workspace", role: "owner", capabilities: [] },
};

const sessionTokens = {
  tokenType: "Bearer" as const,
  accessToken: "access-example",
  expiresIn: 600,
  refreshToken: "refresh-next",
  refreshExpiresIn: 1209600,
  sessionId: "ses_example",
};

function createStore(refreshToken: string | null = null): NativeSessionStore & { refreshToken: string | null } {
  return {
    refreshToken,
    readRefresh: vi.fn(async function (this: NativeSessionStore & { refreshToken: string | null }) {
      return this.refreshToken;
    }),
    writeRefresh: vi.fn(async function (this: NativeSessionStore & { refreshToken: string | null }, token: string) {
      this.refreshToken = token;
    }),
    clear: vi.fn(async function (this: NativeSessionStore & { refreshToken: string | null }) {
      this.refreshToken = null;
    }),
  };
}

function createClient(overrides: Partial<NativeSessionClient> = {}): NativeSessionClient {
  return {
    setAccessToken: vi.fn(),
    beginGoogleSignIn: vi.fn(),
    exchangeGoogleCode: vi.fn(async () => sessionTokens),
    refreshSession: vi.fn(async () => sessionTokens),
    logout: vi.fn(async () => undefined),
    getCurrentAccount: vi.fn(async () => account),
    ...overrides,
  };
}

describe("createNativeSessionAdapter", () => {
  it("restores a refresh session and validates the account before signing in", async () => {
    const store = createStore("refresh-old");
    const client = createClient();
    const adapter = createNativeSessionAdapter(client, store);

    await expect(adapter.restore()).resolves.toEqual({ status: "signed-in", account });
    expect(client.refreshSession).toHaveBeenCalledWith("refresh-old", expect.anything());
    expect(store.writeRefresh).toHaveBeenCalledWith("refresh-next");
    expect(client.setAccessToken).toHaveBeenCalledWith("access-example");
  });

  it("serializes refresh rotation and shares one result across callers", async () => {
    const store = createStore("refresh-old");
    let resolveRefresh: ((value: typeof sessionTokens) => void) | undefined;
    const refresh = new Promise<typeof sessionTokens>((resolve) => { resolveRefresh = resolve; });
    const client = createClient({ refreshSession: vi.fn(() => refresh) });
    const adapter = createNativeSessionAdapter(client, store);

    const first = adapter.refresh();
    const second = adapter.refresh();
    resolveRefresh?.(sessionTokens);

    await expect(Promise.all([first, second])).resolves.toEqual([true, true]);
    expect(client.refreshSession).toHaveBeenCalledOnce();
    expect(store.writeRefresh).toHaveBeenCalledOnce();
  });

  it("does not become signed in when SecureStore rejects the rotated token", async () => {
    const store = createStore("refresh-old");
    store.writeRefresh = vi.fn(async () => { throw new Error("secure store unavailable"); });
    const client = createClient();
    const adapter = createNativeSessionAdapter(client, store);

    await expect(adapter.restore()).resolves.toMatchObject({ status: "unavailable", reason: "storage" });
    expect(client.setAccessToken).toHaveBeenLastCalledWith(null);
    expect(client.getCurrentAccount).not.toHaveBeenCalled();
  });

  it("clears local session material even when server logout is uncertain", async () => {
    const store = createStore("refresh-old");
    const client = createClient({ logout: vi.fn(async () => { throw { kind: "network" }; }) });
    const adapter = createNativeSessionAdapter(client, store);

    await expect(adapter.logout()).resolves.toEqual({
      status: "signed-out",
      serverConfirmed: false,
      localCleared: true,
    });
    expect(store.clear).toHaveBeenCalledOnce();
    expect(client.setAccessToken).toHaveBeenLastCalledWith(null);
  });

  it('invalidates the provider when a request is unauthorized and refresh is rejected', async () => {
    const store = createStore('refresh-old');
    const onSessionInvalidated = vi.fn();
    const client = createClient({
      refreshSession: vi.fn(async () => { throw { kind: 'unauthorized' }; }),
    });
    const adapter = createNativeSessionAdapter(client, store, { onSessionInvalidated });

    await expect(adapter.withRefresh(async () => { throw { kind: 'unauthorized' }; })).rejects.toMatchObject({
      kind: 'unauthorized',
    });
    expect(store.clear).toHaveBeenCalledOnce();
    expect(client.setAccessToken).toHaveBeenLastCalledWith(null);
    expect(onSessionInvalidated).toHaveBeenCalledOnce();
  });

  it('reports unavailable when SecureStore cannot delete the refresh token', async () => {
    const store = createStore('refresh-old');
    store.clear = vi.fn(async () => { throw new Error('secure store unavailable'); });
    const client = createClient();
    const adapter = createNativeSessionAdapter(client, store);

    await expect(adapter.logout()).resolves.toEqual({
      status: 'signed-out',
      serverConfirmed: true,
      localCleared: false,
    });
    expect(client.setAccessToken).toHaveBeenLastCalledWith(null);
  });

  it('classifies SecureStore read failures as unavailable during restore', async () => {
    const store = createStore('refresh-old');
    store.readRefresh = vi.fn(async () => { throw new Error('secure store unavailable'); });
    const client = createClient();
    const adapter = createNativeSessionAdapter(client, store);

    await expect(adapter.restore()).resolves.toMatchObject({ status: 'unavailable', reason: 'storage' });
    expect(client.getCurrentAccount).not.toHaveBeenCalled();
  });

  it('cancels bootstrap when sign-in starts before the refresh read finishes', async () => {
    let resolveRead: ((value: string | null) => void) | undefined;
    const store = createStore(null);
    store.readRefresh = vi.fn(() => new Promise<string | null>((resolve) => { resolveRead = resolve; }));
    const client = createClient();
    const adapter = createNativeSessionAdapter(client, store);

    const restore = adapter.restore();
    const signIn = adapter.completeSignIn({
      code: 'cloud-code',
      codeVerifier: 'verifier-example',
      redirectUri: 'https://mobile.example/auth/return',
    });
    resolveRead?.(null);

    await expect(signIn).resolves.toMatchObject({ status: 'signed-in' });
    await expect(restore).resolves.toEqual({ status: 'signed-out', reason: 'canceled' });
  });
});
