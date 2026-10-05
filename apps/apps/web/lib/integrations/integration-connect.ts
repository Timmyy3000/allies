import { isCloudError, type IntegrationGrantLevel, type IntegrationProvider } from "@allies/cloud-client";

export const INTEGRATION_PROVIDERS = ["gmail", "calendar"] as const satisfies readonly IntegrationProvider[];

/** The access one switch grants: Gmail stays read-only; Calendar can also change events. */
export const INTEGRATIONS: Record<IntegrationProvider, { label: string; grantLevel: Exclude<IntegrationGrantLevel, "none">; scopeMessage: string }> = {
  gmail: {
    label: "Gmail",
    grantLevel: "read",
    scopeMessage: "Gmail needs read and send access. Try connecting again and allow both.",
  },
  calendar: {
    label: "Calendar",
    grantLevel: "write",
    scopeMessage: "Calendar needs access to your events. Try connecting again and allow it.",
  },
};

function returnMessages(provider: IntegrationProvider): Record<string, string> {
  const { label, scopeMessage } = INTEGRATIONS[provider];
  return {
    access_denied: `${label} wasn't connected.`,
    scope_insufficient: scopeMessage,
    integration_conflict: `A different Google account is already connected for ${label}.`,
    provider_unavailable: `${label} isn't responding. Try again.`,
    session_invalid: `Your session ended before ${label} finished connecting. Sign in and try again.`,
  };
}

export type IntegrationReturn =
  | { provider: IntegrationProvider; status: "connected" }
  | { provider: IntegrationProvider; status: "failed"; message: string };

export function readIntegrationReturn(params: URLSearchParams): IntegrationReturn | null {
  for (const provider of INTEGRATION_PROVIDERS) {
    if (params.get(provider) === "connected") return { provider, status: "connected" };
    const code = params.get(`${provider}_error`);
    if (code) return { provider, status: "failed", message: returnMessages(provider)[code] ?? "That link expired. Try connecting again." };
  }
  return null;
}

export type IntegrationAccessProblem = {
  message: string;
  reconnect: boolean;
  locked: boolean;
};

export function integrationAccessProblem(error: unknown, provider: IntegrationProvider): IntegrationAccessProblem {
  const { label } = INTEGRATIONS[provider];
  const problem = (message: string, extra: Partial<IntegrationAccessProblem> = {}) => ({ message, reconnect: false, locked: false, ...extra });
  if (!isCloudError(error)) return problem("Something went wrong. Try again.");
  if (error.code === "refresh_revoked") return problem(`${label} disconnected. Reconnect to keep using it.`, { reconnect: true });
  if (error.code === "scope_insufficient") return problem(`${label} needs more permissions. Reconnect to continue.`, { reconnect: true });
  if (error.status === 401 || error.kind === "unauthorized") return problem("Your session has ended. Sign in again to continue.");
  if (error.status === 403 || error.kind === "forbidden") return problem("You can't change access for this workspace.", { locked: true });
  if (error.status === 503) return problem(`${label} isn't responding. Try again.`);
  return problem("Something went wrong. Try again.");
}
