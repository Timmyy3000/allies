"use client";

import type { SafeInputRequest } from "@allies/cloud-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { useSession } from "../../lib/session/session-context";
import { SafeInputFields, safeInputsQueryKey } from "./ally-safe-inputs";

import styles from "./safe-input-layer.module.css";

type Signal = AbortSignal | undefined;
// The Ally's tool waits up to four minutes for an answer, so a few seconds of lag is fine.
const POLL_MS = 3_000;
const ERROR_POLL_MS = 15_000;

/** In-chat Safe input requests and the Ally's watch-only browser (DSN-011 1–8, 13). */
export function SafeInputLayer({ workspaceId, allyId, allyName, accent }: { workspaceId: string; allyId: string; allyName: string; accent: string }) {
  const session = useSession();
  const requests = useQuery({
    queryKey: ["safe-inputs", workspaceId, "requests", allyId],
    queryFn: ({ signal }) => session.runCloudOperation(
      (operationSignal: Signal) => session.client.listSafeInputRequests(workspaceId, allyId, operationSignal),
      { signal },
    ),
    refetchInterval: (query) => (query.state.status === "error" ? ERROR_POLL_MS : POLL_MS),
    retry: false,
  });
  const browser = useQuery({
    queryKey: ["safe-inputs", workspaceId, "browser-session", allyId],
    queryFn: ({ signal }) => session.runCloudOperation(
      (operationSignal: Signal) => session.client.getAllyBrowserSession(workspaceId, allyId, operationSignal),
      { signal },
    ),
    refetchInterval: (query) => (query.state.status === "error" ? ERROR_POLL_MS : POLL_MS),
    retry: false,
  });
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const request = requests.data?.find((candidate) => !dismissed.has(candidate.id)) ?? null;
  const { refetch } = requests;
  const requestId = request?.id;
  // Stable across polls so the sheet's "Saved" timer is not restarted by a re-render.
  const done = useCallback(() => {
    if (!requestId) return;
    setDismissed((previous) => new Set(previous).add(requestId));
    void refetch();
  }, [requestId, refetch]);
  const style = { "--safe-accent": accent } as CSSProperties;

  return (
    <div style={style}>
      {browser.data && !request ? <BrowserWindow liveUrl={browser.data.liveUrl} allyName={allyName} /> : null}
      {request?.kind === "new" ? (
        <SafeInputSheet key={request.id} workspaceId={workspaceId} request={request} allyName={allyName} onDone={done} />
      ) : request?.kind === "access" ? (
        <AccessRequest key={request.id} workspaceId={workspaceId} request={request} allyName={allyName} onDone={done} />
      ) : null}
    </div>
  );
}

function BrowserWindow({ liveUrl, allyName }: { liveUrl: string; allyName: string }) {
  const [expanded, setExpanded] = useState(false);
  if (expanded) {
    return (
      <div className={styles.scrim} onClick={(event) => { if (event.target === event.currentTarget) setExpanded(false); }}>
        <section className={styles.browserExpanded} role="dialog" aria-modal="true" aria-label={`${allyName}'s browser`}>
          <header className={styles.browserHead}>
            <span><strong>{allyName}&apos;s browser</strong><small><span className={styles.live} /> Live</small></span>
            <button type="button" className={styles.iconButton} aria-label="Minimize" onClick={() => setExpanded(false)}>–</button>
          </header>
          <div className={styles.browserFrame}>
            <iframe src={liveUrl} title={`${allyName}'s browser`} sandbox="allow-scripts allow-same-origin" tabIndex={-1} />
            <div className={styles.watchOnly} aria-hidden="true" />
          </div>
          <p className={styles.caption}>You can watch. Only {allyName} can use this browser.</p>
        </section>
      </div>
    );
  }
  return (
    <button type="button" className={styles.pip} onClick={() => setExpanded(true)} aria-label={`Watch ${allyName}'s browser`}>
      <span className={styles.pipFrame}>
        <iframe src={liveUrl} title={`${allyName}'s browser preview`} sandbox="allow-scripts allow-same-origin" tabIndex={-1} />
      </span>
      <span className={styles.pipLabel}><span className={styles.live} /> Browsing</span>
    </button>
  );
}

function SafeInputSheet({ workspaceId, request, allyName, onDone }: { workspaceId: string; request: SafeInputRequest; allyName: string; onDone: () => void }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const [state, setState] = useState<"editing" | "explaining" | "saving" | "saved">("editing");
  const [problem, setProblem] = useState<string | null>(null);
  const name = request.name || request.website;

  useEffect(() => {
    if (state !== "saved") return;
    const timer = window.setTimeout(onDone, 900);
    return () => window.clearTimeout(timer);
  }, [state, onDone]);

  const decide = async (decision: "allow" | "deny", form?: FormData) => {
    setState(decision === "allow" ? "saving" : state);
    setProblem(null);
    try {
      await session.runCloudOperation(
        (signal: Signal) => session.client.resolveSafeInputRequest(workspaceId, request.id, decision, form ? {
          name: String(form.get("name") || ""),
          website: String(form.get("website") || ""),
          username: String(form.get("username") || ""),
          password: String(form.get("password") || ""),
        } : {}, signal),
        { csrf: true, retryTransient: false },
      );
      void queryClient.invalidateQueries({ queryKey: safeInputsQueryKey(workspaceId) });
      if (decision === "allow") setState("saved");
      else onDone();
    } catch {
      setState("editing");
      setProblem("That didn't save. Check the website and try again.");
    }
  };

  return (
    <div className={`${styles.scrim} ${styles.safeMode}`}>
      <section className={styles.sheet} role="dialog" aria-modal="true" aria-labelledby="safe-input-sheet-title">
        {state === "saved" ? (
          <div className={styles.saved} role="status">
            <span className={styles.savedRing} aria-hidden="true">✓</span>
            <strong>Saved</strong>
            <small>{allyName} can sign in to {request.website} now.</small>
          </div>
        ) : state === "explaining" ? (
          <>
            <SheetHead onHelp={() => setState("editing")} onClose={() => void decide("deny")} />
            <h2 id="safe-input-sheet-title">What&apos;s a Safe input?</h2>
            <p className={styles.lead}>A login you give {allyName} without putting it in chat.</p>
            <ul className={styles.points}>
              <li>You type it here, never in chat.</li>
              <li>It&apos;s encrypted and saved to your account.</li>
              <li>{allyName} can sign in to {request.website} with it, but can&apos;t read it.</li>
              <li>Change or remove it any time in Settings.</li>
            </ul>
            <button type="button" className={styles.primary} onClick={() => setState("editing")}>Got it</button>
          </>
        ) : (
          <form onSubmit={(event) => { event.preventDefault(); void decide("allow", new FormData(event.currentTarget)); }}>
            <SheetHead onHelp={() => setState("explaining")} onClose={() => void decide("deny")} disabled={state === "saving"} />
            <h2 id="safe-input-sheet-title">Sign in to {name}</h2>
            <p className={styles.lead}>{allyName} needs your {name} login. {allyName} can use it but never sees it.</p>
            <fieldset className={styles.fields} disabled={state === "saving"}>
              <SafeInputFields name={name} website={request.website} />
            </fieldset>
            {problem ? <p className={styles.problem} role="alert">{problem}</p> : null}
            <button type="submit" className={styles.primary} disabled={state === "saving"}>{state === "saving" ? "Saving…" : "Save"}</button>
          </form>
        )}
      </section>
    </div>
  );
}

function SheetHead({ onHelp, onClose, disabled = false }: { onHelp: () => void; onClose: () => void; disabled?: boolean }) {
  return (
    <div className={styles.sheetHead}>
      <span className={styles.badge}>Safe input <button type="button" className={styles.help} aria-label="What's a Safe input?" onClick={onHelp} disabled={disabled}>?</button></span>
      <button type="button" className={styles.iconButton} aria-label="Not now" onClick={onClose} disabled={disabled}>×</button>
    </div>
  );
}

function AccessRequest({ workspaceId, request, allyName, onDone }: { workspaceId: string; request: SafeInputRequest; allyName: string; onDone: () => void }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const decide = async (decision: "allow" | "deny") => {
    setBusy(true);
    setProblem(null);
    try {
      await session.runCloudOperation(
        (signal: Signal) => session.client.resolveSafeInputRequest(workspaceId, request.id, decision, {}, signal),
        { csrf: true, retryTransient: false },
      );
      void queryClient.invalidateQueries({ queryKey: safeInputsQueryKey(workspaceId) });
      onDone();
    } catch {
      setProblem("That didn't go through. Try again.");
      setBusy(false);
    }
  };
  return (
    <div className={styles.scrim}>
      <section className={`${styles.sheet} ${styles.light}`} role="dialog" aria-modal="true" aria-labelledby="safe-input-access-title">
        <h2 id="safe-input-access-title">Let {allyName} use your {request.name} login?</h2>
        <p className={styles.lead}>{allyName} can sign in to {request.website} with it, but can&apos;t see it. You can remove access in Settings.</p>
        <div className={styles.siteCard}>
          <span className={styles.siteMark} aria-hidden="true">{request.name.charAt(0).toLowerCase()}</span>
          <span><strong>{request.name}</strong><small>{request.website}</small></span>
        </div>
        {problem ? <p className={styles.problem} role="alert">{problem}</p> : null}
        <div className={styles.actions}>
          <button type="button" className={styles.secondary} disabled={busy} onClick={() => void decide("deny")}>Don&apos;t allow</button>
          <button type="button" className={styles.primary} disabled={busy} onClick={() => void decide("allow")}>Allow</button>
        </div>
      </section>
    </div>
  );
}
