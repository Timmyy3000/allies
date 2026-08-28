import { parseSafeReturnPath } from '@allies/cloud-client';

import type { NativeSessionState } from './native-session-adapter';

export type SessionRouteAction = { type: 'replace'; path: string };

function isProtectedPath(pathname: string): boolean {
  return pathname === '/account'
    || pathname === '/activity'
    || pathname.startsWith('/activity/')
    || pathname === '/allies'
    || pathname.startsWith('/allies/')
    || pathname === '/settings'
    || pathname.startsWith('/settings/');
}

function isAccountEntryPath(pathname: string): boolean {
  return pathname === '/sign-in' || pathname === '/create-account';
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
  if (status === 'checking' || status === 'refreshing' || status === 'unavailable') {
    return null;
  }

  if (status === 'signed-out') {
    return isProtectedPath(pathname)
      ? { type: 'replace', path: `/sign-in?returnTo=${encodeURIComponent(pathname)}` }
      : null;
  }

  if (status === 'offline-with-session') {
    return pathname === '/' || isAccountEntryPath(pathname) ? { type: 'replace', path: '/allies' } : null;
  }

  if (pathname === '/') return { type: 'replace', path: '/allies' };
  if (isAccountEntryPath(pathname) || pathname === '/auth/return') {
    return { type: 'replace', path: isSafeSignedInReturnTo(returnTo) ? (returnTo as string) : '/allies' };
  }

  return null;
}
