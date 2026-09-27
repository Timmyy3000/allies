import { z } from "zod";

const timestampSchema = z.iso.datetime({ offset: true });

export const gmailGrantLevelSchema = z.enum(["read", "send"]);

export const gmailReturnToSchema = z.string().min(1).max(500)
  .refine((value) => value.startsWith("/") && !value.startsWith("//") && !/[\\\u0000-\u001f\u007f]/u.test(value));

const allyGrantSchema = z.object({
  ally_id: z.uuid(),
  level: z.enum(["read", "send", "none"]),
  grant_generation: z.number().int().nonnegative(),
  updated_at: timestampSchema,
});

export const gmailConnectionSchema = z.object({
  connection_id: z.uuid(),
  account_email: z.string().min(1).max(320),
  scope_set: z.array(z.string()),
  connected_at: timestampSchema,
  ally_grants: z.array(allyGrantSchema),
});

export const gmailConnectResponseSchema = z.object({
  connect_session_id: z.uuid(),
  auth_url: z.string().min(1).max(4096),
  expires_at: timestampSchema,
});

export type GmailGrantLevel = "read" | "send" | "none";

export interface GmailAllyGrant {
  allyId: string;
  level: GmailGrantLevel;
  grantGeneration: number;
  updatedAt: string;
}

export interface GmailConnection {
  connectionId: string;
  accountEmail: string;
  scopes: string[];
  connectedAt: string;
  allyGrants: GmailAllyGrant[];
}

export interface GmailConnectSession {
  connectSessionId: string;
  authUrl: string;
  expiresAt: string;
}

export function toGmailAllyGrant(value: z.infer<typeof allyGrantSchema>): GmailAllyGrant {
  return {
    allyId: value.ally_id,
    level: value.level,
    grantGeneration: value.grant_generation,
    updatedAt: value.updated_at,
  };
}

export function toGmailConnection(value: z.infer<typeof gmailConnectionSchema>): GmailConnection {
  return {
    connectionId: value.connection_id,
    accountEmail: value.account_email,
    scopes: value.scope_set,
    connectedAt: value.connected_at,
    allyGrants: value.ally_grants.map(toGmailAllyGrant),
  };
}

export function toGmailConnectSession(value: z.infer<typeof gmailConnectResponseSchema>): GmailConnectSession {
  const authUrl = parseGoogleAuthUrl(value.auth_url);
  if (!authUrl) throw new Error("gmail auth url is not a Google consent url");
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

export { allyGrantSchema as gmailAllyGrantSchema };
