"use client";

import type { AllyViewModel } from "@allies/cloud-client";
import { useEffect, type ReactNode } from "react";

import { resolveAllyAppearance } from "../../lib/allies/appearance";
import sheet from "../home/ally-settings-dialog.module.css";

import styles from "./account.module.css";

export function SettingsSection({ title, meta, busy = false, children }: {
  title: string;
  meta?: string;
  busy?: boolean;
  children: ReactNode;
}) {
  const id = `settings-${title.toLowerCase().replace(/\W+/gu, "-")}`;
  return (
    <section className={styles.section} aria-labelledby={id} aria-busy={busy}>
      <div className={styles.sectionHead}>
        <h2 id={id}>{title}</h2>
        {meta ? <span>{meta}</span> : null}
      </div>
      {children}
    </section>
  );
}

/** Coloured dots naming the Allies that can use something. */
export function AllyDots({ allies }: { allies: AllyViewModel[] }) {
  if (!allies.length) return null;
  const shown = allies.slice(0, 3);
  return (
    <span className={styles.allyDots} role="img" aria-label={`Used by ${allies.map((ally) => ally.name).join(", ")}`}>
      {shown.map((ally) => (
        <span key={ally.id} style={{ background: resolveAllyAppearance(ally)?.color ?? "var(--text-muted)" }} />
      ))}
      {allies.length > shown.length ? <small>+{allies.length - shown.length}</small> : null}
    </span>
  );
}

export function Chevron() {
  return (
    <svg className={styles.chevron} viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/** Pins a bottom sheet to the viewport. `bare` hosts a child that brings its own scrim. */
export function SheetLayer({ onDismiss, bare = false, children }: { onDismiss: () => void; bare?: boolean; children: ReactNode }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onDismiss(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDismiss]);

  return (
    <div className={styles.sheetLayer}>
      {bare ? children : (
        <div className={sheet.subsheetScrim} onClick={(event) => { if (event.target === event.currentTarget) onDismiss(); }}>
          {children}
        </div>
      )}
    </div>
  );
}
