"use strict";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const COPY = { approval_needed: "An approval needs your attention.", routine_completed: "A routine completed.", routine_failed: "A routine failed.", reply_completed: "Your Ally has replied." };
let queue = Promise.resolve();
let reconciled = false;
function enqueue(work) {
  const next = queue.then(work);
  queue = next.catch(() => undefined);
  return next;
}
function validBinding(b) {
  return b && b.enabled === true && b.state === "active" && ["subscription_id", "browser_id", "binding_id", "workspace_id", "session_id", "owner_user_id"].every(key => UUID.test(b[key]));
}
function validPayload(p) {
  return p && Object.keys(p).sort().join() === "ally_id,binding_id,body,conversation_id,expires_at,kind,notification_id,title,version,workspace_id" && p.version === 1 && Object.hasOwn(COPY, p.kind) && ["notification_id", "binding_id", "workspace_id", "ally_id", "conversation_id"].every(key => UUID.test(p[key])) && typeof p.title === "string" && (p.body === null || typeof p.body === "string") && typeof p.expires_at === "string" && /Z$/.test(p.expires_at) && Date.parse(p.expires_at) > Date.now() && Date.parse(p.expires_at) <= Date.now() + 86400000;
}
function validRegistration(r) {
  return r && Object.keys(r).sort().join() === "binding_id,browser_id,endpoint,keys,replaces_binding_id" && UUID.test(r.browser_id) && UUID.test(r.binding_id) && (r.replaces_binding_id === null || UUID.test(r.replaces_binding_id)) && typeof r.endpoint === "string" && r.endpoint.length <= 2048 && r.endpoint.startsWith("https://") && r.keys && Object.keys(r.keys).sort().join() === "auth,p256dh" && /^[A-Za-z0-9_-]{87}$/.test(r.keys.p256dh) && /^[A-Za-z0-9_-]{22}$/.test(r.keys.auth);
}
function database() {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open("allies-push-v1", 1);
    open.onupgradeneeded = () => open.result.createObjectStore("state");
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(new Error("push_storage_unavailable"));
  });
}
async function transaction(update) {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction("state", "readwrite");
      const store = tx.objectStore("state");
      const read = store.get("current");
      let result;
      read.onsuccess = () => {
        let state = read.result ?? { browser_id: crypto.randomUUID(), epoch: 0, binding: null, renewal_needed: false, pending_registration: null, renewal_binding: null, material_fingerprint: null, cleanup_record: null, seen: [] };
        if (!Number.isSafeInteger(state.epoch) || state.epoch < 0 || !UUID.test(state.browser_id)) { tx.abort(); return; }
        if (!validBinding(state.binding)) state.binding = null;
        result = update(state);
        store.put(state, "current");
      };
      tx.oncomplete = () => resolve(result);
      tx.onerror = tx.onabort = () => reject(new Error("push_storage_unavailable"));
    });
  } finally { db.close(); }
}
const readState = () => transaction(state => structuredClone(state));
async function closeStale(binding) {
  const notifications = await self.registration.getNotifications();
  for (const notification of notifications) {
    if (!binding || notification.data?.binding_id !== binding.binding_id) notification.close();
  }
}
async function reconcile() {
  if (!reconciled) {
    await closeStale((await readState()).binding);
    reconciled = true;
  }
}
async function broadcast() {
  for (const client of await self.clients.matchAll({ type: "window", includeUncontrolled: true })) {
    if (new URL(client.url).origin === self.location.origin) client.postMessage({ type: "PUSH_CHANGED" });
  }
}
function ack(state, accepted) {
  return { type: "PUSH_ACK", accepted, epoch: state.epoch, binding_id: state.binding?.binding_id ?? null, enabled: !!state.binding };
}
self.addEventListener("install", event => event.waitUntil(self.skipWaiting()));
self.addEventListener("activate", event => event.waitUntil(enqueue(async () => { await reconcile(); await self.clients.claim(); })));
self.addEventListener("message", event => {
  event.waitUntil(enqueue(async () => {
    const source = event.source;
    if (!source || source.type !== "window" || new URL(source.url).origin !== self.location.origin || !event.ports[0]) return;
    try {
      await reconcile();
      const message = event.data;
      if (message?.type === "PUSH_STATE") {
        const state = await readState();
        event.ports[0].postMessage({ type: "PUSH_STATE", epoch: state.epoch, browser_id: state.browser_id, binding: state.binding, renewal_needed: state.renewal_needed, pending_registration: state.pending_registration, renewal_binding: state.renewal_binding, material_fingerprint: state.material_fingerprint, cleanup_record: state.cleanup_record });
        return;
      }
      if (message?.type === "PUSH_SUBSCRIBE") {
        const state = await readState();
        if (message.expected_epoch !== state.epoch || typeof message.vapid_public_key !== "string" || !/^[A-Za-z0-9_-]{87}$/.test(message.vapid_public_key)) { event.ports[0].postMessage({ type: "PUSH_SUBSCRIPTION", accepted: false, subscription: null }); return; }
        const bytes = Uint8Array.from(atob(message.vapid_public_key.replace(/-/g, "+").replace(/_/g, "/")), character => character.charCodeAt(0));
        const subscription = await self.registration.pushManager.getSubscription() ?? await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes });
        event.ports[0].postMessage({ type: "PUSH_SUBSCRIPTION", accepted: true, subscription: subscription.toJSON() });
        return;
      }
      const before = message?.type === "PUSH_BIND" ? await readState() : null;
      const material = before?.pending_registration?.registration;
      const fingerprint = material ? Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([material.endpoint, material.keys.p256dh, material.keys.auth])))), byte => byte.toString(16).padStart(2, "0")).join("") : null;
      const result = await transaction(state => {
        if (message?.expected_epoch !== state.epoch || state.epoch === Number.MAX_SAFE_INTEGER) return ack(state, false);
        if (message.type === "PUSH_CLEANED") {
          if (!UUID.test(message.cleanup_id) || state.cleanup_record?.cleanup_id !== message.cleanup_id) return ack(state, false);
          if (message.rotate_browser_id !== undefined && typeof message.rotate_browser_id !== "boolean") return ack(state, false);
          state.cleanup_record = null;
          if (message.rotate_browser_id === true) { state.browser_id = crypto.randomUUID(); state.epoch += 1; }
          return ack(state, true);
        }
        if (message.type === "PUSH_PREPARE") {
          if (state.cleanup_record) return ack(state, false);
          const owner = state.binding ?? state.renewal_binding;
          if (owner && (owner.owner_user_id !== message.owner_user_id || owner.session_id !== message.session_id || owner.workspace_id !== message.workspace_id)) return ack(state, false);
          if (!validRegistration(message.registration) || message.registration.browser_id !== state.browser_id || !UUID.test(message.owner_user_id) || !UUID.test(message.session_id) || !UUID.test(message.workspace_id)) return ack(state, false);
          const pending = { registration: message.registration, expected_epoch: state.epoch, owner_user_id: message.owner_user_id, session_id: message.session_id, workspace_id: message.workspace_id };
          if (state.pending_registration && JSON.stringify(state.pending_registration) !== JSON.stringify(pending)) return ack(state, false);
          state.pending_registration = pending;
          return ack(state, true);
        }
        if (message.type === "PUSH_BIND") {
          if (!validBinding(message.binding) || message.binding.browser_id !== state.browser_id) return ack(state, false);
          const pending = state.pending_registration;
          if (!pending || pending.registration.binding_id !== message.binding.binding_id || pending.owner_user_id !== message.binding.owner_user_id || pending.session_id !== message.binding.session_id || pending.workspace_id !== message.binding.workspace_id) return ack(state, false);
          state.binding = message.binding;
          state.material_fingerprint = fingerprint;
          state.renewal_needed = false;
          state.renewal_binding = null;
          state.pending_registration = null;
        } else if (message.type === "PUSH_CLEAR") {
          if (message.binding_id !== (state.binding?.binding_id ?? null) || message.expected_pending_binding_id !== (state.pending_registration?.registration.binding_id ?? null)) return ack(state, false);
          const scope = message.logout_scope;
          if (scope !== null && (!UUID.test(scope?.owner_user_id) || !UUID.test(scope?.session_id) || (state.binding && (state.binding.owner_user_id !== scope.owner_user_id || state.binding.session_id !== scope.session_id)) || (state.pending_registration && (state.pending_registration.owner_user_id !== scope.owner_user_id || state.pending_registration.session_id !== scope.session_id)) || (state.renewal_binding && (state.renewal_binding.owner_user_id !== scope.owner_user_id || state.renewal_binding.session_id !== scope.session_id)))) return ack(state, false);
          const prior = state.binding ?? state.renewal_binding;
          const pending = state.pending_registration;
          if (prior || pending) {
            const owner = prior ?? pending;
            state.cleanup_record = { cleanup_id: crypto.randomUUID(), owner_user_id: owner.owner_user_id, session_id: owner.session_id, workspace_id: owner.workspace_id, binding: prior, pending_registration: pending };
          }
          state.binding = null;
          state.renewal_binding = null;
          state.material_fingerprint = null;
          state.pending_registration = null;
          state.renewal_needed = false;
        } else return ack(state, false);
        state.epoch += 1;
        return ack(state, true);
      });
      if (result.accepted && message.type !== "PUSH_PREPARE" && message.type !== "PUSH_CLEANED") {
        await closeStale((await readState()).binding);
        if (message.type === "PUSH_CLEAR") {
          try { await (await self.registration.pushManager.getSubscription())?.unsubscribe(); } catch { /* The persistent fence still blocks this subscription. */ }
        }
        await broadcast();
      }
      event.ports[0].postMessage(result);
    } catch { event.ports[0].postMessage({ type: "PUSH_ERROR" }); }
  }));
});
self.addEventListener("pushsubscriptionchange", event => event.waitUntil(enqueue(async () => {
  await reconcile();
  await transaction(state => { state.renewal_binding = state.binding ?? state.renewal_binding; state.binding = null; state.pending_registration = null; state.renewal_needed = true; state.epoch += 1; });
  await closeStale(null);
  await broadcast();
})));
self.addEventListener("push", event => event.waitUntil(enqueue(async () => {
  try {
    await reconcile();
    if (!event.data || new TextEncoder().encode(event.data.text()).length > 1024) return;
    const payload = event.data.json();
    if (!validPayload(payload)) return;
    const admitted = await transaction(state => {
      if (!state.binding || payload.binding_id !== state.binding.binding_id || payload.workspace_id !== state.binding.workspace_id) return false;
      state.seen = (state.seen ?? []).filter(item => item.at > Date.now() - 86400000);
      if (state.seen.some(item => item.id === payload.notification_id)) return false;
      state.seen.push({ id: payload.notification_id, at: Date.now() });
      state.seen = state.seen.slice(-256);
      return true;
    });
    if (admitted) await self.registration.showNotification(payload.title || "Allies", { body: payload.body || COPY[payload.kind], icon: "/allies-icon.svg", tag: `allies:${payload.notification_id}`, renotify: false, data: payload });
  } catch { /* Fail closed when persistent ownership cannot be checked. */ }
})));
self.addEventListener("notificationclick", event => event.waitUntil(enqueue(async () => {
  event.notification.close();
  try {
    await reconcile();
    const payload = event.notification.data;
    const binding = (await readState()).binding;
    if (!validPayload(payload) || !binding || payload.binding_id !== binding.binding_id || payload.workspace_id !== binding.workspace_id) return;
    const path = `/home/${payload.ally_id}?push_workspace=${payload.workspace_id}&push_conversation=${payload.conversation_id}`;
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const existing = windows.find(client => new URL(client.url).origin === self.location.origin);
    if (existing) { const navigated = await existing.navigate(path); await (navigated ?? existing).focus(); }
    else await self.clients.openWindow(path);
  } catch { /* Navigation requires a current persistent binding. */ }
})));
