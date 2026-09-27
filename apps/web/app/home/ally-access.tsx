"use client";

import type { GmailConnection } from "@allies/cloud-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { alliesQueryKey } from "../../lib/allies/query-keys";
import { gmailAccessProblem, type GmailAccessProblem, type GmailReturn } from "../../lib/integrations/gmail-connect";
import { useSession } from "../../lib/session/session-context";

import styles from "./ally-settings-dialog.module.css";

export function gmailConnectionQueryKey(workspaceId: string) {
  return [...alliesQueryKey(workspaceId), "integrations", "gmail"] as const;
}

export function AllyAccess({ workspaceId, allyId, returned = null }: { workspaceId: string; allyId: string; returned?: GmailReturn | null }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const queryKey = gmailConnectionQueryKey(workspaceId);
  const connectionQuery = useQuery({
    queryKey,
    queryFn: ({ signal }) => session.runCloudOperation(
      (operationSignal) => session.client.getGmailConnection(workspaceId, operationSignal),
      { signal },
    ),
    retry: false,
  });
  const [problem, setProblem] = useState<GmailAccessProblem | null>(null);
  const [pendingLevel, setPendingLevel] = useState<"read" | "none" | null>(null);
  const [connecting, setConnecting] = useState(false);
  const busyRef = useRef(false);

  const connect = async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setConnecting(true);
    setProblem(null);
    try {
      const started = await session.runCloudOperation(
        (signal) => session.client.beginGmailConnect(
          workspaceId,
          { allyId, grantLevel: "read", returnTo: `/home/${encodeURIComponent(allyId)}` },
          crypto.randomUUID(),
          signal,
        ),
        { csrf: true, retryTransient: false },
      );
      window.location.assign(started.authUrl);
    } catch (caught) {
      setProblem(gmailAccessProblem(caught));
      busyRef.current = false;
      setConnecting(false);
    }
  };

  const setAccess = async (connection: GmailConnection, enabled: boolean) => {
    if (busyRef.current) return;
    const current = connection.allyGrants.find((grant) => grant.allyId === allyId)?.level ?? "none";
    if (enabled && current !== "none") return;
    const level = enabled ? "read" : "none";
    busyRef.current = true;
    setPendingLevel(level);
    setProblem(null);
    try {
      const grant = await session.runCloudOperation(
        (signal) => session.client.setGmailGrant(workspaceId, allyId, level, signal),
        { csrf: true, retryTransient: false },
      );
      queryClient.setQueryData<GmailConnection | null>(queryKey, (previous) => previous && {
        ...previous,
        allyGrants: [...previous.allyGrants.filter((candidate) => candidate.allyId !== allyId), grant],
      });
    } catch (caught) {
      setProblem(gmailAccessProblem(caught));
      void queryClient.invalidateQueries({ queryKey, exact: true });
    } finally {
      busyRef.current = false;
      setPendingLevel(null);
    }
  };

  let row;
  if (connectionQuery.isPending) {
    row = <div className={styles.routineSkeleton} />;
  } else if (connectionQuery.isError) {
    row = (
      <p className={styles.profileInlineError}>
        We couldn&apos;t load connections.{" "}
        <button type="button" onClick={() => void connectionQuery.refetch()}>Try again</button>
      </p>
    );
  } else if (!connectionQuery.data || problem?.reconnect) {
    const reconnect = Boolean(connectionQuery.data);
    row = (
      <div className={styles.profileList}>
        <div className={styles.accessRow}>
          <GmailLogo />
          <span className={styles.accessCopy}><strong>Gmail</strong></span>
          <button type="button" className={styles.accessConnect} onClick={() => void connect()} disabled={connecting}>
            {connecting ? "Opening Google…" : reconnect ? "Reconnect" : "Connect"}
          </button>
        </div>
      </div>
    );
  } else {
    const connection = connectionQuery.data;
    const level = connection.allyGrants.find((grant) => grant.allyId === allyId)?.level ?? "none";
    const checked = pendingLevel ? pendingLevel === "read" : level !== "none";
    row = (
      <div className={styles.profileList}>
        <label className={styles.accessRow}>
          <GmailLogo />
          <span className={styles.accessCopy}>
            <strong>Gmail</strong>
            <small>{connection.accountEmail}</small>
          </span>
          <input
            type="checkbox"
            role="switch"
            className={styles.accessSwitch}
            aria-label="Gmail access"
            checked={checked}
            disabled={pendingLevel !== null || Boolean(problem?.locked)}
            onChange={(event) => void setAccess(connection, event.target.checked)}
          />
        </label>
      </div>
    );
  }

  return (
    <section className={styles.profileSection} aria-labelledby="ally-access-title" aria-busy={connectionQuery.isPending}>
      <div className={styles.profileSectionHead}><h4 id="ally-access-title">Access</h4></div>
      {row}
      {problem ? <p className={styles.profileInlineError} role="alert">{problem.message}</p> : null}
      {!problem && returned?.status === "failed" ? <p className={styles.profileInlineError} role="alert">{returned.message}</p> : null}
    </section>
  );
}

function GmailLogo() {
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
