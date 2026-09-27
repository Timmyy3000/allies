"use client";

import type { AllyViewModel, SafeInput } from "@allies/cloud-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { alliesQueryOptions } from "../../lib/allies/queries";
import { useSession } from "../../lib/session/session-context";

import styles from "./ally-settings-dialog.module.css";

export function safeInputsQueryKey(workspaceId: string) {
  return ["safe-inputs", workspaceId] as const;
}

type Signal = AbortSignal | undefined;

function useSafeInputs(workspaceId: string) {
  const session = useSession();
  return useQuery({
    queryKey: safeInputsQueryKey(workspaceId),
    queryFn: ({ signal }) => session.runCloudOperation(
      (operationSignal: Signal) => session.client.listSafeInputs(workspaceId, operationSignal),
      { signal },
    ),
    retry: false,
  });
}

/** Ally profile section (DSN-011 20–21): toggle which saved logins this Ally can use. */
export function AllySafeInputs({ workspaceId, ally }: { workspaceId: string; ally: AllyViewModel }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const query = useSafeInputs(workspaceId);
  const [pending, setPending] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [signedOut, setSignedOut] = useState<SafeInput | null>(null);
  const [managing, setManaging] = useState<string | null>(null);

  const setAccess = async (item: SafeInput, enabled: boolean) => {
    setPending(item.id);
    setProblem(null);
    try {
      await session.runCloudOperation(
        (signal: Signal) => session.client.setSafeInputAccess(workspaceId, item.id, ally.id, enabled, signal),
        { csrf: true, retryTransient: false },
      );
      setSignedOut(enabled ? null : item);
    } catch {
      setProblem("We couldn't change access. Try again.");
    } finally {
      setPending(null);
      void queryClient.invalidateQueries({ queryKey: safeInputsQueryKey(workspaceId) });
    }
  };

  const items = query.data ?? [];
  if (query.isError || (!query.isPending && items.length === 0)) return null;
  const granted = items.filter((item) => item.allyIds.includes(ally.id)).length;
  const managed = items.find((item) => item.id === managing);

  return (
    <section className={styles.profileSection} aria-labelledby="ally-safe-inputs-title">
      <div className={styles.profileSectionHead}>
        <h4 id="ally-safe-inputs-title">Safe inputs</h4>
        {items.length ? <span className={styles.labelCount}>{granted} of {items.length}</span> : null}
      </div>
      {query.isPending ? <div className={styles.routineSkeleton} /> : (
        <div className={styles.profileList}>
          {items.map((item) => (
            <div key={item.id} className={styles.accessRow}>
              <SiteMark name={item.name} />
              <button type="button" className={styles.accessCopy} onClick={() => setManaging(item.id)}>
                <strong>{item.name}</strong>
                <small>{item.website}</small>
              </button>
              <input
                type="checkbox"
                role="switch"
                className={styles.accessSwitch}
                aria-label={`${ally.name} can use ${item.name}`}
                checked={item.allyIds.includes(ally.id)}
                disabled={pending !== null}
                onChange={(event) => void setAccess(item, event.target.checked)}
              />
            </div>
          ))}
        </div>
      )}
      <p className={styles.settingsHelp}>
        {ally.name} can sign in with these, but never sees them. Turning one off signs {ally.name} out of that site.
      </p>
      {problem ? <p className={styles.profileInlineError} role="alert">{problem}</p> : null}
      {signedOut ? (
        <p className={styles.accessNotice} role="status">
          {ally.name} was signed out of {signedOut.website}{" "}
          <button type="button" onClick={() => void setAccess(signedOut, true)}>Undo</button>
        </p>
      ) : null}
      {managed ? (
        <SafeInputDetail workspaceId={workspaceId} item={managed} onClose={() => setManaging(null)} />
      ) : null}
    </section>
  );
}

/** Safe input detail (DSN-011 17–19): Ally access, update login, delete. */
function SafeInputDetail({ workspaceId, item, onClose }: { workspaceId: string; item: SafeInput; onClose: () => void }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const allies = useQuery(alliesQueryOptions(session.client, session.runCloudOperation, workspaceId)).data ?? [];
  const [view, setView] = useState<"detail" | "update" | "delete">("detail");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: safeInputsQueryKey(workspaceId) });
  const withAccess = allies.filter((ally) => item.allyIds.includes(ally.id));

  const run = async (operation: (signal: Signal) => Promise<void>, done?: () => void) => {
    setBusy(true);
    setProblem(null);
    try {
      await session.runCloudOperation(operation, { csrf: true, retryTransient: false });
      await refresh();
      done?.();
    } catch {
      setProblem("That didn't work. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const update = (form: FormData) => void run(
    (signal) => session.client.updateSafeInput(workspaceId, item.id, {
      website: String(form.get("website") || "") || undefined,
      username: String(form.get("username") || "") || undefined,
      password: String(form.get("password") || "") || undefined,
    }, signal),
    () => setView("detail"),
  );

  return (
    <div className={styles.subsheetScrim} onClick={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <section className={styles.subsheet} role="dialog" aria-modal="true" aria-labelledby="safe-input-title">
        <div className={styles.subsheetHead}>
          <h3 id="safe-input-title">{view === "update" ? `Update ${item.name} login` : view === "delete" ? `Delete your ${item.name} login?` : item.name}</h3>
          <button type="button" className={styles.subsheetClose} aria-label="Close" onClick={onClose} disabled={busy}>×</button>
        </div>
        {view === "detail" ? (
          <>
            <p className={styles.settingsHelp}>{item.website} · Updated {new Date(item.updatedAt).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</p>
            <div className={styles.profileSectionHead}>
              <h4>Allies that can use it</h4>
              <span className={styles.labelCount}>{withAccess.length} of {allies.length}</span>
            </div>
            <div className={styles.profileList}>
              {allies.map((ally) => (
                <label key={ally.id} className={styles.accessRow}>
                  <span className={styles.accessCopy}><strong>{ally.name}</strong><small>{ally.job}</small></span>
                  <input
                    type="checkbox"
                    role="switch"
                    className={styles.accessSwitch}
                    aria-label={`${ally.name} can use ${item.name}`}
                    checked={item.allyIds.includes(ally.id)}
                    disabled={busy}
                    onChange={(event) => void run((signal) => session.client.setSafeInputAccess(workspaceId, item.id, ally.id, event.target.checked, signal))}
                  />
                </label>
              ))}
            </div>
            <p className={styles.settingsHelp}>Email and password are hidden, even from you.</p>
            <button type="button" className={styles.subsheetPrimary} onClick={() => setView("update")}>Update login</button>
            <button type="button" className={styles.profileDeleteRow} onClick={() => setView("delete")}>Delete Safe input</button>
          </>
        ) : view === "update" ? (
          <form onSubmit={(event) => { event.preventDefault(); update(new FormData(event.currentTarget)); }}>
            <p className={styles.settingsHelp}>This replaces what&apos;s saved. {withAccess.map((ally) => ally.name).join(" and ") || "Allies with access"} keep access.</p>
            <SafeInputFields website={item.website} />
            <button type="submit" className={styles.subsheetPrimary} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
          </form>
        ) : (
          <>
            <p className={styles.deleteWarning}>
              {withAccess.length ? `${withAccess.map((ally) => ally.name).join(" and ")} lose access and are signed out of ${item.website}.` : `No Ally will be able to sign in to ${item.website} with it.`}
            </p>
            <button type="button" className={styles.deleteButton} disabled={busy} onClick={() => void run((signal) => session.client.deleteSafeInput(workspaceId, item.id, signal), onClose)}>
              {busy ? "Deleting…" : "Delete"}
            </button>
            <button type="button" className={styles.subsheetPrimary} onClick={() => setView("detail")} disabled={busy}>Cancel</button>
          </>
        )}
        {problem ? <p className={styles.profileInlineError} role="alert">{problem}</p> : null}
      </section>
    </div>
  );
}

export function SafeInputFields({ name, website }: { name?: string; website: string }) {
  return (
    <>
      {name !== undefined ? (
        <label className={styles.settingsField}>Name<input className={styles.settingsInput} name="name" defaultValue={name} maxLength={80} required /></label>
      ) : null}
      <label className={styles.settingsField}>Website<input className={styles.settingsInput} name="website" defaultValue={website} maxLength={253} required /></label>
      <label className={styles.settingsField}>Email or username<input className={styles.settingsInput} name="username" autoComplete="off" maxLength={512} placeholder="name@example.com" required /></label>
      <label className={styles.settingsField}>Password<input className={styles.settingsInput} name="password" type="password" autoComplete="new-password" maxLength={512} placeholder={name !== undefined ? "Password" : "New password"} required /></label>
    </>
  );
}

function SiteMark({ name }: { name: string }) {
  return <span className={styles.accessLogo} aria-hidden="true" style={{ display: "grid", placeItems: "center", fontWeight: 600 }}>{name.charAt(0).toLowerCase()}</span>;
}
