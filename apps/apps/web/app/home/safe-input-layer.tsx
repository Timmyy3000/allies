"use client";

import type { SafeInputRequest } from "@allies/cloud-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";

import { AllyAvatar, type AllyShape } from "../../components/ally-avatar";

import { useSession } from "../../lib/session/session-context";
import { SafeInputFields, safeInputsQueryKey } from "./ally-safe-inputs";

import styles from "./safe-input-layer.module.css";

type Signal = AbortSignal | undefined;
// The Ally's tool waits up to four minutes for an answer, so a few seconds of lag is fine.
const POLL_MS = 3_000;
const ERROR_POLL_MS = 15_000;

/** In-chat Safe input requests and the Ally's watch-only browser (DSN-011 1–8, 13). */
export function SafeInputLayer({ workspaceId, allyId, allyName, accent, shape = "ghosty" }: { workspaceId: string; allyId: string; allyName: string; accent: string; shape?: AllyShape }) {
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
      {browser.data && !request ? <BrowserWindow liveUrl={browser.data.liveUrl} allyName={allyName} avatar={(size) => <AllyAvatar shape={shape} color={accent} size={size} />} /> : null}
      {request?.kind === "new" ? (
        <SafeInputSheet key={request.id} workspaceId={workspaceId} request={request} allyName={allyName} avatar={<AllyAvatar shape={shape} color={accent} size={52} />} onDone={done} />
      ) : request?.kind === "access" ? (
        <AccessRequest key={request.id} workspaceId={workspaceId} request={request} allyName={allyName} onDone={done} />
      ) : null}
    </div>
  );
}

// Where the floating browser sits, measured from the viewport's bottom-right corner.
type Offset = { right: number; bottom: number };
const DRAG_SLOP = 4;
const EDGE = 8;

function BrowserWindow({ liveUrl, allyName, avatar }: { liveUrl: string; allyName: string; avatar: (size: number) => ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  const [offset, setOffset] = useState<Offset>({ right: 16, bottom: 96 });
  const drag = useRef<{ x: number; y: number; start: Offset; moved: boolean } | null>(null);

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, start: offset, moved: false };
  };
  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    const current = drag.current;
    if (!current) return;
    const dx = event.clientX - current.x;
    const dy = event.clientY - current.y;
    if (!current.moved && Math.hypot(dx, dy) < DRAG_SLOP) return;
    current.moved = true;
    const box = event.currentTarget.getBoundingClientRect();
    const clamp = (value: number, max: number) => Math.min(Math.max(EDGE, value), Math.max(EDGE, max));
    setOffset({
      right: clamp(current.start.right - dx, window.innerWidth - box.width - EDGE),
      bottom: clamp(current.start.bottom - dy, window.innerHeight - box.height - EDGE),
    });
  };
  // A drag leaves the window where it was dropped; a tap opens it.
  const onClick = () => {
    const moved = drag.current?.moved;
    drag.current = null;
    if (!moved) setExpanded(true);
  };

  if (expanded) {
    return (
      <div className={styles.scrim} onClick={(event) => { if (event.target === event.currentTarget) setExpanded(false); }}>
        <section className={styles.browserExpanded} role="dialog" aria-modal="true" aria-label={`${allyName}'s browser`}>
          <header className={styles.browserHead}>
            {avatar(36)}
            <span className={styles.browserWho}>
              <strong>{allyName}&apos;s browser</strong>
              <small><span className={styles.live} /> Live</small>
            </span>
            <button type="button" className={styles.minimize} aria-label="Minimize" onClick={() => setExpanded(false)}>
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
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
    <button
      type="button"
      className={styles.pip}
      style={{ right: offset.right, bottom: offset.bottom }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerCancel={() => { drag.current = null; }}
      onClick={onClick}
      aria-label={`Watch ${allyName}'s browser`}
    >
      <span className={styles.pipBar}>
        {avatar(16)}
        <span className={styles.pipTitle}><span className={styles.live} /> Browsing</span>
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </span>
      <span className={styles.pipFrame}>
        <iframe src={liveUrl} title={`${allyName}'s browser preview`} sandbox="allow-scripts allow-same-origin" tabIndex={-1} />
      </span>
    </button>
  );
}

function SafeInputSheet({ workspaceId, request, allyName, avatar, onDone }: { workspaceId: string; request: SafeInputRequest; allyName: string; avatar: ReactNode; onDone: () => void }) {
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
            <SheetHead avatar={avatar} onClose={() => void decide("deny")} />
            <Chip onHelp={() => setState("editing")} />
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
            <SheetHead avatar={avatar} onClose={() => void decide("deny")} disabled={state === "saving"} />
            <Chip onHelp={() => setState("explaining")} disabled={state === "saving"} />
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

function SheetHead({ avatar, onClose, disabled = false }: { avatar: ReactNode; onClose: () => void; disabled?: boolean }) {
  return (
    <div className={styles.sheetHead}>
      <span className={styles.avatarRing}>{avatar}</span>
      <button type="button" className={styles.iconButton} aria-label="Not now" onClick={onClose} disabled={disabled}>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
      </button>
    </div>
  );
}

function Chip({ onHelp, disabled = false }: { onHelp: () => void; disabled?: boolean }) {
  return (
    <div className={styles.chipRow}>
      <span className={styles.badge}>
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2" fill="currentColor" /><path d="M8 11V8a4 4 0 0 1 8 0v3" fill="none" stroke="currentColor" strokeWidth="2" /></svg>
        Safe input
      </span>
      <button type="button" className={styles.help} aria-label="What's a Safe input?" onClick={onHelp} disabled={disabled}>?</button>
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
