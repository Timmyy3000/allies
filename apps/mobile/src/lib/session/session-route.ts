import { parseSafeReturnPath } from '@allies/cloud-client';

import type { NativeSessionState } from './native-session-adapter';

export type SessionRouteAction = { type: 'replace'; path: string };

function isProtectedPath(pathname: string): boolean {
  return pathname === '/account' || pathname === '/allies' || pathname.startsWith('/allies/');
}

function isSafeSignedInReturnTo(value: unknown): value is string {
  const path = parseSafeReturnPath(value);
  return path !== null && isProtectedPath(path);
}

export function getSessionRouteAction(
  status: NativeSessionState['status'],
  pathname: string,
  returnTo?: unknown,
): SessionRouteAction | null {
  if (pathname === '/auth/return' || status === 'checking' || status === 'refreshing' || status === 'unavailable') {
    return null;
  }

  if (status === 'signed-out') {
    return isProtectedPath(pathname)
      ? { type: 'replace', path: `/sign-in?returnTo=${encodeURIComponent(pathname)}` }
      : null;
  }

  if (status === 'offline-with-session') {
    return pathname === '/' || pathname === '/sign-in' ? { type: 'replace', path: '/allies' } : null;
  }

  if (pathname === '/') return { type: 'replace', path: '/allies' };
  if (pathname === '/sign-in') {
    return { type: 'replace', path: isSafeSignedInReturnTo(returnTo) ? (returnTo as string) : '/allies' };
  }

  return null;
}
