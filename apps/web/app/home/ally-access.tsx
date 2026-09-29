"use client";

import type { IntegrationConnection, IntegrationGrantLevel, IntegrationProvider } from "@allies/cloud-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { alliesQueryKey } from "../../lib/allies/query-keys";
import {
  INTEGRATION_PROVIDERS,
  INTEGRATIONS,
  integrationAccessProblem,
  type IntegrationAccessProblem,
  type IntegrationReturn,
} from "../../lib/integrations/integration-connect";
import { useSession } from "../../lib/session/session-context";

import styles from "./ally-settings-dialog.module.css";

export function integrationConnectionQueryKey(workspaceId: string, provider: IntegrationProvider) {
  return [...alliesQueryKey(workspaceId), "integrations", provider] as const;
}

export function AllyAccess({ workspaceId, allyId, returned = null }: { workspaceId: string; allyId: string; returned?: IntegrationReturn | null }) {
  return (
    <section className={styles.profileSection} aria-labelledby="ally-access-title">
      <div className={styles.profileSectionHead}><h4 id="ally-access-title">Access</h4></div>
      <div className={styles.profileList}>
        {INTEGRATION_PROVIDERS.map((provider) => (
          <AccessRow
            key={provider}
            workspaceId={workspaceId}
            allyId={allyId}
            provider={provider}
            returnedFailure={returned?.status === "failed" && returned.provider === provider ? returned.message : null}
          />
        ))}
      </div>
    </section>
  );
}

function AccessRow({ workspaceId, allyId, provider, returnedFailure }: {
  workspaceId: string;
  allyId: string;
  provider: IntegrationProvider;
  returnedFailure: string | null;
}) {
  const session = useSession();
  const queryClient = useQueryClient();
  const { label, grantLevel } = INTEGRATIONS[provider];
  const queryKey = integrationConnectionQueryKey(workspaceId, provider);
  const connectionQuery = useQuery({
    queryKey,
    queryFn: ({ signal }) => session.runCloudOperation(
      (operationSignal) => session.client.getIntegrationConnection(workspaceId, provider, operationSignal),
      { signal },
    ),
    retry: false,
  });
  const [problem, setProblem] = useState<IntegrationAccessProblem | null>(null);
  const [pendingLevel, setPendingLevel] = useState<IntegrationGrantLevel | null>(null);
  const [connecting, setConnecting] = useState(false);
  const busyRef = useRef(false);

  const connect = async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setConnecting(true);
    setProblem(null);
    try {
      const started = await session.runCloudOperation(
        (signal) => session.client.beginIntegrationConnect(
          workspaceId,
          provider,
          { allyId, grantLevel, returnTo: `/home/${encodeURIComponent(allyId)}` },
          crypto.randomUUID(),
          signal,
        ),
        { csrf: true, retryTransient: false },
      );
      window.location.assign(started.authUrl);
    } catch (caught) {
      setProblem(integrationAccessProblem(caught, provider));
      busyRef.current = false;
      setConnecting(false);
    }
  };

  const setAccess = async (connection: IntegrationConnection, enabled: boolean) => {
    if (busyRef.current) return;
    const current = connection.allyGrants.find((grant) => grant.allyId === allyId)?.level ?? "none";
    if (enabled && current !== "none") return;
    const level = enabled ? grantLevel : "none";
    busyRef.current = true;
    setPendingLevel(level);
    setProblem(null);
    try {
      const grant = await session.runCloudOperation(
        (signal) => session.client.setIntegrationGrant(workspaceId, provider, allyId, level, signal),
        { csrf: true, retryTransient: false },
      );
      queryClient.setQueryData<IntegrationConnection | null>(queryKey, (previous) => previous && {
        ...previous,
        allyGrants: [...previous.allyGrants.filter((candidate) => candidate.allyId !== allyId), grant],
      });
    } catch (caught) {
      setProblem(integrationAccessProblem(caught, provider));
      void queryClient.invalidateQueries({ queryKey, exact: true });
    } finally {
      busyRef.current = false;
      setPendingLevel(null);
    }
  };

  let row;
  if (connectionQuery.isPending) {
    row = <div className={styles.routineSkeleton} aria-busy="true" />;
  } else if (connectionQuery.isError) {
    row = (
      <p className={styles.profileInlineError}>
        We couldn&apos;t load {label}.{" "}
        <button type="button" onClick={() => void connectionQuery.refetch()}>Try again</button>
      </p>
    );
  } else if (!connectionQuery.data || problem?.reconnect) {
    const reconnect = Boolean(connectionQuery.data);
    row = (
      <div className={styles.accessRow}>
        <IntegrationLogo provider={provider} />
        <span className={styles.accessCopy}><strong>{label}</strong></span>
        <button type="button" className={styles.accessConnect} aria-label={`${reconnect ? "Reconnect" : "Connect"} ${label}`} onClick={() => void connect()} disabled={connecting}>
          {connecting ? "Opening Google…" : reconnect ? "Reconnect" : "Connect"}
        </button>
      </div>
    );
  } else {
    const connection = connectionQuery.data;
    const level = connection.allyGrants.find((grant) => grant.allyId === allyId)?.level ?? "none";
    const checked = pendingLevel ? pendingLevel !== "none" : level !== "none";
    row = (
      <label className={styles.accessRow}>
        <IntegrationLogo provider={provider} />
        <span className={styles.accessCopy}>
          <strong>{label}</strong>
          <small>{connection.accountEmail}</small>
        </span>
        <input
          type="checkbox"
          role="switch"
          className={styles.accessSwitch}
          aria-label={`${label} access`}
          checked={checked}
          disabled={pendingLevel !== null || Boolean(problem?.locked)}
          onChange={(event) => void setAccess(connection, event.target.checked)}
        />
      </label>
    );
  }

  return (
    <>
      {row}
      {problem ? <p className={styles.profileInlineError} role="alert">{problem.message}</p> : null}
      {!problem && returnedFailure ? <p className={styles.profileInlineError} role="alert">{returnedFailure}</p> : null}
    </>
  );
}

export function IntegrationLogo({ provider }: { provider: IntegrationProvider }) {
  return provider === "calendar" ? <CalendarLogo /> : <GmailLogo />;
}

export function GmailLogo() {
  return (
    <svg className={styles.accessLogo} aria-hidden="true" viewBox="0 0 48 48">
      <path fill="#4caf50" d="M45 16.2l-5 2.75-5 4.75V40h7a3 3 0 0 0 3-3V16.2z" />
      <path fill="#1e88e5" d="M3 16.2l3.61 1.71L13 23.7V40H6a3 3 0 0 1-3-3V16.2z" />
      <path fill="#e53935" d="M35 11.2L24 19.45 13 11.2l-1 5.8 1 6.7 11 8.25 11-8.25 1-6.7z" />
      <path fill="#c62828" d="M3 12.3v3.9l10 7.5V11.2L9.88 8.86A4.3 4.3 0 0 0 3 12.3z" />
      <path fill="#fbc02d" d="M45 12.3v3.9l-10 7.5V11.2l3.12-2.34A4.3 4.3 0 0 1 45 12.3z" />
    </svg>
  );
}

export function CalendarLogo() {
  return (
    <svg className={styles.accessLogo} aria-hidden="true" viewBox="0 0 48 48">
      <rect x="6" y="6" width="36" height="36" rx="4" fill="#ffffff" />
      <path fill="#1e88e5" d="M10 6h28a4 4 0 0 1 4 4v6H6v-6a4 4 0 0 1 4-4z" />
      <rect x="6" y="6" width="36" height="36" rx="4" fill="none" stroke="#dadce0" strokeWidth="2" />
      <rect x="14" y="3" width="4" height="8" rx="2" fill="#1a73e8" />
      <rect x="30" y="3" width="4" height="8" rx="2" fill="#1a73e8" />
      <path fill="#1a73e8" d="M20.4 23.6l2.1-1.5h2.2v12.3h-2.6v-9.2l-1.7 1.2z" />
      <path fill="#34a853" d="M28 25.6c0-1.6 1.3-3 3.2-3s3.2 1.2 3.2 2.9c0 1-.5 1.8-1.4 2.3 1.1.5 1.7 1.4 1.7 2.6 0 1.9-1.6 3.2-3.5 3.2s-3.5-1.3-3.5-3.2h2.4c0 .6.5 1 1.1 1s1.1-.4 1.1-1c0-.7-.5-1.1-1.2-1.1h-.9v-1.8h.8c.6 0 1-.4 1-.9s-.4-.9-1-.9-1 .4-1 1H28z" />
    </svg>
  );
}
