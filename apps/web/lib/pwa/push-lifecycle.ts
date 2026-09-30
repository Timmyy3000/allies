import { isCloudError, type AccountViewModel, type CloudClient, type PushConfig, type RegisterPush } from "@allies/cloud-client";
import type { RunCloudOperation } from "../session/web-session";
import { readPushCleanupScope, savePushCleanupScope } from "./push-cleanup";
import { isStandalonePwa } from "./pwa-install";
import { belongsTo, clearLogoutBinding, registerPushWorker, workerMessage, type LogoutScope, type WorkerBinding, type WorkerState } from "./push-worker";

export type PushView = { status: "loading" | "unsupported" | "off" | "enabling" | "enabled" | "disabling" | "failed"; message: string; available: boolean };
const INITIAL: PushView = { status: "loading", message: "Checking notifications...", available: false };
export function pushSupport(): string | null {
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (ios && !isStandalonePwa()) return "Add Allies to your Home Screen to enable notifications.";
  if (!window.isSecureContext || !("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "Notifications are not supported in this browser.";
  return null;
}
function scopeOf(account: AccountViewModel): LogoutScope { return { owner_user_id: account.userId, session_id: account.session.id }; }
function subscriptionInput(subscription: PushSubscription): Pick<RegisterPush, "endpoint" | "keys"> {
  const json = subscription.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys.auth) throw new Error("Notifications need a new browser subscription. Try again.");
  return { endpoint: json.endpoint, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth } };
}
async function materialFingerprint(material: Pick<RegisterPush, "endpoint" | "keys">): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([material.endpoint, material.keys.p256dh, material.keys.auth])));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
}
export function createPushLifecycle(client: CloudClient, run: RunCloudOperation) {
  let view = INITIAL;
  const listeners = new Set<() => void>();
  let account: AccountViewModel | null = null;
  let config: PushConfig | null = null;
  let registration: ServiceWorkerRegistration | null = null;
  let generation = 0;
  let operation: AbortController | null = null;
  let heartbeat: ReturnType<typeof setInterval> | null = null;
  const clientId = typeof crypto !== "undefined" ? crypto.randomUUID() : "";
  let sequence = 0;
  let active: WorkerBinding | null = null;
  let cleanupScope: LogoutScope | null = null;
  let cleanupRunning = false;
  const persistScope = (scope: LogoutScope | null) => { cleanupScope = scope; savePushCleanupScope(scope); };
  const publish = (next: PushView) => { view = next; for (const listener of listeners) listener(); };
  const stopPresence = () => { if (heartbeat) clearInterval(heartbeat); heartbeat = null; active = null; };
  const cancel = () => { generation += 1; operation?.abort(); operation = null; stopPresence(); };
  const fail = () => publish({ status: "failed", message: "Notifications need recovery. Try again.", available: !!config?.enabled });
  async function presence(event?: Event) {
    const binding = active;
    if (!binding || !account || !belongsTo(binding, scopeOf(account))) return;
    sequence += 1;
    if (sequence > 2147483647) return;
    try { await run(signal => client.push.presence(binding.workspace_id, binding.subscription_id, { binding_id: binding.binding_id, client_id: clientId, sequence, visible: event?.type !== "pagehide" && document.visibilityState === "visible" }, signal), { csrf: true }); } catch { /* Presence is best effort; Cloud expires stale entries. */ }
  }
  function enabled(binding: WorkerBinding) {
    stopPresence(); active = binding;
    publish({ status: "enabled", message: "Approvals, routines and replies on this browser.", available: true });
    void presence(); heartbeat = setInterval(() => { if (document.visibilityState === "visible") void presence(); }, 20000);
  }
  async function cleanup(accountAtStart: AccountViewModel, state: WorkerState, check: () => void) {
    const record = state.cleanup_record;
    if (!record || !registration) return;
    const scope = scopeOf(accountAtStart);
    if (!belongsTo(record, scope)) throw new Error("cleanup_belongs_to_another_family");
    let pendingBinding: WorkerBinding | null = null;
    if (record.pending_registration) {
      try {
        const result = await run(signal => client.push.register(record.workspace_id, record.pending_registration!.registration, signal), { csrf: true, retryTransient: true }); check();
        if (result.binding_id !== record.pending_registration.registration.binding_id || result.session_id !== record.session_id || result.workspace_id !== record.workspace_id || result.browser_id !== record.pending_registration.registration.browser_id) throw new Error("cleanup_contract");
        pendingBinding = { ...result, owner_user_id: record.owner_user_id, enabled: true };
      } catch (error) {
        check();
        if (!isCloudError(error) || error.code !== "push_binding_conflict") throw error;
      }
    }
    for (const binding of [record.binding, pendingBinding]) {
      if (!binding) continue;
      try { await run(signal => client.push.revoke(binding.workspace_id, binding.subscription_id, binding.binding_id, signal), { csrf: true }); }
      catch (error) { if (!isCloudError(error) || error.status !== 404) throw error; }
      check();
    }
    const ack = await workerMessage(registration, { type: "PUSH_CLEANED", expected_epoch: state.epoch, cleanup_id: record.cleanup_id }); check();
    if (!ack.accepted) throw new Error("cleanup_changed");
  }
  async function register(accountAtStart: AccountViewModel, captured: number, state: WorkerState, consent: boolean) {
    if (!registration || !config?.enabled || !config.vapid_public_key) throw new Error("unavailable");
    const scope = scopeOf(accountAtStart);
    if (!belongsTo(state.binding, scope) || !belongsTo(state.renewal_binding, scope) || !belongsTo(state.pending_registration, scope)) throw new Error("account_changed");
    const controller = new AbortController(); operation = controller;
    const check = () => { if (captured !== generation || controller.signal.aborted || account !== accountAtStart) throw new Error("operation_cancelled"); };
    let subscription = await registration.pushManager.getSubscription(); check();
    if (!subscription) {
      if (!consent && !state.renewal_needed && !state.pending_registration) throw new Error("consent_required");
      const subscribed = await workerMessage(registration, { type: "PUSH_SUBSCRIBE", expected_epoch: state.epoch, vapid_public_key: config.vapid_public_key }); check();
      if (!subscribed.accepted || !subscribed.subscription) throw new Error("stale_subscription");
      subscription = await registration.pushManager.getSubscription(); check();
      if (!subscription) throw new Error("subscription_missing");
    }
    const native = subscriptionInput(subscription);
    const pending = state.pending_registration;
    if (pending && (pending.workspace_id !== accountAtStart.workspace.id || pending.expected_epoch !== state.epoch)) throw new Error("pending_material_changed");
    const input: RegisterPush = pending?.registration ?? { browser_id: state.browser_id, binding_id: crypto.randomUUID(), replaces_binding_id: (state.binding ?? state.renewal_binding)?.binding_id ?? null, ...native };
    const prepared = await workerMessage(registration, { type: "PUSH_PREPARE", expected_epoch: state.epoch, ...scope, workspace_id: accountAtStart.workspace.id, registration: input }); check();
    if (!prepared.accepted) throw new Error("stale_registration");
    let result;
    try { result = await run(signal => client.push.register(accountAtStart.workspace.id, input, signal), { csrf: true, signal: controller.signal, retryTransient: true }); }
    catch (error) {
      check();
      if (isCloudError(error) && error.code === "push_binding_conflict") {
        await workerMessage(registration, { type: "PUSH_CLEAR", expected_epoch: state.epoch, binding_id: state.binding?.binding_id ?? null, expected_pending_binding_id: input.binding_id, logout_scope: null });
      }
      throw error;
    }
    check();
    if (result.binding_id !== input.binding_id || result.browser_id !== input.browser_id || result.workspace_id !== accountAtStart.workspace.id || result.session_id !== scope.session_id) throw new Error("registration_contract");
    const binding: WorkerBinding = { ...result, ...scope, enabled: true };
    const ack = await workerMessage(registration, { type: "PUSH_BIND", expected_epoch: state.epoch, binding }); check();
    if (!ack.accepted) throw new Error("stale_registration");
    enabled(binding);
    if (pending && (native.endpoint !== pending.registration.endpoint || native.keys.p256dh !== pending.registration.keys.p256dh || native.keys.auth !== pending.registration.keys.auth)) {
      await recover(accountAtStart);
    }
  }
  async function disable() {
    const accountAtStart = account;
    const workerAtStart = registration;
    if (!accountAtStart || !workerAtStart) return;
    const scope = scopeOf(accountAtStart);
    cancel(); const captured = generation;
    const check = () => { if (captured !== generation || account !== accountAtStart || registration !== workerAtStart) throw new Error("operation_cancelled"); };
    publish({ status: "disabling", message: "Turning notifications off...", available: true });
    try {
      const state = await workerMessage(workerAtStart, { type: "PUSH_STATE" }); check();
      if (![state.binding, state.pending_registration, state.renewal_binding, state.cleanup_record].every(value => belongsTo(value, scope))) throw new Error("account_changed");
      const ack = await workerMessage(workerAtStart, { type: "PUSH_CLEAR", expected_epoch: state.epoch, binding_id: state.binding?.binding_id ?? null, expected_pending_binding_id: state.pending_registration?.registration.binding_id ?? null, logout_scope: null }); check();
      if (!ack.accepted) throw new Error("stale_disable");
      const nextState = await workerMessage(workerAtStart, { type: "PUSH_STATE" }); check();
      await cleanup(accountAtStart, nextState, check); check();
      publish({ status: "off", message: "Notifications are off on this browser.", available: !!config?.enabled });
    } catch { if (captured === generation) fail(); }
  }
  async function logout(scope?: LogoutScope) {
    const capturedScope = scope ?? (account ? scopeOf(account) : cleanupScope);
    const accountAtStart = account;
    const workerAtStart = registration;
    cancel(); account = null;
    const captured = generation;
    const check = () => { if (captured !== generation || account !== null || registration !== workerAtStart) throw new Error("operation_cancelled"); };
    publish({ status: "off", message: "Notifications are off on this browser.", available: false });
    if (!capturedScope) return true;
    persistScope(capturedScope);
    if (!registration) return false;
    try {
      const state = await workerMessage(registration, { type: "PUSH_STATE" }); check();
      const cleared = await clearLogoutBinding(registration, capturedScope, state);
      check();
      if (!cleared) return false;
      if (cleanupScope === capturedScope) persistScope(null);
      if (accountAtStart) {
        const nextState = await workerMessage(registration, { type: "PUSH_STATE" }); check();
        try { await cleanup(accountAtStart, nextState, check); } catch { /* Server logout still revokes the captured family. */ }
      }

      return true;
    } catch { return false; }
  }
  async function recover(nextAccount: AccountViewModel) {
    cancel(); account = nextAccount; const captured = generation;
    const current = () => captured === generation && account === nextAccount;
    const check = () => { if (!current()) throw new Error("operation_cancelled"); };
    const support = pushSupport();
    if (support) { publish({ status: "unsupported", message: support, available: false }); return; }
    try {
      const freshAccount = await run(signal => client.getCurrentAccount(signal)); check();
      if (freshAccount.userId !== nextAccount.userId || freshAccount.session.id !== nextAccount.session.id || freshAccount.workspace.id !== nextAccount.workspace.id) {
        account = null;
        publish({ status: "off", message: "Your account changed. Reload Allies to continue.", available: false });
        return;
      }
      registration = await registerPushWorker(); check();
      if (cleanupScope) { const capturedScope = cleanupScope; if (await clearLogoutBinding(registration, capturedScope) && cleanupScope === capturedScope) persistScope(null); check(); }
      const [state, nextConfig] = await Promise.all([workerMessage(registration, { type: "PUSH_STATE" }), run(signal => client.push.config(nextAccount.workspace.id, signal))]);
      check();
      config = nextConfig;
      if (state.cleanup_record && belongsTo(state.cleanup_record, scopeOf(nextAccount))) {
        await cleanup(nextAccount, state, check);
        publish({ status: "off", message: "Notifications are off on this browser.", available: config.enabled });
        return;
      }
      const scope = scopeOf(nextAccount);
      const old = state.binding ?? state.renewal_binding;
      if (![old, state.pending_registration, state.cleanup_record].every(value => belongsTo(value, scope))) {
        publish({ status: "off", message: "Enable notifications for this account.", available: config.enabled }); return;
      }
      if ((old && old.workspace_id !== nextAccount.workspace.id) || (state.pending_registration && state.pending_registration.workspace_id !== nextAccount.workspace.id)) {
        publish({ status: "disabling", message: "Clearing notifications from your previous workspace...", available: false });
        const ack = await workerMessage(registration, { type: "PUSH_CLEAR", expected_epoch: state.epoch, binding_id: state.binding?.binding_id ?? null, expected_pending_binding_id: state.pending_registration?.registration.binding_id ?? null, logout_scope: scope }); check();
        if (!ack.accepted) throw new Error("replacement_race");
        const workerState = await workerMessage(registration, { type: "PUSH_STATE" }); check();
        if (workerState.epoch !== ack.epoch || workerState.binding) throw new Error("replacement_race");
        await cleanup(nextAccount, workerState, check); check();
        publish({ status: "off", message: "Enable notifications for this workspace.", available: config.enabled }); return;
      }
      if (!config.enabled) {
        if (state.binding || state.pending_registration || state.renewal_binding) { await disable(); return; }
        publish({ status: "off", message: "Notifications are currently unavailable.", available: false }); return;
      }
      if (Notification.permission === "denied") { publish({ status: "off", message: "Allow notifications in your browser settings, then try again.", available: true }); return; }
      if (state.pending_registration || state.renewal_needed) {
        const fresh = await run(signal => client.getCurrentAccount(signal)); check();
        if (fresh.userId !== nextAccount.userId || fresh.session.id !== nextAccount.session.id || fresh.workspace.id !== nextAccount.workspace.id) throw new Error("account_changed");
        publish({ status: "enabling", message: "Recovering notifications...", available: true });
        await register(nextAccount, captured, state, false); return; }
      if (state.binding) {
        const native = await registration.pushManager.getSubscription(); check();
        if (!native || Notification.permission !== "granted") { fail(); return; }
        const material = subscriptionInput(native);
        const fingerprint = await materialFingerprint(material); check();
        if (state.material_fingerprint === fingerprint) { enabled(state.binding); return; }
        const fresh = await run(signal => client.getCurrentAccount(signal)); check();
        if (fresh.userId !== nextAccount.userId || fresh.session.id !== nextAccount.session.id || fresh.workspace.id !== nextAccount.workspace.id) throw new Error("account_changed");
        publish({ status: "enabling", message: "Recovering notifications...", available: true });
        await register(nextAccount, captured, state, false); return;
      }
      publish({ status: "off", message: "Approvals, routines and replies on this browser.", available: true });
    } catch { if (captured === generation) fail(); }
  }
  function enable() {
    if (!account || !config?.enabled || !registration) return Promise.resolve();
    const permission = Notification.permission === "granted" ? Promise.resolve("granted" as const) : Notification.requestPermission();
    cancel(); const captured = generation; const currentAccount = account;
    publish({ status: "enabling", message: "Turning notifications on...", available: true });
    return (async () => {
      try {
        if (await permission !== "granted") { if (captured === generation) publish({ status: "off", message: "Allow notifications in your browser settings, then try again.", available: true }); return; }
        if (captured !== generation || !registration) return;
        const workerAtStart = registration;
        let state = await workerMessage(workerAtStart, { type: "PUSH_STATE" });
        const check = () => { if (captured !== generation || account !== currentAccount || registration !== workerAtStart) throw new Error("operation_cancelled"); };
        check();
        const verifyAccount = async () => {
          const fresh = await run(signal => client.getCurrentAccount(signal)); check();
          if (fresh.userId !== currentAccount.userId || fresh.session.id !== currentAccount.session.id || fresh.workspace.id !== currentAccount.workspace.id) throw new Error("account_changed");
        };
        await verifyAccount();
        const scope = scopeOf(currentAccount);
        const previous = state.binding ?? state.renewal_binding ?? state.pending_registration ?? state.cleanup_record;
        if (previous && !belongsTo(previous, scope)) {
          const foreignScope = { owner_user_id: previous.owner_user_id, session_id: previous.session_id };
          if (![state.binding, state.renewal_binding, state.pending_registration, state.cleanup_record].every(value => belongsTo(value, foreignScope))) throw new Error("mixed_binding_scopes");
          const ack = await workerMessage(workerAtStart, { type: "PUSH_CLEAR", expected_epoch: state.epoch, binding_id: state.binding?.binding_id ?? null, expected_pending_binding_id: state.pending_registration?.registration.binding_id ?? null, logout_scope: foreignScope }); check();
          if (!ack.accepted) throw new Error("foreign_binding_changed");
          const cleared = await workerMessage(workerAtStart, { type: "PUSH_STATE" }); check();
          if (cleared.epoch !== ack.epoch || !cleared.cleanup_record || !belongsTo(cleared.cleanup_record, foreignScope)) throw new Error("foreign_cleanup_changed");
          await verifyAccount();
          const handedOff = await workerMessage(workerAtStart, { type: "PUSH_CLEANED", expected_epoch: cleared.epoch, cleanup_id: cleared.cleanup_record.cleanup_id, rotate_browser_id: true }); check();
          if (!handedOff.accepted) throw new Error("foreign_cleanup_changed");
          state = await workerMessage(workerAtStart, { type: "PUSH_STATE" }); check();
          if (state.epoch !== handedOff.epoch || state.binding || state.pending_registration || state.cleanup_record || state.browser_id === cleared.browser_id) throw new Error("foreign_handoff_changed");
        } else if (state.cleanup_record) {
          await cleanup(currentAccount, state, check);
          state = await workerMessage(workerAtStart, { type: "PUSH_STATE" }); check();
        }
        await register(currentAccount, captured, state, true);
      } catch { if (captured === generation) fail(); }
    })();
  }
  async function retryLocalCleanup() {
    if (!cleanupScope || cleanupRunning || !("serviceWorker" in navigator) || !window.isSecureContext) return;
    cleanupRunning = true;
    const scope = cleanupScope;
    try {
      const worker = registration ?? await registerPushWorker();
      const cleared = await clearLogoutBinding(worker, scope);
      if (cleared && cleanupScope === scope) persistScope(null);
    } catch { /* A future opening retries only the captured family. */ }
    finally { cleanupRunning = false; }
  }
  const changed = (event: MessageEvent) => {
    if (event.data?.type !== "PUSH_CHANGED") return;
    if (!account) { void retryLocalCleanup(); return; }
    if (view.status !== "enabling" && view.status !== "disabling") void recover(account);
  };
  return {
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    getSnapshot: () => view, getServerSnapshot: () => INITIAL,
    recover, enable, disable, logout,
    async retry() {
      const captured = generation; const previous = account;
      if (!previous) return;
      publish({ status: "loading", message: "Checking notifications...", available: false });
      try {
        const fresh = await run(signal => client.getCurrentAccount(signal));
        if (captured !== generation || account !== previous) return;
        if (fresh.userId !== previous.userId || fresh.session.id !== previous.session.id || fresh.workspace.id !== previous.workspace.id) throw new Error("account_changed");
        await recover(fresh);
      } catch { if (captured === generation) fail(); }
    },
    start() {
      cleanupScope = readPushCleanupScope();
      void retryLocalCleanup();
      document.addEventListener("visibilitychange", presence); window.addEventListener("pagehide", presence);
      navigator.serviceWorker?.addEventListener("message", changed);
      return () => { cancel(); document.removeEventListener("visibilitychange", presence); window.removeEventListener("pagehide", presence); navigator.serviceWorker?.removeEventListener("message", changed); };
    },
  };
}
export type PushLifecycle = ReturnType<typeof createPushLifecycle>;
