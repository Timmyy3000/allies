import {
  createCloudClient,
  createNativeAuthClient,
  type CloudClient,
  type NativeAuthClient,
} from '@allies/cloud-client';

import type { MobileEnvironment } from '../env';
import type { NativeSessionClient } from '../session/native-session-adapter';

export interface MobileCloudClient extends NativeSessionClient {
  account: CloudClient;
  nativeAuthRedirectUri: string | null;
}

export interface MobileCloudClientOptions extends MobileEnvironment {
  fetch?: typeof globalThis.fetch;
  timeoutMs?: number;
  maxJsonBytes?: number;
}

export function isAuthenticatedCloudRequest(request: Request): boolean {
  const pathname = new URL(request.url).pathname;
  const method = request.method.toUpperCase();

  return (
    (method === 'GET' && pathname === '/api/v1/auths/me') ||
    (method === 'PATCH' && pathname === '/api/v1/auths/me/profile') ||
    (method === 'POST' && pathname === '/api/v1/auths/me/avatar/uploads') ||
    (method === 'POST' && /^\/api\/v1\/auths\/me\/avatar\/[^/]+\/complete$/u.test(pathname)) ||
    (method === 'GET' && pathname === '/api/v1/auths/me/avatar/read') ||
    (method === 'DELETE' && pathname === '/api/v1/auths/me/avatar') ||
    (method === 'GET' && /^\/api\/v1\/workspaces\/[^/]+$/u.test(pathname)) ||
    (method === 'GET' && /^\/api\/v1\/workspaces\/[^/]+\/allies$/u.test(pathname)) ||
    (method === 'POST' && /^\/api\/v1\/workspaces\/[^/]+\/allies$/u.test(pathname)) ||
    (method === 'GET' && /^\/api\/v1\/workspaces\/[^/]+\/allies\/[^/]+$/u.test(pathname)) ||
    (method === 'GET' && /^\/api\/v1\/workspaces\/[^/]+\/allies\/[^/]+\/conversation$/u.test(pathname)) ||
    (method === 'GET' && /^\/api\/v1\/workspaces\/[^/]+\/conversations\/[^/]+$/u.test(pathname)) ||
    (method === 'GET' && /^\/api\/v1\/workspaces\/[^/]+\/conversations\/[^/]+\/activities$/u.test(pathname)) ||
    (method === 'POST' && /^\/api\/v1\/workspaces\/[^/]+\/conversations\/[^/]+\/messages$/u.test(pathname))
  );
}

export function createMobileCloudClient(options: MobileCloudClientOptions): MobileCloudClient {
  let accessToken: string | null = null;
  const fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
  const account = createCloudClient({
    baseUrl: options.cloudApiUrl,
    fetch,
    timeoutMs: options.timeoutMs,
    maxJsonBytes: options.maxJsonBytes,
    prepareRequest: (request) => {
      const headers = new Headers(request.headers);
      if (accessToken && isAuthenticatedCloudRequest(request)) {
        headers.set('authorization', `Bearer ${accessToken}`);
      }
      return new Request(request, { credentials: 'omit', headers });
    },
  });
  const nativeAuth: NativeAuthClient = createNativeAuthClient({
    baseUrl: options.cloudApiUrl,
    fetch,
    timeoutMs: options.timeoutMs,
    maxJsonBytes: options.maxJsonBytes,
  });

  return {
    ...nativeAuth,
    account,
    nativeAuthRedirectUri: options.nativeAuthRedirectUri,
    setAccessToken: (token) => {
      accessToken = token;
    },
    getCurrentAccount: account.getCurrentAccount,
  };
}
