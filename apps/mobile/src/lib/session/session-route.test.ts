import { describe, expect, it } from 'vitest';

import { getSessionRouteAction, selectMobileReturnTo } from './session-route';

describe('getSessionRouteAction', () => {
  it.each([
    ['checking', '/', undefined],
    ['refreshing', '/allies/new', undefined],
    ['unavailable', '/allies', undefined],
  ] as const)('does not redirect while the session is %s', (status, pathname, returnTo) => {
    expect(getSessionRouteAction(status, pathname, returnTo)).toBeNull();
  });

  it('keeps the auth return route exempt until sign-in completes', () => {
    expect(getSessionRouteAction('signed-out', '/auth/return')).toBeNull();
    expect(getSessionRouteAction('signed-out', '/auth/callback')).toBeNull();
    expect(getSessionRouteAction('signed-in', '/auth/callback')).toBeNull();
    expect(getSessionRouteAction('signed-in', '/auth/return', '/allies/new')).toEqual({
      type: 'replace',
      path: '/allies/new',
    });
  });

  it('leaves the public onboarding name route available in every session state', () => {
    expect(getSessionRouteAction('signed-out', '/onboarding/name')).toBeNull();
    expect(getSessionRouteAction('signed-in', '/onboarding/name')).toBeNull();
    expect(getSessionRouteAction('offline-with-session', '/onboarding/name')).toBeNull();
  });

  it.each([
    ['/allies', '/sign-in?returnTo=%2Fallies'],
    ['/allies/new', '/sign-in?returnTo=%2Fallies%2Fnew'],
    ['/allies/new/complete', '/sign-in?returnTo=%2Fallies%2Fnew%2Fcomplete'],
    ['/allies/ally-1', '/sign-in?returnTo=%2Fallies%2Fally-1'],
  ] as const)('sends signed-out protected route %s to sign-in', (pathname, expected) => {
    expect(getSessionRouteAction('signed-out', pathname)).toEqual({ type: 'replace', path: expected });
  });

  it('returns a signed-out account route to the public welcome', () => {
    expect(getSessionRouteAction('signed-out', '/account')).toEqual({ type: 'replace', path: '/' });
  });

  it('sends a signed-in root or auth entry to the Ally collection', () => {
    expect(getSessionRouteAction('signed-in', '/')).toEqual({ type: 'replace', path: '/allies' });
    expect(getSessionRouteAction('signed-in', '/', '/allies/new/complete')).toEqual({
      type: 'replace',
      path: '/allies/new/complete',
    });
    expect(getSessionRouteAction('signed-in', '/sign-in')).toEqual({ type: 'replace', path: '/allies' });
  });

  it.each([
    ['/sign-in', '/allies/new', '/allies/new'],
    ['/sign-in', '/allies/ally-1', '/allies/ally-1'],
    ['/sign-in', '/account', '/account'],
  ] as const)('uses a safe signed-in return target from %s', (pathname, returnTo, expected) => {
    expect(getSessionRouteAction('signed-in', pathname, returnTo)).toEqual({ type: 'replace', path: expected });
  });

  it.each([
    undefined,
    '',
    'https://evil.example',
    '//evil.example',
    '/allies/new/complete?unsafe=true',
    '/sign-in',
    '/auth/return',
  ])('falls back to the collection for an unsafe return target: %s', (returnTo) => {
    expect(selectMobileReturnTo(returnTo)).toBe('/allies');
  });

  it('moves entry routes to the collection when a session is offline', () => {
    expect(getSessionRouteAction('offline-with-session', '/sign-in')).toEqual({ type: 'replace', path: '/allies' });
  });

  it('allows current protected routes with an offline session', () => {
    expect(getSessionRouteAction('offline-with-session', '/allies/ally-1')).toBeNull();
  });
});
