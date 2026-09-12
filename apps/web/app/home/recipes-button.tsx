"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import styles from "./recipes-button.module.css";

export function RecipesButton({ children, className }: { children: ReactNode; className: string }) {
  const [announcement, setAnnouncement] = useState(0);
  const [closing, setClosing] = useState(false);
  const dismiss = useCallback(() => {
    setClosing(true);
    window.setTimeout(() => setAnnouncement(0), 180);
  }, []);
  useEffect(() => {
    if (!announcement) return;
    const timeout = setTimeout(dismiss, 4000);
    return () => clearTimeout(timeout);
  }, [announcement, dismiss]);

  return <>
    <button type="button" className={className} aria-label="Recipes" onClick={() => { setClosing(false); setAnnouncement((value) => value + 1); }}>{children}</button>
    <div className={styles.announcement} role="status" aria-live="polite" aria-atomic="true">
      {announcement ? <div className={styles.toast} data-closing={closing ? "true" : undefined}>
        <span>Recipes are coming soon.</span>
        <button type="button" aria-label="Dismiss notification" onClick={dismiss}>×</button>
      </div> : null}
    </div>
  </>;
}
