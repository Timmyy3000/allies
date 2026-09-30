import type { LogoutScope } from "./push-worker";
const KEY = "allies:push-cleanup:v1";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export function readPushCleanupScope(): LogoutScope | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(KEY) ?? "null");
    return value && Object.keys(value).sort().join() === "owner_user_id,session_id" && UUID.test(value.owner_user_id) && UUID.test(value.session_id) ? value : null;
  } catch { return null; }
}
export function savePushCleanupScope(scope: LogoutScope | null): void {
  try { if (scope) sessionStorage.setItem(KEY, JSON.stringify(scope)); else sessionStorage.removeItem(KEY); } catch { /* The worker still persists the ownership fence and cleanup record. */ }
}
