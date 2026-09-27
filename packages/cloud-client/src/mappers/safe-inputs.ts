import { z } from "zod";

import { externalHttpsUrlSchema } from "../schemas";

const timestampSchema = z.iso.datetime({ offset: true });

export const safeInputSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  website: z.string(),
  ally_ids: z.array(z.uuid()),
  updated_at: timestampSchema,
});

export const safeInputRequestSchema = z.object({
  id: z.uuid(),
  ally_id: z.uuid(),
  kind: z.enum(["new", "access"]),
  safe_input_id: z.uuid().nullable(),
  name: z.string(),
  website: z.string(),
  created_at: timestampSchema,
});

export const browserSessionSchema = z.object({
  live_url: externalHttpsUrlSchema,
  expires_at: timestampSchema,
});

export interface SafeInput {
  id: string;
  name: string;
  website: string;
  allyIds: string[];
  updatedAt: string;
}

export interface SafeInputRequest {
  id: string;
  allyId: string;
  kind: "new" | "access";
  safeInputId: string | null;
  name: string;
  website: string;
  createdAt: string;
}

export interface AllyBrowserSession {
  liveUrl: string;
  expiresAt: string;
}

/** Write-only login values; never read back from Cloud. */
export interface SafeInputValues {
  name?: string;
  website?: string;
  username?: string;
  password?: string;
}

export function toSafeInput(value: z.infer<typeof safeInputSchema>): SafeInput {
  return {
    id: value.id,
    name: value.name,
    website: value.website,
    allyIds: value.ally_ids,
    updatedAt: value.updated_at,
  };
}

export function toSafeInputRequest(value: z.infer<typeof safeInputRequestSchema>): SafeInputRequest {
  return {
    id: value.id,
    allyId: value.ally_id,
    kind: value.kind,
    safeInputId: value.safe_input_id,
    name: value.name,
    website: value.website,
    createdAt: value.created_at,
  };
}

export function toAllyBrowserSession(value: z.infer<typeof browserSessionSchema>): AllyBrowserSession {
  return { liveUrl: value.live_url, expiresAt: value.expires_at };
}
