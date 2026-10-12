"use client";

import type { AllyViewModel, WebSearchBackend, WebSearchConnection as WebSearchConnectionData } from "@allies/cloud-client";
import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import Image from "next/image";
import { useRef, useState, type CSSProperties, type FormEvent } from "react";

import { AllyAvatar } from "../../components/ally-avatar";
import { allySubtitle, resolveAllyAppearance } from "../../lib/allies/appearance";
import {
  WEB_SEARCH_KEY_LENGTH,
  WEB_SEARCH_PROVIDERS,
  webSearchConnectProblem,
  webSearchConnectionQueryKey,
  webSearchAccessProblem,
} from "../../lib/integrations/web-search";
import { useSession } from "../../lib/session/session-context";
import sheet from "../home/ally-settings-dialog.module.css";

import { AllyDots, Chevron, SheetLayer, namesList } from "./account-parts";
import styles from "./account.module.css";

type Signal = AbortSignal | undefined;

export function useWebSearchConnectionQuery(workspaceId: string) {
  const session = useSession();
  return useQuery({
    queryKey: webSearchConnectionQueryKey(workspaceId),
    queryFn: ({ signal }) => session.runCloudOperation(
      (operationSignal: Signal) => session.client.getWebSearchConnection(workspaceId, operationSignal),
      { signal },
    ),
  });
}

export function WebSearchConnection({ workspaceId, allies, query }: {
  workspaceId: string;
  allies: AllyViewModel[];
  query: UseQueryResult<WebSearchConnectionData | null>;
}) {
  const [sheetView, setSheetView] = useState<"detail" | "connect" | null>(null);
  const connection = query.data ?? null;

  const row = query.isPending ? <div className={styles.rowSkeleton} /> : query.isError ? (
    <div className={styles.group}>
      <div className={styles.row}>
        <WebSearchLogo />
        <span className={styles.rowCopy}><strong>Web search</strong><small className={styles.danger}>Couldn&apos;t load</small></span>
        <button type="button" className={styles.pillAction} onClick={() => void query.refetch()}>Try again</button>
      </div>
    </div>
  ) : connection ? (
    <div className={styles.group}>
      <button type="button" className={styles.row} onClick={() => setSheetView("detail")}>
        <WebSearchLogo />
        <span className={styles.rowCopy}><strong>Web search</strong><small>{WEB_SEARCH_PROVIDERS[connection.backend].label} · ending {connection.keyHint}</small></span>
        <AllyDots allies={alliesWithAccess(connection, allies)} />
        <Chevron />
      </button>
    </div>
  ) : (
    <div className={styles.group}>
      <div className={styles.row}>
        <WebSearchLogo />
        <span className={styles.rowCopy}><strong>Web search</strong><small>Not connected</small></span>
        <button type="button" className={styles.pillPrimary} aria-label="Connect Web search" onClick={() => setSheetView("connect")}>Connect</button>
      </div>
    </div>
  );

  return (
    <>
      {row}
      {sheetView === "detail" && connection ? (
        <WebSearchDetail workspaceId={workspaceId} connection={connection} allies={allies} onReplace={() => setSheetView("connect")} onClose={() => setSheetView(null)} />
      ) : null}
      {sheetView === "connect" ? (
        <WebSearchConnectSheet workspaceId={workspaceId} connection={connection} onClose={() => setSheetView(null)} />
      ) : null}
    </>
  );
}

function WebSearchLogo() {
  return <Image className={sheet.accessLogo} src="/home/mobile-roster/search.svg" alt="" width={22} height={22} />;
}

function alliesWithAccess(connection: WebSearchConnectionData, allies: AllyViewModel[]) {
  const granted = new Set(connection.allyGrants.filter((grant) => grant.level !== "none").map((grant) => grant.allyId));
  return allies.filter((ally) => granted.has(ally.id));
}

function WebSearchDetail({ workspaceId, connection, allies, onReplace, onClose }: {
  workspaceId: string;
  connection: WebSearchConnectionData;
  allies: AllyViewModel[];
  onReplace: () => void;
  onClose: () => void;
}) {
  const session = useSession();
  const queryClient = useQueryClient();
  const queryKey = webSearchConnectionQueryKey(workspaceId);
  const { label } = WEB_SEARCH_PROVIDERS[connection.backend];
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
        (signal: Signal) => session.client.setWebSearchGrant(workspaceId, allyId, enabled ? "use" : "none", signal),
        { csrf: true, retryTransient: false },
      );
      queryClient.setQueryData<WebSearchConnectionData | null>(queryKey, (previous) => previous && {
        ...previous,
        allyGrants: [...previous.allyGrants.filter((candidate) => candidate.allyId !== allyId), grant],
      });
    } catch (caught) {
      setProblem(webSearchAccessProblem(caught));
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
        (signal: Signal) => session.client.disconnectWebSearch(workspaceId, signal),
        { csrf: true, retryTransient: false },
      );
      queryClient.setQueryData(queryKey, null);
      onClose();
    } catch (caught) {
      setProblem(webSearchAccessProblem(caught));
      void queryClient.invalidateQueries({ queryKey, exact: true });
    } finally {
      busy.current = false;
      setPending(null);
    }
  };

  const close = () => { if (!busy.current) onClose(); };

  return (
    <SheetLayer onDismiss={close}>
      <section className={sheet.subsheet} role="dialog" aria-modal="true" aria-labelledby={view === "disconnect" ? "connection-title" : undefined} aria-label={view === "disconnect" ? undefined : "Web search"}>
        <div className={sheet.subsheetHead}>
          <h3 id="connection-title">{view === "disconnect" ? "Disconnect Web search?" : ""}</h3>
          <button type="button" className={sheet.subsheetClose} aria-label="Close" onClick={close} disabled={pending !== null}>×</button>
        </div>
        {view === "detail" ? (
          <>
            <div className={styles.identity}>
              <WebSearchLogo />
              <strong>Web search</strong>
              <small><span className={styles.connectedDot} aria-hidden="true" />Connected · {label} · ending {connection.keyHint}</small>
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
                      style={appearance ? { "--access-accent": appearance.color } as CSSProperties : undefined}
                      aria-label={`${ally.name} can use Web search`}
                      checked={pending === ally.id ? !checked : checked}
                      disabled={pending !== null}
                      onChange={(event) => void setAccess(ally.id, event.target.checked)}
                    />
                  </label>
                );
              })}
            </div>
            <button type="button" className={styles.greyPill} onClick={onReplace} disabled={pending !== null}>Replace key</button>
            <button type="button" className={styles.greyPill} onClick={() => setView("disconnect")}>Disconnect Web search</button>
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

function WebSearchConnectSheet({ workspaceId, connection, onClose }: {
  workspaceId: string;
  connection: WebSearchConnectionData | null;
  onClose: () => void;
}) {
  const session = useSession();
  const queryClient = useQueryClient();
  const queryKey = webSearchConnectionQueryKey(workspaceId);
  const [backend, setBackend] = useState<WebSearchBackend>(connection?.backend ?? "parallel");
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const busy = useRef(false);
  const { label, keyUrl } = WEB_SEARCH_PROVIDERS[backend];

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy.current) return;
    const apiKey = String(new FormData(event.currentTarget).get("apiKey") ?? "").trim();
    if (apiKey.length < WEB_SEARCH_KEY_LENGTH.min || apiKey.length > WEB_SEARCH_KEY_LENGTH.max) {
      setProblem("That key doesn't look right.");
      return;
    }
    busy.current = true;
    setSubmitting(true);
    setProblem(null);
    try {
      const saved = await session.runCloudOperation(
        (signal: Signal) => session.client.connectWebSearch(workspaceId, { backend, apiKey }, signal),
        { csrf: true, retryTransient: false },
      );
      queryClient.setQueryData<WebSearchConnectionData | null>(queryKey, saved);
      onClose();
    } catch (caught) {
      setProblem(webSearchConnectProblem(caught, label));
    } finally {
      busy.current = false;
      setSubmitting(false);
    }
  };

  const close = () => { if (!busy.current) onClose(); };

  return (
    <SheetLayer onDismiss={close}>
      <section className={sheet.subsheet} role="dialog" aria-modal="true" aria-label={connection ? "Replace key" : "Connect Web search"}>
        <div className={sheet.subsheetHead}>
          <h3>{connection ? "Replace key" : "Connect Web search"}</h3>
          <button type="button" className={sheet.subsheetClose} aria-label="Close" onClick={close} disabled={submitting}>×</button>
        </div>
        <form onSubmit={(event) => void submit(event)}>
          <p className={sheet.settingsHelp}>{connection ? "This replaces what's saved. Allies with access keep it." : "Allies can search once you turn it on for them."}</p>
          <div className={sheet.settingsField}>
            <label htmlFor="web-search-provider">Provider</label>
            <select id="web-search-provider" className={sheet.settingsInput} name="backend" value={backend} disabled={submitting} onChange={(event) => setBackend(event.target.value as WebSearchBackend)}>
              {(Object.keys(WEB_SEARCH_PROVIDERS) as WebSearchBackend[]).map((option) => (
                <option key={option} value={option}>{WEB_SEARCH_PROVIDERS[option].label}</option>
              ))}
            </select>
          </div>
          <a className={sheet.settingsHelp} href={keyUrl} target="_blank" rel="noopener noreferrer">Get a {label} key</a>
          <div className={sheet.settingsField}>
            <label htmlFor="web-search-api-key">API key</label>
            <input id="web-search-api-key" className={sheet.settingsInput} name="apiKey" type="password" autoComplete="off" maxLength={WEB_SEARCH_KEY_LENGTH.max} required disabled={submitting} />
          </div>
          <button type="submit" className={sheet.subsheetPrimary} disabled={submitting}>
            {submitting ? "Checking key…" : connection ? "Replace" : "Connect"}
          </button>
        </form>
        {problem ? <p className={styles.inlineError} role="alert">{problem}</p> : null}
      </section>
    </SheetLayer>
  );
}
