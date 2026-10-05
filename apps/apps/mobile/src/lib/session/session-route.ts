import { parseSafeReturnPath } from '@allies/cloud-client';

import type { NativeSessionState } from './native-session-adapter';

export type SessionRouteAction = { type: 'replace'; path: string };

function isCurrentAlliesPath(pathname: string): boolean {
  return pathname === '/allies'
    || pathname === '/account'
    || pathname === '/allies/new'
    || pathname === '/allies/new/complete'
    || pathname === '/allies/new/post-setup'
    || /^\/allies\/[^/]+$/u.test(pathname);
}

function isAccountEntryPath(pathname: string): boolean {
  return pathname === '/sign-in';
}

function isAuthReturnPath(pathname: string): boolean {
  return pathname === '/auth/return' || pathname === '/auth/callback';
}

function isSafeSignedInReturnTo(value: unknown): value is string {
  const path = parseSafeReturnPath(value);
  return path !== null && isCurrentAlliesPath(path);
}

export function selectMobileReturnTo(value: unknown): string {
  return isSafeSignedInReturnTo(value) ? value : '/allies';
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
    if (pathname === '/account') return { type: 'replace', path: '/' };
    return isCurrentAlliesPath(pathname)
      ? { type: 'replace', path: `/sign-in?returnTo=${encodeURIComponent(pathname)}` }
      : null;
  }

  if (status === 'offline-with-session') {
    return pathname === '/' || isAccountEntryPath(pathname) ? { type: 'replace', path: '/allies' } : null;
  }

  if (pathname === '/') return { type: 'replace', path: selectMobileReturnTo(returnTo) };
  if (isAccountEntryPath(pathname) || isAuthReturnPath(pathname)) {
    if (isAuthReturnPath(pathname) && returnTo === undefined) return null;
    return { type: 'replace', path: selectMobileReturnTo(returnTo) };
  }

  return null;
}
