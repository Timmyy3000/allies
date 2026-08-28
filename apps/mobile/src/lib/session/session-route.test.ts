import { describe, expect, it } from 'vitest';

import { getSessionRouteAction } from './session-route';

describe('getSessionRouteAction', () => {
  it.each([
    ['checking', '/', undefined],
    ['refreshing', '/allies/new', undefined],
    ['unavailable', '/account', undefined],
  ] as const)('does not redirect while the session is %s', (status, pathname, returnTo) => {
    expect(getSessionRouteAction(status, pathname, returnTo)).toBeNull();
  });

  it('keeps the auth return route exempt from redirects', () => {
    expect(getSessionRouteAction('signed-out', '/auth/return')).toBeNull();
    expect(getSessionRouteAction('signed-in', '/auth/return', '/allies/new/complete')).toBeNull();
  });

  it.each([
    ['/allies', '/sign-in?returnTo=%2Fallies'],
    ['/allies/new', '/sign-in?returnTo=%2Fallies%2Fnew'],
    ['/activity/approval', '/sign-in?returnTo=%2Factivity%2Fapproval'],
    ['/account', '/sign-in?returnTo=%2Faccount'],
    ['/settings/connections', '/sign-in?returnTo=%2Fsettings%2Fconnections'],
  ] as const)('sends signed-out protected route %s to sign-in', (pathname, expected) => {
    expect(getSessionRouteAction('signed-out', pathname)).toEqual({ type: 'replace', path: expected });
  });

  it('sends a signed-in root to the Ally collection', () => {
    expect(getSessionRouteAction('signed-in', '/')).toEqual({ type: 'replace', path: '/allies' });
  });

  it.each([
    ['/allies/new/complete', '/allies/new/complete'],
    ['/activity', '/activity'],
    ['/account', '/account'],
    ['/settings/privacy', '/settings/privacy'],
  ] as const)('uses a safe signed-in return target: %s', (returnTo, expected) => {
    expect(getSessionRouteAction('signed-in', '/sign-in', returnTo)).toEqual({ type: 'replace', path: expected });
  });

  it.each([undefined, '', 'https://evil.example', '//evil.example', '/sign-in', '/auth/return'])(
    'falls back to the collection for an unsafe return target: %s',
    (returnTo) => {
      expect(getSessionRouteAction('signed-in', '/sign-in', returnTo)).toEqual({
        type: 'replace',
        path: '/allies',
      });
    },
  );

  it.each(['/', '/sign-in'] as const)('sends offline entry route %s to the collection', (pathname) => {
    expect(getSessionRouteAction('offline-with-session', pathname)).toEqual({ type: 'replace', path: '/allies' });
  });

  it('allows protected routes with an offline session', () => {
    expect(getSessionRouteAction('offline-with-session', '/allies/ally-1')).toBeNull();
  });
});
