"use client";

import Link from "next/link";
import { useState } from "react";
import styles from "./invite-required-notice.module.css";

export function InviteRequiredNotice({ visible }: { visible: boolean }) {
  const [dismissed, setDismissed] = useState(false);
  if (!visible || dismissed) return null;

  const dismiss = () => {
    setDismissed(true);
    const url = new URL(window.location.href);
    url.searchParams.delete("auth_error");
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  };

  return (
    <div className={styles.position}>
      <div className={styles.toast} role="alert">
        <div className={styles.message}>
          <p>You’ll need a beta invite to join Allies.</p>
          <Link href="/claim-invite">Claim your invite</Link>
        </div>
        <button type="button" aria-label="Dismiss invite notification" onClick={dismiss}>×</button>
      </div>
    </div>
  );
}
