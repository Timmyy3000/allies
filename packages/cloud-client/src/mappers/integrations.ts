import { z } from "zod";

const timestampSchema = z.iso.datetime({ offset: true });

export const integrationProviderSchema = z.enum(["gmail", "calendar"]);

export const integrationGrantLevelSchema = z.enum(["read", "send", "write"]);

export const integrationReturnToSchema = z.string().min(1).max(500)
  .refine((value) => value.startsWith("/") && !value.startsWith("//") && !/[\\\u0000-\u001f\u007f]/u.test(value));

const allyGrantSchema = z.object({
  ally_id: z.uuid(),
  level: z.enum(["read", "send", "write", "none"]),
  grant_generation: z.number().int().nonnegative(),
  updated_at: timestampSchema,
});

export const integrationConnectionSchema = z.object({
  connection_id: z.uuid(),
  account_email: z.string().min(1).max(320),
  scope_set: z.array(z.string()),
  connected_at: timestampSchema,
  ally_grants: z.array(allyGrantSchema),
});

export const integrationConnectResponseSchema = z.object({
  connect_session_id: z.uuid(),
  auth_url: z.string().min(1).max(4096),
  expires_at: timestampSchema,
});

export const webSearchBackendSchema = z.enum(["parallel", "tavily", "exa"]);

export const webSearchGrantLevelSchema = z.enum(["use", "none"]);

export const webSearchAllyGrantSchema = z.object({
  ally_id: z.uuid(),
  level: webSearchGrantLevelSchema,
  grant_generation: z.number().int().nonnegative(),
  updated_at: timestampSchema,
});

export const webSearchConnectionSchema = z.object({
  connection_id: z.uuid(),
  backend: webSearchBackendSchema,
  key_hint: z.string().min(1).max(4),
  connected_at: timestampSchema,
  ally_grants: z.array(webSearchAllyGrantSchema),
});

export type IntegrationProvider = z.infer<typeof integrationProviderSchema>;

export type WebSearchBackend = z.infer<typeof webSearchBackendSchema>;

export type WebSearchGrantLevel = z.infer<typeof webSearchGrantLevelSchema>;

export type IntegrationGrantLevel = "read" | "send" | "write" | "none";

export interface IntegrationAllyGrant {
  allyId: string;
  level: IntegrationGrantLevel;
  grantGeneration: number;
  updatedAt: string;
}

export interface IntegrationConnection {
  connectionId: string;
  accountEmail: string;
  scopes: string[];
  connectedAt: string;
  allyGrants: IntegrationAllyGrant[];
}

export interface IntegrationConnectSession {
  connectSessionId: string;
  authUrl: string;
  expiresAt: string;
}

export interface WebSearchAllyGrant extends Omit<IntegrationAllyGrant, "level"> {
  level: WebSearchGrantLevel;
}

export interface WebSearchConnection {
  backend: WebSearchBackend;
  keyHint: string;
  connectedAt: string;
  allyGrants: WebSearchAllyGrant[];
}

export function toWebSearchAllyGrant(value: z.infer<typeof webSearchAllyGrantSchema>): WebSearchAllyGrant {
  return {
    allyId: value.ally_id,
    level: value.level,
    grantGeneration: value.grant_generation,
    updatedAt: value.updated_at,
  };
}

export function toWebSearchConnection(value: z.infer<typeof webSearchConnectionSchema>): WebSearchConnection {
  return {
    backend: value.backend,
    keyHint: value.key_hint,
    connectedAt: value.connected_at,
    allyGrants: value.ally_grants.map(toWebSearchAllyGrant),
  };
}

export function toIntegrationAllyGrant(value: z.infer<typeof allyGrantSchema>): IntegrationAllyGrant {
  return {
    allyId: value.ally_id,
    level: value.level,
    grantGeneration: value.grant_generation,
    updatedAt: value.updated_at,
  };
}

export function toIntegrationConnection(value: z.infer<typeof integrationConnectionSchema>): IntegrationConnection {
  return {
    connectionId: value.connection_id,
    accountEmail: value.account_email,
    scopes: value.scope_set,
    connectedAt: value.connected_at,
    allyGrants: value.ally_grants.map(toIntegrationAllyGrant),
  };
}

export function toIntegrationConnectSession(value: z.infer<typeof integrationConnectResponseSchema>): IntegrationConnectSession {
  const authUrl = parseGoogleAuthUrl(value.auth_url);
  if (!authUrl) throw new Error("integration auth url is not a Google consent url");
  return { connectSessionId: value.connect_session_id, authUrl, expiresAt: value.expires_at };
}

export function parseGoogleAuthUrl(value: string): string | null {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || url.hostname !== "accounts.google.com") return null;
  if (url.username || url.password || url.port) return null;
  return url.toString();
}

export { allyGrantSchema as integrationAllyGrantSchema };
