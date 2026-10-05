import { z } from "zod";

import { externalHttpsUrlSchema } from "../schemas";

const dateTime = z.iso.datetime({ offset: true });
const accountSchema = z
  .object({
    user: z.object({ id: z.string().min(1) }).loose(),
    profile: z
      .object({
        display_name: z.string(),
        avatar_url: externalHttpsUrlSchema.nullable().optional(),
      })
      .loose(),
    session: z
      .object({
        id: z.string().min(1),
        expires_at: dateTime,
      })
      .loose(),
    workspace: z
      .object({
        id: z.string().min(1),
        name: z.string().min(1),
        role: z.string().min(1),
        capabilities: z.array(z.string()),
      })
      .loose(),
  })
  .loose();

export interface AccountViewModel {
  userId: string;
  displayName: string;
  avatarUrl: string | null;
  session: { id: string; expiresAt: string };
  workspace: { id: string; name: string; role: string; capabilities: string[] };
}

export function toAccountViewModel(input: unknown): AccountViewModel {
  const value = accountSchema.parse(input);
  return {
    userId: value.user.id,
    displayName: value.profile.display_name,
    avatarUrl: value.profile.avatar_url ?? null,
    session: { id: value.session.id, expiresAt: value.session.expires_at },
    workspace: {
      id: value.workspace.id,
      name: value.workspace.name,
      role: value.workspace.role,
      capabilities: value.workspace.capabilities,
    },
  };
}
