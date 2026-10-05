import { z } from "zod";
import type { CloudClientOptions } from "./client";
import { normalizeCloudError } from "./errors";
import { parsePublicCloudUrl } from "./environment";
import { canonicalRoutineUuidSchema as uuid } from "./routines";
import { createControlledFetch } from "./transport";

export const pushConfigSchema = z.object({ enabled: z.boolean(), vapid_public_key: z.string().nullable(), presence_ttl_seconds: z.literal(60), heartbeat_seconds: z.literal(20) });
export const registerPushSchema = z.strictObject({ browser_id: uuid, binding_id: uuid, replaces_binding_id: uuid.nullable(), endpoint: z.url().max(2048).refine(value => new URL(value).protocol === "https:"), keys: z.strictObject({ p256dh: z.string().regex(/^[A-Za-z0-9_-]{87}$/), auth: z.string().regex(/^[A-Za-z0-9_-]{22}$/) }) });
export const pushRegistrationSchema = z.object({ subscription_id: uuid, browser_id: uuid, binding_id: uuid, workspace_id: uuid, session_id: uuid, state: z.literal("active") });
const presenceSchema = z.strictObject({ binding_id: uuid, client_id: uuid, sequence: z.number().int().min(1).max(2147483647), visible: z.boolean() });
const receiptSchema = z.object({ accepted_sequence: z.number().int().positive(), foreground_until: z.iso.datetime({ offset: true }).nullable() });
export type PushConfig = z.infer<typeof pushConfigSchema>;
export type RegisterPush = z.infer<typeof registerPushSchema>;
export type PushRegistration = z.infer<typeof pushRegistrationSchema>;
export type PushPresence = z.infer<typeof presenceSchema>;

export function createPushClient(options: CloudClientOptions) {
  const baseUrl = parsePublicCloudUrl(options.baseUrl);
  const fetch = createControlledFetch({ ...options, fetch: options.fetch ?? globalThis.fetch.bind(globalThis), maxJsonBytes: 8192 });
  const path = (workspace: string) => `${baseUrl}/api/v1/workspaces/${uuid.parse(workspace)}/push`;
  async function request<T>(url: string, method: string, schema: z.ZodType<T> | null, body?: unknown, signal?: AbortSignal): Promise<T> {
    const response = await fetch(new Request(url, { method, credentials: "include", signal, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined }));
    const data: unknown = response.status === 204 ? undefined : await response.json();
    if (!response.ok) throw normalizeCloudError(response.status, data);
    if (!schema) {
      if (response.status !== 204) throw { kind: "contract" };
      return undefined as T;
    }
    const parsed = z.object({ status: z.literal("success"), message: z.string(), data: schema }).safeParse(data);
    if (response.status !== 200 || !parsed.success) throw { kind: "contract" };
    return parsed.data.data;
  }
  return {
    config: (workspace: string, signal?: AbortSignal) => request(path(workspace) + "/config", "GET", pushConfigSchema, undefined, signal),
    register: (workspace: string, registration: RegisterPush, signal?: AbortSignal) => request(path(workspace) + "/subscriptions", "POST", pushRegistrationSchema, registerPushSchema.parse(registration), signal),
    presence: (workspace: string, subscription: string, presence: PushPresence, signal?: AbortSignal) => request(`${path(workspace)}/subscriptions/${uuid.parse(subscription)}/presence`, "POST", receiptSchema, presenceSchema.parse(presence), signal),
    revoke: (workspace: string, subscription: string, binding: string, signal?: AbortSignal) => request(`${path(workspace)}/subscriptions/${uuid.parse(subscription)}`, "DELETE", null, { binding_id: uuid.parse(binding) }, signal),
  };
}
