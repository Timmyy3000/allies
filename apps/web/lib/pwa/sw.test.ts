import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { webcrypto } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
const id = (n: number) => `00000000-0000-4000-8000-${n.toString().padStart(12, "0")}`;
const scope = { owner_user_id: id(1), session_id: id(2) };
const source = { type: "window", url: "https://allies.example/account" };
const material = { endpoint: "https://fcm.googleapis.com/test", keys: { p256dh: "B".repeat(87), auth: "A".repeat(22) } };
type Event = { waitUntil: (promise: Promise<unknown>) => void; [key: string]: unknown };
type Notification = { data: Record<string, unknown>; close: () => void };
function harness(records = new Map<string, unknown>()) {
  const handlers = new Map<string, (event: Event) => void>();
  const notifications: Notification[] = [];
  const navigate = vi.fn(async () => windowClient);
  const focus = vi.fn(async () => windowClient);
  const windowClient = { ...source, navigate, focus, postMessage: vi.fn() };
  const show = vi.fn(async (_title: string, options: { data: Record<string, unknown> }) => { const notice = { data: options.data, close: vi.fn(() => { const index = notifications.indexOf(notice); if (index >= 0) notifications.splice(index, 1); }) }; notifications.push(notice); });
  const unsubscribe = vi.fn(async () => true);
  const subscription = { toJSON: () => material, unsubscribe };
  const self = { location: { origin: "https://allies.example" }, addEventListener: (type: string, handler: (event: Event) => void) => handlers.set(type, handler), skipWaiting: async () => undefined, clients: { claim: async () => undefined, matchAll: vi.fn(async () => [windowClient]), openWindow: vi.fn() }, registration: { showNotification: show, getNotifications: async () => notifications.slice(), pushManager: { getSubscription: async () => subscription, subscribe: vi.fn(async () => subscription) } } };
  const indexedDB = { open() {
    const open: { result?: unknown; onsuccess?: () => void; onerror?: () => void } = {};
    queueMicrotask(() => {
      open.result = { close() {}, transaction() {
        const tx: { oncomplete?: () => void; onerror?: () => void; onabort?: () => void; objectStore?: () => unknown; abort?: () => void } = {};
        tx.abort = () => queueMicrotask(() => tx.onabort?.());
        tx.objectStore = () => ({ get(key: string) { const request: { result?: unknown; onsuccess?: () => void } = {}; queueMicrotask(() => { request.result = structuredClone(records.get(key)); request.onsuccess?.(); }); return request; }, put(value: unknown, key: string) { records.set(key, structuredClone(value)); queueMicrotask(() => tx.oncomplete?.()); } });
        return tx;
      } };
      open.onsuccess?.();
    }); return open;
  } };
  runInNewContext(readFileSync(new URL("../../public/sw.js", import.meta.url), "utf8"), { self, indexedDB, crypto: webcrypto, TextEncoder, Uint8Array, structuredClone, URL, Date, atob, queueMicrotask });
  async function dispatch(type: string, values: Record<string, unknown>) { let done = Promise.resolve(); handlers.get(type)?.({ ...values, waitUntil(promise) { done = promise.then(() => undefined); } }); await done; }
  async function message(data: Record<string, unknown>, client = source) { let reply: Record<string, unknown> | undefined; await dispatch("message", { source: client, data, ports: [{ postMessage: (value: Record<string, unknown>) => { reply = value; } }] }); return reply!; }
  async function bind(bindingId = id(4), owner = scope, expected?: number) {
    const state = await message({ type: "PUSH_STATE" });
    const epoch = expected ?? state.epoch;
    const registration = { browser_id: state.browser_id, binding_id: bindingId, replaces_binding_id: null, ...material };
    await message({ type: "PUSH_PREPARE", expected_epoch: epoch, ...owner, workspace_id: id(3), registration });
    return message({ type: "PUSH_BIND", expected_epoch: epoch, binding: { subscription_id: id(5), browser_id: state.browser_id, binding_id: bindingId, workspace_id: id(3), ...owner, state: "active", enabled: true } });
  }
  const payload = (binding = id(4), notification = id(6)) => ({ version: 1, notification_id: notification, binding_id: binding, kind: "reply_completed", title: "Shaka", body: "Hello there", workspace_id: id(3), ally_id: id(7), conversation_id: id(8), expires_at: new Date(Date.now() + 60000).toISOString() });
  const push = (value = payload()) => dispatch("push", { data: { text: () => JSON.stringify(value), json: () => value } });
  return { records, message, bind, push, payload, dispatch, self, show, notifications, navigate, focus, unsubscribe };
}
describe("real push service worker", () => {
  it("persists CAS across restart; scoped logout rejects another owner or new family", async () => {
    const h = harness(); expect((await h.bind()).accepted).toBe(true);
    const restarted = harness(h.records);
    expect((await restarted.bind(id(9), scope, 0)).accepted).toBe(false);
    expect((await restarted.message({ type: "PUSH_CLEAR", expected_pending_binding_id: null, expected_epoch: 1, binding_id: id(4), logout_scope: { ...scope, session_id: id(10) } })).accepted).toBe(false);
    expect((await restarted.message({ type: "PUSH_CLEAR", expected_pending_binding_id: null, expected_epoch: 1, binding_id: id(4), logout_scope: scope })).accepted).toBe(true);
    expect((await restarted.bind(id(9), scope, 1)).accepted).toBe(false);
    expect((await restarted.message({ type: "PUSH_STATE" })).binding).toBeNull();
    expect(restarted.unsubscribe).toHaveBeenCalledOnce();
  });
  it("first pending writer wins; exact replay survives restart and binds only matching workspace", async () => {
    const h = harness(); const state = await h.message({ type: "PUSH_STATE" });
    const prepare = { type: "PUSH_PREPARE", expected_epoch: 0, ...scope, workspace_id: id(3), registration: { browser_id: state.browser_id, binding_id: id(4), replaces_binding_id: null, ...material } };
    expect((await h.message(prepare)).accepted).toBe(true);
    expect((await h.message({ ...prepare, registration: { ...prepare.registration, binding_id: id(9) } })).accepted).toBe(false);
    const restart = harness(h.records); expect((await restart.message(prepare)).accepted).toBe(true);
    const binding = { subscription_id: id(5), browser_id: state.browser_id, binding_id: id(4), workspace_id: id(10), ...scope, state: "active", enabled: true };
    expect((await restart.message({ type: "PUSH_BIND", expected_epoch: 0, binding })).accepted).toBe(false);
    expect((await restart.message({ type: "PUSH_BIND", expected_epoch: 0, binding: { ...binding, workspace_id: id(3) } })).accepted).toBe(true);
    expect((await restart.message({ type: "PUSH_STATE" })).pending_registration).toBeNull();
  });
  it("clear ACK waits for a paused display and closes it, foreground accepted pushes still display", async () => {
    const h = harness(); await h.bind(); let release!: () => void;
    const original = h.show.getMockImplementation()!;
    h.show.mockImplementationOnce(async (title, options) => { await new Promise<void>(resolve => { release = resolve; }); await original(title, options); });
    const pushed = h.push(); await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    let acknowledged = false;
    const clear = h.message({ type: "PUSH_CLEAR", expected_pending_binding_id: null, expected_epoch: 1, binding_id: id(4), logout_scope: scope }).then(reply => { acknowledged = true; return reply; });
    await Promise.resolve(); expect(acknowledged).toBe(false);
    release(); await pushed; expect((await clear).accepted).toBe(true); expect(h.notifications).toHaveLength(0);
  });
  it("dedupes, rejects expired/malformed/foreign pushes, and navigates only canonical same-origin Ally paths", async () => {
    const h = harness(); await h.bind(); await h.push(); await h.push();
    await h.push({ ...h.payload(), expires_at: new Date(0).toISOString() });
    await h.push({ ...h.payload(id(9)), notification_id: id(10) });
    await h.push({ ...h.payload(), url: "https://evil.example" } as ReturnType<typeof h.payload>);
    expect(h.show).toHaveBeenCalledOnce();
    await h.dispatch("notificationclick", { notification: h.notifications[0] });
    expect(h.navigate).toHaveBeenCalledWith(`/home/${id(7)}?push_workspace=${id(3)}&push_conversation=${id(8)}`);
    expect(h.focus).toHaveBeenCalledOnce();
    await h.message({ type: "PUSH_CLEAR", expected_pending_binding_id: null, expected_epoch: 1, binding_id: id(4), logout_scope: scope });
    await h.dispatch("notificationclick", { notification: { data: h.payload(), close() {} } });
    expect(h.navigate).toHaveBeenCalledOnce();
  });
  it("a prepare after a state read rejects stale exact clear at the same epoch", async () => {
    const h = harness(); const state = await h.message({ type: "PUSH_STATE" });
    await h.message({ type: "PUSH_PREPARE", expected_epoch: 0, ...scope, workspace_id: id(3), registration: { browser_id: state.browser_id, binding_id: id(4), replaces_binding_id: null, ...material } });
    expect((await h.message({ type: "PUSH_CLEAR", expected_pending_binding_id: null, expected_epoch: 0, binding_id: null, logout_scope: null })).accepted).toBe(false);
    expect((await h.message({ type: "PUSH_STATE" })).pending_registration).not.toBeNull();
    expect((await h.message({ type: "PUSH_CLEAR", expected_pending_binding_id: id(4), expected_epoch: 0, binding_id: null, logout_scope: scope })).accepted).toBe(true);
  });
  it("clear retains inactive reconciliation bytes and stale cleanup cannot erase a newer record", async () => {
    const h = harness(); await h.bind();
    const before = await h.message({ type: "PUSH_STATE" });
    const pending = { type: "PUSH_PREPARE", expected_epoch: 1, ...scope, workspace_id: id(3), registration: { browser_id: before.browser_id, binding_id: id(9), replaces_binding_id: id(4), ...material } };
    await h.message(pending);
    await h.message({ type: "PUSH_CLEAR", expected_epoch: 1, expected_pending_binding_id: id(9), binding_id: id(4), logout_scope: scope });
    const cleared = await h.message({ type: "PUSH_STATE" });
    const record = cleared.cleanup_record as { cleanup_id: string; binding: { binding_id: string }; pending_registration: { registration: { binding_id: string } } };
    expect(record.binding.binding_id).toBe(id(4)); expect(record.pending_registration.registration.binding_id).toBe(id(9)); expect(cleared.binding).toBeNull();
    expect((await h.message({ ...pending, expected_epoch: 2 })).accepted).toBe(false);
    expect((await h.message({ type: "PUSH_CLEANED", expected_epoch: 2, cleanup_id: id(100) })).accepted).toBe(false);
    expect((await h.message({ type: "PUSH_CLEANED", expected_epoch: 2, cleanup_id: record.cleanup_id, rotate_browser_id: true })).accepted).toBe(true);
    const handedOff = await h.message({ type: "PUSH_STATE" }); expect(handedOff.browser_id).not.toBe(before.browser_id); expect(handedOff.epoch).toBe(3);
    expect((await h.message({ type: "PUSH_CLEANED", expected_epoch: 2, cleanup_id: record.cleanup_id })).accepted).toBe(false);
    expect((await h.bind(id(11))).accepted).toBe(true);
    await h.message({ type: "PUSH_CLEAR", expected_epoch: 4, expected_pending_binding_id: null, binding_id: id(11), logout_scope: scope });
    const newer = (await h.message({ type: "PUSH_STATE" })).cleanup_record;
    expect((await h.message({ type: "PUSH_CLEANED", expected_epoch: 2, cleanup_id: record.cleanup_id })).accepted).toBe(false);
    expect((await h.message({ type: "PUSH_STATE" })).cleanup_record).toEqual(newer);
  });
  it("native unsubscribe and replacement subscribe share the display/clear queue", async () => {
    const h = harness(); await h.bind(); let release!: () => void;
    h.unsubscribe.mockImplementationOnce(() => new Promise(resolve => { release = () => resolve(true); }));
    let acknowledged = false;
    const clear = h.message({ type: "PUSH_CLEAR", expected_epoch: 1, expected_pending_binding_id: null, binding_id: id(4), logout_scope: scope }).then(reply => { acknowledged = true; return reply; });
    await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    const stale = h.message({ type: "PUSH_SUBSCRIBE", expected_epoch: 1, vapid_public_key: "B".repeat(87) });
    expect(acknowledged).toBe(false); release(); expect((await clear).accepted).toBe(true); expect((await stale).accepted).toBe(false);
    expect((await h.message({ type: "PUSH_SUBSCRIBE", expected_epoch: 2, vapid_public_key: "B".repeat(87) })).accepted).toBe(true);
  });
  it("closed-worker subscription changes fence old pushes and retain inactive recovery identity", async () => {
    const h = harness(); await h.bind(); await h.dispatch("pushsubscriptionchange", {});
    const state = await h.message({ type: "PUSH_STATE" });
    expect(state.binding).toBeNull(); expect(state.epoch).toBe(2); expect(state.renewal_needed).toBe(true); expect(state.renewal_binding).toMatchObject({ binding_id: id(4), ...scope });
    await h.push(); expect(h.show).not.toHaveBeenCalled();
    expect((await h.message({ type: "PUSH_SUBSCRIBE", expected_epoch: 1, vapid_public_key: "B".repeat(87) })).accepted).toBe(false);
    expect(await h.message({ type: "PUSH_STATE" }, { type: "window", url: "https://evil.example/" })).toBeUndefined();
  });
});
