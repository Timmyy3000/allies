import { parseSafeReturnPath } from "@allies/cloud-client";

export const AUTH_RETURN_ERROR_CODES = [
  "access_denied",
  "provider_denied",
  "provider_unavailable",
  "invalid_state",
  "origin_rejected",
  "csrf_rejected",
] as const;

export type AuthReturnErrorCode = (typeof AUTH_RETURN_ERROR_CODES)[number];

export function selectAuthReturnTo(value: unknown): string {
  return parseSafeReturnPath(value) ?? "/account";
}

export function selectAuthError(value: unknown): AuthReturnErrorCode | undefined {
  if (typeof value !== "string") return undefined;
  return AUTH_RETURN_ERROR_CODES.includes(value as AuthReturnErrorCode)
    ? (value as AuthReturnErrorCode)
    : undefined;
}
