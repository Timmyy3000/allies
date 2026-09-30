// @vitest-environment jsdom
import { MessageChannel } from "node:worker_threads";
import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CloudClient, AccountViewModel } from "@allies/cloud-client";
import { createPushLifecycle } from "./push-lifecycle";
import { clearLogoutBinding, registerPushWorker, workerMessage, type WorkerState, type WorkerRequest, type WorkerAck, type WorkerSubscription } from "./push-worker";
import { matchesPushTarget } from "./push-navigation";
vi.mock("./push-worker", async importOriginal => ({ ...await importOriginal<typeof import("./push-worker")>(), registerPushWorker: vi.fn(), workerMessage: vi.fn() }));
const id = (n: number) => `00000000-0000-4000-8000-${n.toString().padStart(12, "0")}`;
const account = { userId: id(1), session: { id: id(2) }, workspace: { id: id(3) } } as AccountViewModel;
const material = { endpoint: "https://fcm.googleapis.com/test", keys: { p256dh: "B".repeat(87), auth: "A".repeat(22) } };
const binding = { subscription_id: id(5), browser_id: id(6), binding_id: id(4), workspace_id: id(3), session_id: id(2), owner_user_id: id(1), state: "active" as const, enabled: true as const };
const state = (): WorkerState => ({ type: "PUSH_STATE", epoch: 0, browser_id: id(6), binding: null, renewal_needed: false, renewal_binding: null, pending_registration: null, material_fingerprint: null, cleanup_record: null });
const getAccount = vi.fn(async () => account);
const requestPermission = vi.fn(async () => "granted");
const revoke = vi.fn(async (): Promise<void> => { throw new Error("offline"); });
const register = vi.fn(async (_workspace, input) => ({ ...binding, binding_id: input.binding_id }));
let current: WorkerState;
let getSubscription: ReturnType<typeof vi.fn>;
let registration: ServiceWorkerRegistration;
let lifecycle: ReturnType<typeof createPushLifecycle>;
let stop: () => void;
const run = async <T,>(operation: (signal?: AbortSignal) => Promise<T>) => operation();
beforeEach(() => {
  vi.clearAllMocks(); getAccount.mockResolvedValue(account); sessionStorage.clear(); current = state();
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("MessageChannel", MessageChannel);
  vi.stubGlobal("Notification", { permission: "granted", requestPermission });
  vi.stubGlobal("PushManager", class {});
  Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
  Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { addEventListener: vi.fn(), removeEventListener: vi.fn() } });
  getSubscription = vi.fn(async () => ({ toJSON: () => material }));
  registration = { pushManager: { getSubscription }, active: { postMessage(request: WorkerRequest, ports: { postMessage: (reply: unknown) => void }[]) {
    const send = workerMessage as unknown as (registration: ServiceWorkerRegistration, request: WorkerRequest) => Promise<WorkerState | WorkerAck | WorkerSubscription>;
    void send(registration, request).then(reply => ports[0].postMessage(reply));
  } } } as unknown as ServiceWorkerRegistration;
  vi.mocked(registerPushWorker).mockResolvedValue(registration);
  vi.mocked(workerMessage).mockImplementation((async (_registration, request) => {
    if (request.type === "PUSH_STATE") return structuredClone(current);
    if (request.type === "PUSH_SUBSCRIBE") return { type: "PUSH_SUBSCRIPTION", accepted: true, subscription: material };
    if (request.type === "PUSH_PREPARE") { current.pending_registration = { registration: request.registration, expected_epoch: request.expected_epoch, owner_user_id: request.owner_user_id, session_id: request.session_id, workspace_id: request.workspace_id }; }
    if (request.type === "PUSH_BIND") { current.binding = request.binding; current.epoch += 1; current.pending_registration = null; }
    if (request.type === "PUSH_CLEAR") {
      const prior = current.binding ?? current.renewal_binding;
      const pending = current.pending_registration;
      if (prior || pending) current.cleanup_record = { cleanup_id: id(100), owner_user_id: (prior ?? pending)!.owner_user_id, session_id: (prior ?? pending)!.session_id, workspace_id: (prior ?? pending)!.workspace_id, binding: prior, pending_registration: pending };
      current.binding = null; current.pending_registration = null; current.renewal_binding = null; current.epoch += 1;
    }
    if (request.type === "PUSH_CLEANED") { current.cleanup_record = null; if (request.rotate_browser_id) { current.browser_id = id(200); current.epoch += 1; } }
    return { type: "PUSH_ACK", accepted: true, epoch: current.epoch, binding_id: current.binding?.binding_id ?? null, enabled: !!current.binding };
  }) as typeof workerMessage);
  const client = { push: { config: vi.fn(async () => ({ enabled: true, vapid_public_key: "B".repeat(87), heartbeat_seconds: 20, presence_ttl_seconds: 60 })), register, revoke, presence: vi.fn(async () => undefined) }, getCurrentAccount: getAccount } as unknown as CloudClient;
  lifecycle = createPushLifecycle(client, run); stop = lifecycle.start();
});
afterEach(() => { stop(); vi.unstubAllGlobals(); });
describe("authenticated push lifecycle", () => {
  it("does not prompt on recovery, requests permission synchronously from enable, handles denial", async () => {
    await lifecycle.recover(account); expect(requestPermission).not.toHaveBeenCalled();
    vi.stubGlobal("Notification", { permission: "default", requestPermission: vi.fn(async () => "denied") });
    const enabling = lifecycle.enable(); expect(Notification.requestPermission).toHaveBeenCalledOnce();
    await enabling; expect(lifecycle.getSnapshot().status).toBe("off"); expect(register).not.toHaveBeenCalled();
  });
  it("unsupported installation has no registration or prompt", async () => {
    vi.stubGlobal("PushManager", undefined); Object.defineProperty(window, "isSecureContext", { configurable: true, value: false });
    await lifecycle.recover(account); expect(lifecycle.getSnapshot().status).toBe("unsupported"); expect(registerPushWorker).not.toHaveBeenCalled();
  });
  it("lost registration response retries exact persisted UUID, renewal replaces old binding", async () => {
    current.renewal_needed = true; current.renewal_binding = binding;
    register.mockRejectedValueOnce(new Error("lost response"));
    await lifecycle.recover(account); expect(lifecycle.getSnapshot().status).toBe("failed");
    const firstInput = register.mock.calls[0][1]; expect(firstInput.replaces_binding_id).toBe(binding.binding_id); expect(firstInput.binding_id).not.toBe(binding.binding_id);
    await lifecycle.recover(account); expect(register.mock.calls[1][1]).toEqual(firstInput); expect(lifecycle.getSnapshot().status).toBe("enabled");
  });
  it("a revoked pending binding is cleared so explicit retry uses a new UUID", async () => {
    await lifecycle.recover(account); register.mockRejectedValueOnce({ kind: "conflict", code: "push_binding_conflict" });
    await lifecycle.enable(); expect(lifecycle.getSnapshot().status).toBe("failed"); expect(current.pending_registration).toBeNull();
    const revoked = register.mock.calls[0][1].binding_id;
    register.mockRejectedValueOnce({ kind: "conflict", code: "push_binding_conflict" });
    await lifecycle.enable(); expect(register.mock.calls[2][1].binding_id).not.toBe(revoked); expect(lifecycle.getSnapshot().status).toBe("enabled");
  });
  it("a paused recovery cannot restore enabled after logout; failed revoke leaves off", async () => {
    current.binding = binding;
    current.material_fingerprint = Array.from(new Uint8Array(await webcrypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([material.endpoint, material.keys.p256dh, material.keys.auth])))), byte => byte.toString(16).padStart(2, "0")).join("");
    let release!: (value: unknown) => void;
    getSubscription.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    const recovering = lifecycle.recover(account); await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    await lifecycle.logout(); release({ toJSON: () => material }); await recovering;
    expect(lifecycle.getSnapshot().status).toBe("off");
  });
  it("failed revoke is recovered before a new explicit enable, with no automatic consent", async () => {
    current.binding = binding; await lifecycle.recover(account);
    await lifecycle.disable(); expect(current.cleanup_record).not.toBeNull(); expect(lifecycle.getSnapshot().status).toBe("failed");
    revoke.mockResolvedValueOnce(undefined);
    await lifecycle.enable(); expect(current.cleanup_record).toBeNull(); expect(lifecycle.getSnapshot().status).toBe("enabled");
    expect(revoke.mock.calls.length).toBeGreaterThan(1);
  });
  it("clears a Cloud-accepted lost response before enabling a fresh UUID", async () => {
    await lifecycle.recover(account); register.mockRejectedValueOnce(new Error("response lost")); await lifecycle.enable();
    const pendingId = current.pending_registration!.registration.binding_id;
    await lifecycle.disable(); expect(current.cleanup_record?.pending_registration?.registration.binding_id).toBe(pendingId);
    revoke.mockResolvedValueOnce(undefined); await lifecycle.enable();
    expect(current.cleanup_record).toBeNull(); expect(current.binding?.binding_id).not.toBe(pendingId);
  });
  it("a paused disable state read never clears a newer account or family", async () => {
    await lifecycle.recover(account); let release!: (value: WorkerState) => void;
    vi.mocked(workerMessage).mockImplementationOnce((() => new Promise<WorkerState>(resolve => { release = resolve; })) as unknown as typeof workerMessage);
    const disabling = lifecycle.disable(); await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    const nextAccount = { ...account, userId: id(20), session: { ...account.session, id: id(21) } };
    getAccount.mockResolvedValue(nextAccount); await lifecycle.recover(nextAccount); const callsBefore = vi.mocked(workerMessage).mock.calls.length;
    release({ ...state(), binding: { ...binding, owner_user_id: id(20), session_id: id(21) } }); await disabling;
    expect(vi.mocked(workerMessage).mock.calls.slice(callsBefore).filter(call => call[1].type === "PUSH_CLEAR")).toHaveLength(0);
    expect(revoke).not.toHaveBeenCalled();
  });
  it("stale enable response cannot bind after logout", async () => {
    await lifecycle.recover(account); let release!: (value: typeof binding) => void;
    register.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    const enabling = lifecycle.enable(); await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    await lifecycle.logout(); release(binding); await enabling;
    expect(lifecycle.getSnapshot().status).toBe("off"); expect(vi.mocked(workerMessage).mock.calls.filter(call => call[1].type === "PUSH_BIND")).toHaveLength(0);
  });
  it("same-family workspace changes reconcile the old workspace before asking for fresh consent", async () => {
    current.pending_registration = { owner_user_id: id(1), session_id: id(2), workspace_id: id(10), expected_epoch: 0, registration: { browser_id: id(6), binding_id: id(4), replaces_binding_id: null, ...material } };
    register.mockResolvedValueOnce({ ...binding, workspace_id: id(10) }); revoke.mockResolvedValueOnce(undefined);
    await lifecycle.recover(account); expect(register.mock.calls[0][0]).toBe(id(10)); expect(revoke).toHaveBeenCalledWith(id(10), id(5), id(4), undefined); expect(current.pending_registration).toBeNull(); expect(lifecycle.getSnapshot().status).toBe("off");
  });
  it("a signed-out retry keeps the unconfirmed captured scope until clear succeeds", async () => {
    await lifecycle.recover(account); vi.mocked(workerMessage).mockRejectedValueOnce(new Error("worker unavailable"));
    expect(await lifecycle.logout()).toBe(false); expect(sessionStorage.getItem("allies:push-cleanup:v1")).not.toBeNull();
    vi.mocked(workerMessage).mockRejectedValueOnce(new Error("still unavailable"));
    expect(await lifecycle.logout()).toBe(false); expect(sessionStorage.getItem("allies:push-cleanup:v1")).not.toBeNull();
    expect(await lifecycle.logout()).toBe(true); expect(sessionStorage.getItem("allies:push-cleanup:v1")).toBeNull();
  });
  it("foreign pending scope is preserved until explicit account replacement", async () => {
    current.pending_registration = { owner_user_id: id(20), session_id: id(21), workspace_id: id(10), expected_epoch: 0, registration: { browser_id: id(6), binding_id: id(4), replaces_binding_id: null, ...material } };
    await lifecycle.recover(account); expect(current.pending_registration).not.toBeNull(); expect(register).not.toHaveBeenCalled(); expect(revoke).not.toHaveBeenCalled();
  });
  it("a stale broadcast account cannot clear a newer bound family", async () => {
    await lifecycle.recover(account);
    current.binding = { ...binding, session_id: id(21) }; current.epoch = 3;
    getAccount.mockResolvedValue({ ...account, session: { ...account.session, id: id(21) } });
    const callsBefore = vi.mocked(workerMessage).mock.calls.length;
    await lifecycle.recover(account);
    expect(current.binding.session_id).toBe(id(21)); expect(lifecycle.getSnapshot().status).toBe("off");
    expect(vi.mocked(workerMessage).mock.calls.slice(callsBefore).filter(call => call[1].type === "PUSH_CLEAR")).toHaveLength(0);
  });
  it("explicit cross-family enable rotates logical browser identity and obtains fresh native material", async () => {
    const nextAccount = { ...account, session: { ...account.session, id: id(21) } };
    getAccount.mockResolvedValue(nextAccount); current.binding = binding; current.epoch = 1;
    await lifecycle.recover(nextAccount);
    expect(lifecycle.getSnapshot().status).toBe("off"); expect(current.binding).toEqual(binding);
    const freshMaterial = { ...material, endpoint: "https://fcm.googleapis.com/new-family" };
    getSubscription.mockResolvedValueOnce(null).mockResolvedValueOnce({ toJSON: () => freshMaterial });
    const cloudBindings = new Map([[`${id(1)}:${id(6)}`, { binding_id: id(4), session_id: id(2) }]]);
    register.mockImplementationOnce(async (_workspace, input) => {
      const active = cloudBindings.get(`${id(1)}:${input.browser_id}`);
      if (active && (active.session_id !== nextAccount.session.id || input.replaces_binding_id !== active.binding_id)) throw { kind: "conflict", code: "push_binding_conflict" };
      if (!active && input.replaces_binding_id !== null) throw { kind: "conflict", code: "push_binding_conflict" };
      return { ...binding, browser_id: input.browser_id, session_id: nextAccount.session.id, binding_id: input.binding_id };
    });
    await lifecycle.enable();
    expect(lifecycle.getSnapshot().status).toBe("enabled"); expect(current.browser_id).not.toBe(id(6));
    expect(register.mock.calls[0][1].endpoint).toBe(freshMaterial.endpoint); expect(register.mock.calls[0][1].replaces_binding_id).toBeNull();
    expect(revoke).not.toHaveBeenCalled();
  });
  it("unconfirmed local clear retains a validated old scope across startup without touching a replacement", async () => {
    await lifecycle.recover(account); vi.mocked(workerMessage).mockRejectedValueOnce(new Error("worker unavailable"));
    expect(await lifecycle.logout()).toBe(false);
    expect(JSON.parse(sessionStorage.getItem("allies:push-cleanup:v1")!)).toEqual({ owner_user_id: id(1), session_id: id(2) });
    current.binding = { ...binding, session_id: id(21) }; current.epoch = 2;
    stop(); stop = lifecycle.start();
    await vi.waitFor(() => expect(vi.mocked(workerMessage).mock.calls.at(-1)?.[1].type).toBe("PUSH_STATE"));
    expect(current.binding.session_id).toBe(id(21));
  });
  it("scoped logout reconciles bind-wins but never clears a replacement family; retries are bounded", async () => {
    let clears = 0;
    vi.stubGlobal("MessageChannel", MessageChannel);
    registration = { active: { postMessage(request: { type: string }, ports: { postMessage: (value: unknown) => void }[]) {
      if (request.type === "PUSH_STATE") ports[0].postMessage({ ...state(), epoch: clears, binding });
      else { clears += 1; ports[0].postMessage({ type: "PUSH_ACK", accepted: clears === 2, epoch: clears, binding_id: binding.binding_id, enabled: true }); }
    } } } as unknown as ServiceWorkerRegistration;
    expect(await clearLogoutBinding(registration, { owner_user_id: id(1), session_id: id(2) }, state())).toBe(true); expect(clears).toBe(2);
    expect(await clearLogoutBinding(registration, { owner_user_id: id(1), session_id: id(10) })).toBe(false); expect(clears).toBe(2);
    registration = { active: { postMessage(request: { type: string }, ports: { postMessage: (value: unknown) => void }[]) { ports[0].postMessage(request.type === "PUSH_STATE" ? { ...state(), binding } : { type: "PUSH_ACK", accepted: false, epoch: 0, binding_id: id(4), enabled: true }); } } } as unknown as ServiceWorkerRegistration;
    expect(await clearLogoutBinding(registration, { owner_user_id: id(1), session_id: id(2) })).toBe(false);
  });
  it("navigation validates the authenticated main conversation before rendering", () => {
    expect(matchesPushTarget(`?push_workspace=${id(3)}&push_conversation=${id(8)}`, id(3), id(8))).toBe(true);
    expect(matchesPushTarget(`?push_workspace=${id(3)}&push_conversation=${id(8)}`, id(3), id(9))).toBe(false);
    expect(matchesPushTarget("?push_workspace=https://evil.example", id(3), id(8))).toBe(false);
  });
});
