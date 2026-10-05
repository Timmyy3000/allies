"use client";

import type { AllyViewModel } from "@allies/cloud-client";
import { useState } from "react";

import { SafeInputDetail, SiteMark, useSafeInputs } from "../home/ally-safe-inputs";

import { AllyDots, Chevron, SettingsSection, SheetLayer } from "./account-parts";
import styles from "./account.module.css";

/** DSN-011 15–19: saved logins, which Allies can use them, and their detail. */
export function AccountSafeInputs({ workspaceId, allies }: { workspaceId: string; allies: AllyViewModel[] }) {
  const query = useSafeInputs(workspaceId);
  const [managing, setManaging] = useState<string | null>(null);
  const items = query.data ?? [];
  const managed = items.find((item) => item.id === managing);

  if (!query.isPending && !query.isError && items.length === 0) return null;

  return (
    <SettingsSection title="Safe inputs" meta={items.length ? `${items.length} saved` : undefined} busy={query.isPending}>
      {query.isPending ? <div className={styles.rowSkeleton} /> : query.isError ? (
        <p className={styles.inlineError} role="alert">
          We couldn&apos;t load Safe inputs.{" "}
          <button type="button" className={styles.textAction} onClick={() => void query.refetch()}>Try again</button>
        </p>
      ) : (
        <div className={styles.group}>
          {items.map((item) => (
            <button key={item.id} type="button" className={styles.row} onClick={() => setManaging(item.id)}>
              <SiteMark name={item.name} />
              <span className={styles.rowCopy}><strong>{item.name}</strong><small>{item.website}</small></span>
              <AllyDots allies={allies.filter((ally) => item.allyIds.includes(ally.id))} />
              <Chevron />
            </button>
          ))}
        </div>
      )}
      {managed ? (
        <SheetLayer bare onDismiss={() => setManaging(null)}>
          <SafeInputDetail workspaceId={workspaceId} item={managed} onClose={() => setManaging(null)} />
        </SheetLayer>
      ) : null}
    </SettingsSection>
  );
}
