import { isCloudError, type WebSearchBackend } from "@allies/cloud-client";

import { alliesQueryKey } from "../allies/query-keys";

import { integrationAccessProblem } from "./integration-connect";

export const WEB_SEARCH_PROVIDERS: Record<WebSearchBackend, { label: string; keyUrl: string }> = {
  parallel: { label: "Parallel", keyUrl: "https://platform.parallel.ai/" },
  tavily: { label: "Tavily", keyUrl: "https://app.tavily.com/" },
  exa: { label: "Exa", keyUrl: "https://dashboard.exa.ai/api-keys" },
};

export const WEB_SEARCH_KEY_LENGTH = { min: 16, max: 512 } as const;

export function webSearchConnectionQueryKey(workspaceId: string) {
  return [...alliesQueryKey(workspaceId), "integrations", "web-search"] as const;
}

export function webSearchConnectProblem(error: unknown, label: string): string {
  if (isCloudError(error)) {
    if (error.code === "web_search_key_rejected") return `${label} rejected this key. Check it and paste it again.`;
    if (error.code === "web_search_check_failed") return "Couldn't check the key right now. Try again.";
    if (error.code === "vault_unavailable") return "Web search can't store keys right now. Try again later.";
    if (error.code === "integration_conflict") return "Web search changed while saving. Try again.";
    if (error.kind === "bad-request" || error.kind === "validation") return "That key doesn't look right.";
  }
  return integrationAccessProblem(error, label).message;
}

export function webSearchAccessProblem(error: unknown): string {
  if (isCloudError(error) && error.code === "web_search_not_connected") return "Connect web search before changing access.";
  return integrationAccessProblem(error, "Web search").message;
}
