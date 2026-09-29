"use client";

import type { AllyViewModel, GmailConnection } from "@allies/cloud-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { AllyAvatar } from "../../components/ally-avatar";
import { allySubtitle, resolveAllyAppearance } from "../../lib/allies/appearance";
import { gmailAccessProblem, readGmailReturn } from "../../lib/integrations/gmail-connect";
import { useSession } from "../../lib/session/session-context";
import { GmailLogo, gmailConnectionQueryKey } from "../home/ally-access";
import sheet from "../home/ally-settings-dialog.module.css";

import { AllyDots, Chevron, SettingsSection, SheetLayer } from "./account-parts";
import styles from "./account.module.css";

type Signal = AbortSignal | undefined;

export function namesList(allies: AllyViewModel[]): string {
  const names = allies.map((ally) => ally.name);
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

/** DSN-006 frames 6–8, 13: account-level connections with per-Ally access. */
export function AccountConnections({ workspaceId, allies }: { workspaceId: string; allies: AllyViewModel[] }) {
  const session = useSession();
  const queryKey = gmailConnectionQueryKey(workspaceId);
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => session.runCloudOperation(
      (operationSignal: Signal) => session.client.getGmailConnection(workspaceId, operationSignal),
      { signal },
    ),
    retry: false,
  });
  const [open, setOpen] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [problem, setProblem] = useState<string | null>(() =>
    typeof window === "undefined" ? null : failedReturn(new URLSearchParams(window.location.search)));

  const connect = async () => {
    if (connecting) return;
    setConnecting(true);
    setProblem(null);
    try {
      const started = await session.runCloudOperation(
        (signal: Signal) => session.client.beginGmailConnect(
          workspaceId,
          { grantLevel: "read", returnTo: "/account" },
          crypto.randomUUID(),
          signal,
        ),
        { csrf: true, retryTransient: false },
      );
      window.location.assign(started.authUrl);
    } catch (caught) {
      setProblem(gmailAccessProblem(caught).message);
      setConnecting(false);
    }
  };

  const connection = query.data ?? null;
  const withAccess = connection ? alliesWithAccess(connection, allies) : [];

  return (
    <SettingsSection title="Connections" meta={connection ? "1 connected" : undefined} busy={query.isPending}>
      {query.isPending ? <div className={styles.rowSkeleton} /> : query.isError ? (
        <div className={styles.group}>
          <div className={styles.row}>
            <GmailLogo />
            <span className={styles.rowCopy}><strong>Gmail</strong><small className={styles.danger}>Couldn&apos;t load</small></span>
            <button type="button" className={styles.pillAction} onClick={() => void query.refetch()}>Try again</button>
          </div>
        </div>
      ) : connection ? (
        <div className={styles.group}>
          <button type="button" className={styles.row} onClick={() => setOpen(true)}>
            <GmailLogo />
            <span className={styles.rowCopy}><strong>Gmail</strong><small>{connection.accountEmail}</small></span>
            <AllyDots allies={withAccess} />
            <Chevron />
          </button>
        </div>
      ) : (
        <div className={styles.group}>
          <div className={styles.row}>
            <GmailLogo />
            <span className={styles.rowCopy}><strong>Gmail</strong><small>Not connected</small></span>
            <button type="button" className={styles.pillPrimary} onClick={() => void connect()} disabled={connecting}>
              {connecting ? "Opening Google…" : "Connect"}
            </button>
          </div>
        </div>
      )}
      {problem ? <p className={styles.inlineError} role="alert">{problem}</p> : null}
      {open && connection ? (
        <ConnectionDetail workspaceId={workspaceId} connection={connection} allies={allies} onClose={() => setOpen(false)} />
      ) : null}
    </SettingsSection>
  );
}

function failedReturn(params: URLSearchParams): string | null {
  const returned = readGmailReturn(params);
  return returned?.status === "failed" ? returned.message : null;
}

function alliesWithAccess(connection: GmailConnection, allies: AllyViewModel[]) {
  const granted = new Set(connection.allyGrants.filter((grant) => grant.level !== "none").map((grant) => grant.allyId));
  return allies.filter((ally) => granted.has(ally.id));
}

function ConnectionDetail({ workspaceId, connection, allies, onClose }: {
  workspaceId: string;
  connection: GmailConnection;
  allies: AllyViewModel[];
  onClose: () => void;
}) {
  const session = useSession();
  const queryClient = useQueryClient();
  const queryKey = gmailConnectionQueryKey(workspaceId);
  const [view, setView] = useState<"detail" | "disconnect">("detail");
  const [pending, setPending] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const busy = useRef(false);
  const withAccess = alliesWithAccess(connection, allies);

  const setAccess = async (allyId: string, enabled: boolean) => {
    if (busy.current) return;
    busy.current = true;
    setPending(allyId);
    setProblem(null);
    try {
      const grant = await session.runCloudOperation(
        (signal: Signal) => session.client.setGmailGrant(workspaceId, allyId, enabled ? "read" : "none", signal),
        { csrf: true, retryTransient: false },
      );
      queryClient.setQueryData<GmailConnection | null>(queryKey, (previous) => previous && {
        ...previous,
        allyGrants: [...previous.allyGrants.filter((candidate) => candidate.allyId !== allyId), grant],
      });
    } catch (caught) {
      setProblem(gmailAccessProblem(caught).message);
      void queryClient.invalidateQueries({ queryKey, exact: true });
    } finally {
      busy.current = false;
      setPending(null);
    }
  };

  const disconnect = async () => {
    if (busy.current) return;
    busy.current = true;
    setPending("disconnect");
    setProblem(null);
    try {
      await session.runCloudOperation(
        (signal: Signal) => session.client.disconnectGmail(workspaceId, signal),
        { csrf: true, retryTransient: false },
      );
      queryClient.setQueryData(queryKey, null);
      onClose();
    } catch (caught) {
      setProblem(gmailAccessProblem(caught).message);
      void queryClient.invalidateQueries({ queryKey, exact: true });
    } finally {
      busy.current = false;
      setPending(null);
    }
  };

  const close = () => { if (!busy.current) onClose(); };

  return (
    <SheetLayer onDismiss={close}>
      <section className={sheet.subsheet} role="dialog" aria-modal="true" aria-labelledby={view === "disconnect" ? "connection-title" : undefined} aria-label={view === "disconnect" ? undefined : "Gmail"}>
        <div className={sheet.subsheetHead}>
          <h3 id="connection-title">{view === "disconnect" ? "Disconnect Gmail?" : ""}</h3>
          <button type="button" className={sheet.subsheetClose} aria-label="Close" onClick={close} disabled={pending !== null}>×</button>
        </div>
        {view === "detail" ? (
          <>
            <div className={styles.identity}>
              <GmailLogo />
              <strong>Gmail</strong>
              <small><span className={styles.connectedDot} aria-hidden="true" />Connected · {connection.accountEmail}</small>
            </div>
            <div className={styles.sectionHead}>
              <h3>Allies with access</h3>
              <span>{withAccess.length} of {allies.length}</span>
            </div>
            <div className={styles.group}>
              {allies.map((ally) => {
                const appearance = resolveAllyAppearance(ally);
                const checked = withAccess.includes(ally);
                return (
                  <label key={ally.id} className={styles.row}>
                    {appearance ? <AllyAvatar shape={appearance.shape} color={appearance.color} size={36} label="" /> : null}
                    <span className={styles.rowCopy}><strong>{ally.name}</strong><small>{allySubtitle(ally)}</small></span>
                    <input
                      type="checkbox"
                      role="switch"
                      className={sheet.accessSwitch}
                      style={appearance ? { "--access-accent": appearance.color } as React.CSSProperties : undefined}
                      aria-label={`${ally.name} can use Gmail`}
                      checked={pending === ally.id ? !checked : checked}
                      disabled={pending !== null}
                      onChange={(event) => void setAccess(ally.id, event.target.checked)}
                    />
                  </label>
                );
              })}
            </div>
            <button type="button" className={styles.greyPill} onClick={() => setView("disconnect")}>Disconnect Gmail</button>
          </>
        ) : (
          <>
            <p className={styles.sheetCopy}>
              {withAccess.length
                ? `${namesList(withAccess)} will stop using it straight away.`
                : "No Ally is using it right now."}
            </p>
            <button type="button" className={sheet.deleteButton} onClick={() => void disconnect()} disabled={pending !== null}>
              {pending === "disconnect" ? "Disconnecting…" : "Disconnect"}
            </button>
            <button type="button" className={sheet.subsheetPrimary} onClick={() => setView("detail")} disabled={pending !== null}>Cancel</button>
          </>
        )}
        {problem ? <p className={styles.inlineError} role="alert">{problem}</p> : null}
      </section>
    </SheetLayer>
  );
}
