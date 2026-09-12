"use client";

import { useEffect, useState, type ReactNode } from "react";
import styles from "./recipes-button.module.css";

export function RecipesButton({ children, className }: { children: ReactNode; className: string }) {
  const [announcement, setAnnouncement] = useState(0);
  useEffect(() => {
    if (!announcement) return;
    const timeout = setTimeout(() => setAnnouncement(0), 4000);
    return () => clearTimeout(timeout);
  }, [announcement]);

  return <>
    <button type="button" className={className} aria-label="Recipes" onClick={() => setAnnouncement((value) => value + 1)}>{children}</button>
    <div className={styles.announcement} role="status" aria-live="polite" aria-atomic="true">
      {announcement ? <div className={styles.toast} key={announcement}>
        <span>Recipes are coming soon.</span>
        <button type="button" aria-label="Dismiss notification" onClick={() => setAnnouncement(0)}>×</button>
      </div> : null}
    </div>
  </>;
}
