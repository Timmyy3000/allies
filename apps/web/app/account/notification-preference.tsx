"use client";
import { useSyncExternalStore } from "react";
import type { PushLifecycle } from "../../lib/pwa/push-lifecycle";
import styles from "./account.module.css";

export function NotificationPreference({ push }: { push: PushLifecycle }) {
  const state = useSyncExternalStore(push.subscribe, push.getSnapshot, push.getServerSnapshot);
  const enabled = state.status === "enabled";
  const busy = state.status === "loading" || state.status === "enabling" || state.status === "disabling";
  return <button type="button" className={styles.row} role="switch" aria-label="Notifications" aria-checked={enabled} aria-describedby="notification-status" aria-busy={busy} disabled={busy || (!state.available && state.status !== "failed")} onClick={() => void (enabled ? push.disable() : state.available ? push.enable() : push.retry())}>
    <span className={styles.rowCopy}><strong>Notifications</strong><small id="notification-status" className={styles.notificationCopy} role={state.status === "failed" ? "alert" : "status"}>{state.message}</small></span>
    <span className={styles.notificationToggle} data-enabled={enabled} aria-hidden="true"><span /></span>
  </button>;
}
