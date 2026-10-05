import { z } from "zod";
import { pushRegistrationSchema, registerPushSchema, type PushRegistration, type RegisterPush } from "@allies/cloud-client";

export type WorkerBinding = PushRegistration & { owner_user_id: string; enabled: true };
export type LogoutScope = { owner_user_id: string; session_id: string };
export type PendingRegistration = LogoutScope & { workspace_id: string; registration: RegisterPush; expected_epoch: number };
export type CleanupRecord = LogoutScope & { cleanup_id: string; workspace_id: string; binding: WorkerBinding | null; pending_registration: PendingRegistration | null };
export type WorkerState = { type: "PUSH_STATE"; epoch: number; browser_id: string; binding: WorkerBinding | null; renewal_needed: boolean; renewal_binding: WorkerBinding | null; pending_registration: PendingRegistration | null; material_fingerprint: string | null; cleanup_record: CleanupRecord | null };
export type WorkerAck = { type: "PUSH_ACK"; accepted: boolean; epoch: number; binding_id: string | null; enabled: boolean };
export type WorkerSubscription = { type: "PUSH_SUBSCRIPTION"; accepted: boolean; subscription: { endpoint: string; keys: { p256dh: string; auth: string } } | null };
export type WorkerRequest = { type: "PUSH_CLEANED"; expected_epoch: number; cleanup_id: string; rotate_browser_id?: boolean } | { type: "PUSH_SUBSCRIBE"; expected_epoch: number; vapid_public_key: string } | { type: "PUSH_STATE" } | { type: "PUSH_BIND"; expected_epoch: number; binding: WorkerBinding } | { type: "PUSH_CLEAR"; expected_epoch: number; binding_id: string | null; expected_pending_binding_id: string | null; logout_scope: LogoutScope | null } | ({ type: "PUSH_PREPARE"; expected_epoch: number; registration: RegisterPush; workspace_id: string } & LogoutScope);
const bindingSchema = pushRegistrationSchema.extend({ owner_user_id: z.uuid(), enabled: z.literal(true) });
const pendingSchema = z.object({ owner_user_id: z.uuid(), session_id: z.uuid(), workspace_id: z.uuid(), registration: registerPushSchema, expected_epoch: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER) });
const replySchema = z.discriminatedUnion("type", [z.object({ type: z.literal("PUSH_SUBSCRIPTION"), accepted: z.boolean(), subscription: z.object({ endpoint: z.string(), keys: z.object({ p256dh: z.string(), auth: z.string() }) }).nullable() }),z.object({ type: z.literal("PUSH_STATE"), epoch: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER), browser_id: z.uuid(), binding: bindingSchema.nullable(), renewal_needed: z.boolean(), renewal_binding: bindingSchema.nullable(), pending_registration: pendingSchema.nullable(), material_fingerprint: z.string().regex(/^[0-9a-f]{64}$/).nullable(), cleanup_record: z.object({ cleanup_id: z.uuid(), owner_user_id: z.uuid(), session_id: z.uuid(), workspace_id: z.uuid(), binding: bindingSchema.nullable(), pending_registration: pendingSchema.nullable() }).nullable() }), z.object({ type: z.literal("PUSH_ACK"), accepted: z.boolean(), epoch: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER), binding_id: z.uuid().nullable(), enabled: z.boolean() })]);
export async function registerPushWorker(): Promise<ServiceWorkerRegistration> {
  const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" });
  if (!registration.active) {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try { await Promise.race([navigator.serviceWorker.ready, new Promise<never>((_resolve, reject) => { timer = setTimeout(() => reject(new Error("Notifications are not ready. Try again.")), 5000); })]); }
    finally { clearTimeout(timer); }
  }
  return registration;
}
export async function workerMessage(registration: ServiceWorkerRegistration, request: { type: "PUSH_STATE" }): Promise<WorkerState>;
export async function workerMessage(registration: ServiceWorkerRegistration, request: { type: "PUSH_SUBSCRIBE"; expected_epoch: number; vapid_public_key: string }): Promise<WorkerSubscription>;
export async function workerMessage(registration: ServiceWorkerRegistration, request: Exclude<WorkerRequest, { type: "PUSH_STATE" } | { type: "PUSH_SUBSCRIBE"; expected_epoch: number; vapid_public_key: string }>): Promise<WorkerAck>;
export async function workerMessage(registration: ServiceWorkerRegistration, request: WorkerRequest): Promise<WorkerState | WorkerAck | WorkerSubscription> {
  const worker = registration.active;
  if (!worker) throw new Error("Notifications are not ready. Try again.");
  return new Promise((resolve, reject) => {
    const channel = new MessageChannel();
    const finish = () => { clearTimeout(timer); channel.port1.close(); channel.port2.close(); };
    const timer = setTimeout(() => { finish(); reject(new Error("Notification cleanup could not be confirmed. Try again.")); }, 5000);
    channel.port1.onmessage = event => {
      const parsed = replySchema.safeParse(event.data);
      finish();
      if (!parsed.success || parsed.data.type !== (request.type === "PUSH_STATE" ? "PUSH_STATE" : request.type === "PUSH_SUBSCRIBE" ? "PUSH_SUBSCRIPTION" : "PUSH_ACK")) reject(new Error("Notifications are not ready. Try again."));
      else resolve(parsed.data);
    };
    worker.postMessage(request, [channel.port2]);
  });
}
export function belongsTo(binding: LogoutScope | null, scope: LogoutScope): boolean {
  return !binding || (binding.owner_user_id === scope.owner_user_id && binding.session_id === scope.session_id);
}
export async function clearLogoutBinding(registration: ServiceWorkerRegistration, scope: LogoutScope, initial?: WorkerState): Promise<boolean> {
  let state = initial ?? await workerMessage(registration, { type: "PUSH_STATE" });
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (!belongsTo(state.binding, scope) || !belongsTo(state.pending_registration, scope) || !belongsTo(state.renewal_binding, scope)) return false;
    const ack = await workerMessage(registration, { type: "PUSH_CLEAR", expected_epoch: state.epoch, binding_id: state.binding?.binding_id ?? null, expected_pending_binding_id: state.pending_registration?.registration.binding_id ?? null, logout_scope: scope });
    if (ack.accepted) return true;
    if (attempt < 2) state = await workerMessage(registration, { type: "PUSH_STATE" });
  }
  return false;
}
