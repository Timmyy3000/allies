import { describe, expect, it, vi } from 'vitest';

import { createMobileCloudClient, isAuthenticatedCloudRequest } from './native-cloud-client';

const accountResponse = {
  status: 'success',
  message: 'Account loaded',
  data: {
    user: { id: 'usr_example' },
    profile: { display_name: 'Example User', avatar_url: null },
    session: { id: 'ses_example', expires_at: '2026-08-21T12:00:00Z' },
    workspace: { id: 'wsp_example', name: 'Personal Workspace', role: 'owner', capabilities: [] },
  },
};

describe('createMobileCloudClient', () => {
  it.each([
    ['POST', 'https://cloud.example.com/api/v1/workspaces/workspace/allies'],
    ['GET', 'https://cloud.example.com/api/v1/workspaces/workspace/allies/ally'],
    ['GET', 'https://cloud.example.com/api/v1/workspaces/workspace/allies/ally/conversation'],
    ['GET', 'https://cloud.example.com/api/v1/workspaces/workspace/conversations/conversation'],
    ['GET', 'https://cloud.example.com/api/v1/workspaces/workspace/conversations/conversation/activities'],
    ['POST', 'https://cloud.example.com/api/v1/workspaces/workspace/conversations/conversation/messages'],
  ])('classifies %s %s as authenticated', (method, url) => {
    expect(isAuthenticatedCloudRequest(new Request(url, { method }))).toBe(true);
  });

  it.each([
    ['POST', 'https://cloud.example.com/api/v1/onboarding/attempts'],
    ['GET', 'https://cloud.example.com/api/v1/workspaces/workspace/allies'],
    ['POST', 'https://cloud.example.com/api/v1/workspaces/workspace/allies/ally'],
    ['POST', 'https://cloud.example.com/api/v1/workspaces/workspace/conversations/conversation'],
    ['GET', 'https://cloud.example.com/api/v1/workspaces/workspace/conversations/conversation/messages'],
  ])('does not classify %s %s as authenticated', (method, url) => {
    expect(isAuthenticatedCloudRequest(new Request(url, { method }))).toBe(false);
  });

  it('adds bearer credentials only to authenticated Cloud routes', async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      expect(request.credentials).toBe('omit');
      expect(request.headers.get('authorization')).toBe('Bearer access-example');
      return Response.json(accountResponse);
    });
    const client = createMobileCloudClient({
      cloudApiUrl: 'https://cloud.example.com',
      nativeAuthRedirectUri: 'https://mobile.example/auth/return',
      fetch,
    });

    client.setAccessToken('access-example');
    await expect(client.getCurrentAccount()).resolves.toMatchObject({ userId: 'usr_example' });
  });

  it('does not attach bearer credentials to native auth requests', async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      expect(request.credentials).toBe('omit');
      expect(request.headers.get('authorization')).toBeNull();
      return Response.json({
        status: 'success',
        message: 'Native sign-in started',
        data: {
          authorization_url: 'https://accounts.google.com/o/oauth2/auth',
          expires_at: '2026-08-21T12:00:00Z',
        },
      });
    });
    const client = createMobileCloudClient({
      cloudApiUrl: 'https://cloud.example.com',
      nativeAuthRedirectUri: 'https://mobile.example/auth/return',
      fetch,
    });

    client.setAccessToken('access-example');
    await expect(client.beginGoogleSignIn({
      redirectUri: 'https://mobile.example/auth/return',
      codeChallenge: 'a'.repeat(43),
      state: 'state-example',
    })).resolves.toMatchObject({ authorizationUrl: 'https://accounts.google.com/o/oauth2/auth' });
  });

  it('does not attach bearer credentials to unlisted account paths or methods', async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      expect(request.credentials).toBe('omit');
      expect(request.headers.get('authorization')).toBeNull();
      return Response.json({ status: 'success', message: 'ok', data: {} });
    });
    const client = createMobileCloudClient({
      cloudApiUrl: 'https://cloud.example.com',
      nativeAuthRedirectUri: 'https://mobile.example/auth/return',
      fetch,
    });

    client.setAccessToken('access-example');
    await expect(client.account.getWorkspace('')).rejects.toMatchObject({ kind: 'contract' });
  });
});
