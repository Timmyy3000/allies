"use client";

import type { AllyViewModel, IntegrationConnection, IntegrationProvider } from "@allies/cloud-client";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { AllyAvatar } from "../../components/ally-avatar";
import { allySubtitle, resolveAllyAppearance } from "../../lib/allies/appearance";
import { INTEGRATION_PROVIDERS, INTEGRATIONS, integrationAccessProblem, readIntegrationReturn } from "../../lib/integrations/integration-connect";
import { useSession } from "../../lib/session/session-context";
import { IntegrationLogo, integrationConnectionQueryKey } from "../home/ally-access";
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
  const queries = useQueries({
    queries: INTEGRATION_PROVIDERS.map((provider) => ({
      queryKey: integrationConnectionQueryKey(workspaceId, provider),
      queryFn: ({ signal }: { signal: AbortSignal }) => session.runCloudOperation(
        (operationSignal: Signal) => session.client.getIntegrationConnection(workspaceId, provider, operationSignal),
        { signal },
      ),
      retry: false,
    })),
  });
  const [open, setOpen] = useState<IntegrationProvider | null>(null);
  const [connecting, setConnecting] = useState<IntegrationProvider | null>(null);
  const [problem, setProblem] = useState<string | null>(() =>
    typeof window === "undefined" ? null : failedReturn(new URLSearchParams(window.location.search)));

  const connect = async (provider: IntegrationProvider) => {
    if (connecting) return;
    setConnecting(provider);
    setProblem(null);
    try {
      const started = await session.runCloudOperation(
        (signal: Signal) => session.client.beginIntegrationConnect(
          workspaceId,
          provider,
          { grantLevel: INTEGRATIONS[provider].grantLevel, returnTo: "/account" },
          crypto.randomUUID(),
          signal,
        ),
        { csrf: true, retryTransient: false },
      );
      window.location.assign(started.authUrl);
    } catch (caught) {
      setProblem(integrationAccessProblem(caught, provider).message);
      setConnecting(null);
    }
  };

  const connectedCount = queries.filter((query) => query.data).length;
  const openIndex = open ? INTEGRATION_PROVIDERS.indexOf(open) : -1;
  const openConnection = openIndex >= 0 ? queries[openIndex]?.data ?? null : null;

  return (
    <SettingsSection title="Connections" meta={connectedCount ? `${connectedCount} connected` : undefined} busy={queries.some((query) => query.isPending)}>
      {INTEGRATION_PROVIDERS.map((provider, index) => {
        const query = queries[index]!;
        const { label } = INTEGRATIONS[provider];
        const connection = query.data ?? null;
        return query.isPending ? <div key={provider} className={styles.rowSkeleton} /> : query.isError ? (
          <div key={provider} className={styles.group}>
            <div className={styles.row}>
              <IntegrationLogo provider={provider} />
              <span className={styles.rowCopy}><strong>{label}</strong><small className={styles.danger}>Couldn&apos;t load</small></span>
              <button type="button" className={styles.pillAction} onClick={() => void query.refetch()}>Try again</button>
            </div>
          </div>
        ) : connection ? (
          <div key={provider} className={styles.group}>
            <button type="button" className={styles.row} onClick={() => setOpen(provider)}>
              <IntegrationLogo provider={provider} />
              <span className={styles.rowCopy}><strong>{label}</strong><small>{connection.accountEmail}</small></span>
              <AllyDots allies={alliesWithAccess(connection, allies)} />
              <Chevron />
            </button>
          </div>
        ) : (
          <div key={provider} className={styles.group}>
            <div className={styles.row}>
              <IntegrationLogo provider={provider} />
              <span className={styles.rowCopy}><strong>{label}</strong><small>Not connected</small></span>
              <button type="button" className={styles.pillPrimary} aria-label={`Connect ${label}`} onClick={() => void connect(provider)} disabled={connecting !== null}>
                {connecting === provider ? "Opening Google…" : "Connect"}
              </button>
            </div>
          </div>
        );
      })}
      {problem ? <p className={styles.inlineError} role="alert">{problem}</p> : null}
      {open && openConnection ? (
        <ConnectionDetail workspaceId={workspaceId} provider={open} connection={openConnection} allies={allies} onClose={() => setOpen(null)} />
      ) : null}
    </SettingsSection>
  );
}

function failedReturn(params: URLSearchParams): string | null {
  const returned = readIntegrationReturn(params);
  return returned?.status === "failed" ? returned.message : null;
}

function alliesWithAccess(connection: IntegrationConnection, allies: AllyViewModel[]) {
  const granted = new Set(connection.allyGrants.filter((grant) => grant.level !== "none").map((grant) => grant.allyId));
  return allies.filter((ally) => granted.has(ally.id));
}

function ConnectionDetail({ workspaceId, provider, connection, allies, onClose }: {
  workspaceId: string;
  provider: IntegrationProvider;
  connection: IntegrationConnection;
  allies: AllyViewModel[];
  onClose: () => void;
}) {
  const session = useSession();
  const queryClient = useQueryClient();
  const { label, grantLevel } = INTEGRATIONS[provider];
  const queryKey = integrationConnectionQueryKey(workspaceId, provider);
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
        (signal: Signal) => session.client.setIntegrationGrant(workspaceId, provider, allyId, enabled ? grantLevel : "none", signal),
        { csrf: true, retryTransient: false },
      );
      queryClient.setQueryData<IntegrationConnection | null>(queryKey, (previous) => previous && {
        ...previous,
        allyGrants: [...previous.allyGrants.filter((candidate) => candidate.allyId !== allyId), grant],
      });
    } catch (caught) {
      setProblem(integrationAccessProblem(caught, provider).message);
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
        (signal: Signal) => session.client.disconnectIntegration(workspaceId, provider, signal),
        { csrf: true, retryTransient: false },
      );
      queryClient.setQueryData(queryKey, null);
      onClose();
    } catch (caught) {
      setProblem(integrationAccessProblem(caught, provider).message);
      void queryClient.invalidateQueries({ queryKey, exact: true });
    } finally {
      busy.current = false;
      setPending(null);
    }
  };

  const close = () => { if (!busy.current) onClose(); };

  return (
    <SheetLayer onDismiss={close}>
      <section className={sheet.subsheet} role="dialog" aria-modal="true" aria-labelledby={view === "disconnect" ? "connection-title" : undefined} aria-label={view === "disconnect" ? undefined : label}>
        <div className={sheet.subsheetHead}>
          <h3 id="connection-title">{view === "disconnect" ? `Disconnect ${label}?` : ""}</h3>
          <button type="button" className={sheet.subsheetClose} aria-label="Close" onClick={close} disabled={pending !== null}>×</button>
        </div>
        {view === "detail" ? (
          <>
            <div className={styles.identity}>
              <IntegrationLogo provider={provider} />
              <strong>{label}</strong>
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
                      aria-label={`${ally.name} can use ${label}`}
                      checked={pending === ally.id ? !checked : checked}
                      disabled={pending !== null}
                      onChange={(event) => void setAccess(ally.id, event.target.checked)}
                    />
                  </label>
                );
              })}
            </div>
            <button type="button" className={styles.greyPill} onClick={() => setView("disconnect")}>Disconnect {label}</button>
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
