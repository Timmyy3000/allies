"use client";

import Link from "next/link";
import type { AllyDeletionViewModel, AllyViewModel } from "@allies/cloud-client";
import { isCloudError } from "@allies/cloud-client";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { motion, useReducedMotion } from "motion/react";

import { useSession } from "../../lib/session/session-context";
import { alliesQueryKey } from "../../lib/allies/query-keys";

import { BottomSheet } from "./conversation-frame-primitives";
import frameStyles from "./conversation-frame.module.css";
import styles from "./ally-settings-dialog.module.css";

type SettingsDraft = {
  label: string;
  showLabel: boolean;
};

type DeletionState = "active" | "pending" | "repair_required";
type DeletionView = "settings" | "confirming" | "submitting" | "pending" | "repair_required";

export const ALLY_DELETION_INITIAL_POLL_MS = 2_000;
export const ALLY_DELETION_MAX_POLL_MS = 30_000;
export const ALLY_DELETION_MAX_POLL_DURATION_MS = 10 * 60 * 1_000;

function normalizeLabel(value: string): string {
  return value.trim().replace(/\s+/gu, " ");
}

function settingsFor(ally: AllyViewModel): SettingsDraft & { settingsRevision: number } {
  const label = normalizeLabel(ally.label ?? "");
  return {
    label,
    showLabel: Boolean(ally.showLabel && label),
    settingsRevision: ally.settingsRevision ?? 0,
  };
}

function sameDraft(left: SettingsDraft, right: SettingsDraft): boolean {
  return left.label === right.label && left.showLabel === right.showLabel;
}

function labelError(label: string): string | null {
  if (/[\p{Cc}\p{Cf}]/u.test(label)) return "Use a single-line label.";
  const normalized = normalizeLabel(label);
  if (!normalized) return null;
  return [2, 3].includes(normalized.split(" ").length) ? null : "Use two or three words.";
}

function saveError(error: unknown): string {
  if (isCloudError(error)) {
    if (error.kind === "conflict" || error.status === 409) {
      return "This Ally changed elsewhere. We refreshed its settings. Review your draft and save again.";
    }
    if (error.kind === "validation" || error.status === 422 || error.kind === "bad-request") {
      return "Check the label and try again.";
    }
    if (error.kind === "unauthorized" || error.status === 401) {
      return "Your session has ended. Sign in again to continue.";
    }
    if (error.kind === "forbidden" || error.kind === "security" || error.status === 403) {
      return "You don't have permission to change this Ally.";
    }
  }
  return "We couldn't save these settings. Your draft is still here. Try again.";
}

function deletionError(error: unknown): string {
  if (isCloudError(error)) {
    if (error.kind === "conflict" || error.status === 409) {
      return "This deletion request conflicted with a change. Review the confirmation phrase and try again.";
    }
    if (error.kind === "validation" || error.status === 422) {
      return "Enter the exact confirmation phrase to continue.";
    }
    if (error.kind === "unauthorized" || error.status === 401) {
      return "Your session has ended. Sign in again to continue.";
    }
    if (error.kind === "forbidden" || error.kind === "security" || error.status === 403) {
      return "You don't have permission to delete this Ally.";
    }
    if (error.status === 404) {
      return "We couldn't find this Ally. Refresh the page and try again.";
    }
  }
  return "We couldn't start deletion. Your Ally is still here. Try again.";
}

function deletionStatusMessage(state: DeletionState): string {
  return state === "repair_required"
    ? "Deletion needs attention. We couldn't finish removing this Ally."
    : "Deletion is still in progress. This Ally stays unavailable until cleanup is confirmed.";
}

function isUnknownDeletionOutcome(error: unknown): boolean {
  if (!isCloudError(error)) return true;
  return error.kind === "network" || error.kind === "timeout" || error.kind === "server";
}

function isDeletionConflict(error: unknown): boolean {
  return isCloudError(error) && (error.kind === "conflict" || error.status === 409);
}

function isDeletionNotFound(error: unknown): boolean {
  return isCloudError(error) && (error.kind === "not-found" || error.status === 404);
}

function deletionConflictReconciliationError(error: unknown): string {
  if (isDeletionNotFound(error)) {
    return "This Ally changed before deletion could start. Review the confirmation phrase and try again.";
  }
  if (isUnknownDeletionOutcome(error)) {
    return "We couldn't verify whether another deletion is in progress. Check its status again when you're online.";
  }
  return "This deletion request conflicted with a change. Your Ally is still here. Review the confirmation phrase and try again.";
}

export function AllySettingsDialog({
  ally,
  workspaceId,
  onClose,
  onSaved,
  onDeletionStatus,
  onRefreshDeletion,
}: {
  ally: AllyViewModel;
  workspaceId: string;
  onClose: () => void;
  onSaved: (ally: AllyViewModel) => void;
  onDeletionStatus: (status: AllyDeletionViewModel) => void;
  onRefreshDeletion: () => Promise<AllyDeletionViewModel>;
}) {
  const reducedMotion = useReducedMotion();
  const session = useSession();
  const queryClient = useQueryClient();
  const initial = settingsFor(ally);
  const [draft, setDraft] = useState<SettingsDraft>(initial);
  const dirtyRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [deletionView, setDeletionView] = useState<DeletionView>(
    ally.deletionState === "pending" || ally.deletionState === "repair_required"
      ? ally.deletionState
      : "settings",
  );
  const [deletionConfirmation, setDeletionConfirmation] = useState("");
  const [deletionErrorMessage, setDeletionErrorMessage] = useState<string | null>(null);
  const [deletionStatusCheckAvailable, setDeletionStatusCheckAvailable] = useState(false);
  const [refreshingDeletion, setRefreshingDeletion] = useState(false);
  const deletionConfirmationRef = useRef<HTMLInputElement | null>(null);
  const deleteTriggerRef = useRef<HTMLButtonElement | null>(null);
  const mountedRef = useRef(true);
  const remoteRevisionRef = useRef(initial.settingsRevision);
  const remoteDraftRef = useRef<SettingsDraft>(initial);
  const remoteKeyRef = useRef(`${ally.id}:${initial.label}:${initial.showLabel}:${initial.settingsRevision}`);
  const saveControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const next = settingsFor(ally);
    const nextKey = `${ally.id}:${next.label}:${next.showLabel}:${next.settingsRevision}`;
    if (remoteKeyRef.current === nextKey) return;
    remoteKeyRef.current = nextKey;
    if (!dirtyRef.current) {
      remoteRevisionRef.current = next.settingsRevision;
      remoteDraftRef.current = next;
      setDraft(next);
      dirtyRef.current = false;
    }
  }, [ally]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      saveControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (deletionView !== "confirming") return;
    deletionConfirmationRef.current?.focus();
  }, [deletionView]);

  const updateDraft = (next: SettingsDraft) => {
    const normalized = { ...next, showLabel: Boolean(next.showLabel && normalizeLabel(next.label)) };
    const nextDirty = !sameDraft(normalized, remoteDraftRef.current);
    dirtyRef.current = nextDirty;
    setDraft(normalized);
    setError(null);
    setStatus(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (savingRef.current) return;
    const label = normalizeLabel(draft.label);
    const validationError = labelError(draft.label);
    if (validationError) {
      setError(validationError);
      setStatus(null);
      return;
    }
    if (!label && draft.showLabel) {
      setError("Add a label before showing it.");
      return;
    }

    savingRef.current = true;
    setSaving(true);
    setError(null);
    setStatus("Saving settings…");
    const controller = new AbortController();
    saveControllerRef.current = controller;
    const allyQueryKey = alliesQueryKey(workspaceId);
    try {
      await queryClient.cancelQueries({ queryKey: allyQueryKey, exact: true });
      const updated = await session.runCloudOperation(
        (signal) => session.client.updateAllySettings(workspaceId, ally.id, {
          label,
          showLabel: Boolean(draft.showLabel && label),
          settingsRevision: remoteRevisionRef.current,
        }, signal),
        { csrf: true, retryTransient: false, signal: controller.signal },
      );
      await queryClient.cancelQueries({ queryKey: allyQueryKey, exact: true });
      const next = settingsFor(updated);
      remoteRevisionRef.current = next.settingsRevision;
      remoteDraftRef.current = next;
      remoteKeyRef.current = `${updated.id}:${next.label}:${next.showLabel}:${next.settingsRevision}`;
      dirtyRef.current = false;
      setDraft(next);
      setStatus("Settings saved.");
      onSaved(updated);
    } catch (caught) {
      const conflict = isCloudError(caught) && (caught.kind === "conflict" || caught.status === 409);
      let conflictRefreshed = false;
      if (conflict) {
        try {
          await queryClient.refetchQueries(
            { queryKey: alliesQueryKey(workspaceId), exact: true, type: "active" },
            { throwOnError: true },
          );
          const current = queryClient.getQueryData<AllyViewModel[]>(alliesQueryKey(workspaceId))
            ?.find((candidate) => candidate.id === ally.id);
          if (current) {
            const next = settingsFor(current);
            remoteRevisionRef.current = next.settingsRevision;
            remoteDraftRef.current = next;
            remoteKeyRef.current = `${current.id}:${next.label}:${next.showLabel}:${next.settingsRevision}`;
            conflictRefreshed = true;
          }
        } catch {
          // Keep the draft and the current revision when reconciliation is unavailable.
        }
      }
      setStatus(null);
      setError(conflict && !conflictRefreshed
        ? "This Ally changed elsewhere. We couldn't refresh its current settings. Your draft is still here; try again when you're ready."
        : saveError(caught));
    } finally {
      if (saveControllerRef.current === controller) saveControllerRef.current = null;
      savingRef.current = false;
      setSaving(false);
    }
  };

  const confirmationPhrase = `${ally.name} - deletes me`;
  const currentDeletionView: DeletionView = ally.deletionState === "pending" || ally.deletionState === "repair_required"
    ? ally.deletionState
    : deletionView;
  const acceptedDeletion = currentDeletionView === "submitting"
    || currentDeletionView === "pending"
    || currentDeletionView === "repair_required";

  const applyDeletionStatus = (next: AllyDeletionViewModel, notifyParent = true) => {
    if (next.allyId !== ally.id) {
      setDeletionErrorMessage("We couldn't verify this deletion belongs to the selected Ally.");
      return;
    }
    if (notifyParent) onDeletionStatus(next);
    if (next.state === "complete") return;
    setDeletionView(next.state);
    setDeletionConfirmation("");
    setDeletionErrorMessage(next.state === "repair_required" ? deletionStatusMessage(next.state) : null);
  };

  const handleDelete = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (currentDeletionView === "submitting" || acceptedDeletion) return;
    if (deletionConfirmation !== confirmationPhrase) {
      setDeletionErrorMessage("Enter the exact confirmation phrase to continue.");
      return;
    }

    setDeletionView("submitting");
    setDeletionErrorMessage(null);
    try {
      const response = await session.runCloudOperation(
        (signal) => session.client.requestAllyDeletion(workspaceId, ally.id, { confirmation: deletionConfirmation }, signal),
        { csrf: true, retryTransient: false },
      );
      onDeletionStatus(response);
      if (!mountedRef.current) return;
      applyDeletionStatus(response, false);
    } catch (caught) {
      if (isDeletionConflict(caught)) {
        try {
          const response = await onRefreshDeletion();
          if (!mountedRef.current) return;
          setDeletionStatusCheckAvailable(false);
          applyDeletionStatus(response, false);
          if (response.state === "pending") {
            setDeletionErrorMessage("This Ally is already being deleted. We'll keep checking its status.");
          }
        } catch (statusError) {
          if (!mountedRef.current) return;
          setDeletionView("confirming");
          setDeletionConfirmation("");
          setDeletionStatusCheckAvailable(isUnknownDeletionOutcome(statusError));
          setDeletionErrorMessage(deletionConflictReconciliationError(statusError));
        }
      } else if (isUnknownDeletionOutcome(caught)) {
        const pending: AllyDeletionViewModel = {
          allyId: ally.id,
          state: "pending",
          retryable: true,
          safeErrorCode: "request_unknown",
        };
        onDeletionStatus(pending);
        if (!mountedRef.current) return;
        setDeletionStatusCheckAvailable(false);
        applyDeletionStatus(pending, false);
        setDeletionErrorMessage("We couldn't confirm the request. We'll keep checking its status.");
      } else {
        if (!mountedRef.current) return;
        setDeletionView("confirming");
        setDeletionStatusCheckAvailable(false);
        setDeletionErrorMessage(deletionError(caught));
      }
    }
  };

  const refreshDeletion = async () => {
    if (refreshingDeletion) return;
    setRefreshingDeletion(true);
    setDeletionErrorMessage(null);
    try {
      const response = await onRefreshDeletion();
      if (mountedRef.current) applyDeletionStatus(response);
    } catch {
      if (mountedRef.current) setDeletionErrorMessage("We couldn't check deletion yet. Try again when you're online.");
    } finally {
      if (mountedRef.current) setRefreshingDeletion(false);
    }
  };

  const cancelDeletionConfirmation = () => {
    setDeletionView("settings");
    setDeletionConfirmation("");
    setDeletionErrorMessage(null);
    setDeletionStatusCheckAvailable(false);
    window.requestAnimationFrame(() => deleteTriggerRef.current?.focus());
  };

  const deletionState = currentDeletionView === "repair_required"
    ? "repair_required"
    : currentDeletionView === "pending" || currentDeletionView === "submitting"
      ? "pending"
      : ally.deletionState ?? "active";

  return (
    <BottomSheet
      modal
      title={`${ally.name} settings`}
      onClose={onClose}
      labelledBy="ally-settings-title"
      className={styles.settingsOverlay}
      closeDisabled={saving || currentDeletionView === "submitting"}
    >
      <form className={styles.settingsContent} onSubmit={currentDeletionView === "confirming" ? handleDelete : handleSubmit} noValidate>
        <motion.div key={currentDeletionView} className={styles.settingsView} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reducedMotion ? 0 : .16 }}>
        {currentDeletionView === "settings" ? (
          <>
            <Link href={`/allies/${encodeURIComponent(ally.id)}/settings`}>View ally details</Link>
            <div className={styles.settingsField}>
              <label htmlFor="ally-label">Label</label>
              <input
                id="ally-label"
                className={styles.settingsInput}
                type="text"
                value={draft.label}
                disabled={saving}
                maxLength={80}
                autoComplete="off"
                aria-invalid={Boolean(error && !status)}
                aria-describedby={error ? "ally-label-help ally-settings-error" : "ally-label-help"}
                onChange={(event) => updateDraft({ ...draft, label: event.target.value })}
              />
              <span id="ally-label-help" className={styles.settingsHelp}>Use two or three words, up to 80 characters.</span>
            </div>
            <label className={styles.settingsToggle}>
              <input
                type="checkbox"
                checked={draft.showLabel}
                disabled={saving || !normalizeLabel(draft.label)}
                onChange={(event) => updateDraft({ ...draft, showLabel: event.target.checked })}
                aria-describedby="ally-show-label-help"
              />
              <span>
                <strong>Show label</strong>
                <small id="ally-show-label-help">Display this label beneath the Ally&apos;s name in your roster.</small>
              </span>
            </label>
            <section className={styles.deleteSection} aria-labelledby="ally-delete-title">
              <h3 id="ally-delete-title">Delete Ally</h3>
              <p>Permanently remove this Ally and its conversations, files, and memory.</p>
              <button
                ref={deleteTriggerRef}
                type="button"
                className={styles.deleteButton}
                onClick={() => {
                  setDeletionView("confirming");
                  setDeletionStatusCheckAvailable(false);
                  setDeletionErrorMessage(null);
                }}
                disabled={saving}
              >
                Delete Ally
              </button>
            </section>
            <div className={styles.settingsMessages} aria-live="polite">
              {error ? <p id="ally-settings-error" role="alert">{error}</p> : null}
              {status ? <p role="status">{status}</p> : null}
            </div>
            <div className={frameStyles.frameSheetActions}>
              <button type="button" className={frameStyles.frameNeutralAction} onClick={onClose} disabled={saving}>Cancel</button>
              <button type="submit" className={frameStyles.frameAccentAction} disabled={saving}>
                <motion.span key={saving ? "saving" : status ? "saved" : "save"} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reducedMotion ? 0 : .12 }}>{saving ? "Saving…" : status ? "Saved ✓" : "Save"}</motion.span>
              </button>
            </div>
          </>
        ) : currentDeletionView === "confirming" ? (
          <>
            <section className={styles.deleteWarning} aria-labelledby="ally-delete-warning-title">
              <h3 id="ally-delete-warning-title">Delete {ally.name}?</h3>
              <p>This permanently removes {ally.name}&apos;s conversations, files, memory, and associated work. The deletion continues after you close this window.</p>
              <label className={styles.settingsField} htmlFor="ally-delete-confirmation">
                <span>Type the exact phrase to confirm</span>
                <input
                  ref={deletionConfirmationRef}
                  id="ally-delete-confirmation"
                  className={styles.settingsInput}
                  type="text"
                  value={deletionConfirmation}
                  autoComplete="off"
                  spellCheck={false}
                  aria-describedby="ally-delete-phrase-help ally-deletion-error"
                  aria-invalid={Boolean(deletionErrorMessage)}
                  onChange={(event) => { setDeletionConfirmation(event.target.value); setDeletionErrorMessage(null); }}
                />
                <span id="ally-delete-phrase-help" className={styles.settingsHelp}>Enter: <code>{confirmationPhrase}</code></span>
              </label>
            </section>
            {deletionErrorMessage ? <p id="ally-deletion-error" className={styles.deletionError} role="alert">{deletionErrorMessage}</p> : null}
            <div className={frameStyles.frameSheetActions}>
              <button type="button" className={frameStyles.frameNeutralAction} onClick={cancelDeletionConfirmation}>Cancel</button>
              {deletionStatusCheckAvailable ? (
                <button type="button" className={frameStyles.frameNeutralAction} onClick={() => void refreshDeletion()} disabled={refreshingDeletion}>
                  {refreshingDeletion ? "Checking…" : "Check status"}
                </button>
              ) : null}
              <button type="submit" className={styles.deleteButton} disabled={deletionConfirmation !== confirmationPhrase}>
                Delete Ally
              </button>
            </div>
          </>
        ) : (
          <>
            <section className={styles.deleteStatus} aria-labelledby="ally-delete-status-title" aria-live="polite">
              <h3 id="ally-delete-status-title">{deletionState === "repair_required" ? "Deletion needs attention" : `Deleting ${ally.name}`}</h3>
              <p>{deletionStatusMessage(deletionState)}</p>
              {currentDeletionView === "submitting" ? <p role="status">Starting deletion…</p> : null}
            </section>
            {deletionErrorMessage ? <p className={styles.deletionError} role="alert">{deletionErrorMessage}</p> : null}
            <div className={frameStyles.frameSheetActions}>
              <button type="button" className={frameStyles.frameNeutralAction} onClick={onClose} disabled={currentDeletionView === "submitting"}>Close</button>
              <button type="button" className={frameStyles.frameAccentAction} onClick={() => void refreshDeletion()} disabled={refreshingDeletion || currentDeletionView === "submitting"}>
                {refreshingDeletion ? "Checking…" : "Refresh status"}
              </button>
            </div>
          </>
        )}
        </motion.div>
      </form>
    </BottomSheet>
  );
}
