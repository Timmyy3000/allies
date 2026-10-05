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

export type IntegrationProvider = z.infer<typeof integrationProviderSchema>;

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
