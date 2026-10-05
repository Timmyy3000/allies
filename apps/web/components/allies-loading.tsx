"use client";

import Image from "next/image";
import type { CSSProperties } from "react";
import { AllyAvatar, type AllyShape } from "./ally-avatar";
import styles from "./allies-loading.module.css";

const allies: { shape: AllyShape; color: string; left: string; top: string }[] = [
  { shape: "boxy", color: "#fbe65f", left: "76%", top: "19%" },
  { shape: "rolly", color: "#3446e9", left: "23%", top: "34%" },
  { shape: "rocky", color: "#51c56b", left: "25%", top: "78%" },
  { shape: "ghosty", color: "#fd304f", left: "83%", top: "70%" },
];

export function AlliesLoading({ label = "Loading your space" }: { label?: string }) {
  return (
    <main className={styles.page} role="status" aria-label={label}>
      <div className={styles.scene} aria-hidden="true">
        <Image className={styles.brand} src="/allies-icon.svg" alt="" width={96} height={96} priority />
        {allies.map((ally, index) => (
          <div key={ally.shape} className={styles.ally} style={{ left: ally.left, top: ally.top, color: ally.color, "--delay": `${-index * 2.7}s`, "--duration": `${10 + index}s` } as CSSProperties}>
            <svg className={styles.cursor} width="28" height="30" viewBox="0 0 28 30" fill="currentColor"><path d="M3 1.5c-2-.8-3.7 1.1-3 3l8 23c.7 2 3.5 2.1 4.3.2l4.2-9.5 9.1-4.8c1.9-1 1.7-3.7-.3-4.4L3 1.5Z" /></svg>
            <AllyAvatar shape={ally.shape} color={ally.color} size={36} state="idle" motion="system" />
          </div>
        ))}
      </div>
    </main>
  );
}