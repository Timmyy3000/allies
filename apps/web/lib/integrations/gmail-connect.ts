import { isCloudError } from "@allies/cloud-client";

const RETURN_MESSAGES: Record<string, string> = {
  access_denied: "Gmail wasn't connected.",
  scope_insufficient: "Gmail needs read and send access. Try connecting again and allow both.",
  integration_conflict: "A different Gmail account is already connected to this workspace.",
  provider_unavailable: "Gmail isn't responding. Try again.",
  session_invalid: "Your session ended before Gmail finished connecting. Sign in and try again.",
};

export type GmailReturn = { status: "connected" } | { status: "failed"; message: string };

export function readGmailReturn(params: URLSearchParams): GmailReturn | null {
  if (params.get("gmail") === "connected") return { status: "connected" };
  const code = params.get("gmail_error");
  if (!code) return null;
  return { status: "failed", message: RETURN_MESSAGES[code] ?? "That link expired. Try connecting again." };
}

export type GmailAccessProblem = {
  message: string;
  reconnect: boolean;
  locked: boolean;
};

export function gmailAccessProblem(error: unknown): GmailAccessProblem {
  const problem = (message: string, extra: Partial<GmailAccessProblem> = {}) => ({ message, reconnect: false, locked: false, ...extra });
  if (!isCloudError(error)) return problem("Something went wrong. Try again.");
  if (error.code === "refresh_revoked") return problem("Gmail disconnected. Reconnect to keep using it.", { reconnect: true });
  if (error.code === "scope_insufficient") return problem("Gmail needs more permissions. Reconnect to continue.", { reconnect: true });
  if (error.status === 401 || error.kind === "unauthorized") return problem("Your session has ended. Sign in again to continue.");
  if (error.status === 403 || error.kind === "forbidden") return problem("You can't change access for this workspace.", { locked: true });
  if (error.status === 503) return problem("Gmail isn't responding. Try again.");
  return problem("Something went wrong. Try again.");
}
