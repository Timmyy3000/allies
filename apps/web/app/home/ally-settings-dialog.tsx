"use client";

import type { AllyDeletionViewModel, AllySettingsInput, AllyViewModel, RoutineDiscoveryPage } from "@allies/cloud-client";
import { isCloudError } from "@allies/cloud-client";
import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { motion, useReducedMotion } from "motion/react";

import { AllyAvatar, ALLY_SHAPES, type AllyShape } from "../../components/ally-avatar";
import { allyAppearanceKey, resolveAllyAppearance, type ResolvedAllyAppearance } from "../../lib/allies/appearance";
import { useSession } from "../../lib/session/session-context";
import { alliesQueryKey } from "../../lib/allies/query-keys";
import { WAITLIST_APPEARANCE_CATALOG_VERSION, WAITLIST_COLORS } from "../../lib/waitlist/catalog";

import { formatRoutineSchedule } from "./conversation-frame";
import { BottomSheet, RoutineCard } from "./conversation-frame-primitives";
import frameStyles from "./conversation-frame.module.css";
import styles from "./ally-settings-dialog.module.css";

type SettingsDraft = {
  label: string;
  showLabel: boolean;
};

type ProfilePanel = "profile" | "label" | "look";
type DeletionState = "active" | "pending" | "repair_required";
type DeletionView = "settings" | "confirming" | "submitting" | "pending" | "repair_required";

export const ALLY_DELETION_INITIAL_POLL_MS = 2_000;
export const ALLY_DELETION_MAX_POLL_MS = 30_000;
export const ALLY_DELETION_MAX_POLL_DURATION_MS = 10 * 60 * 1_000;
const PROFILE_ROUTINE_PREVIEW = 3;
const DEFAULT_LOOK: ResolvedAllyAppearance = { shape: "ghosty", color: WAITLIST_COLORS[0] };
const SHAPE_NAMES: Record<AllyShape, string> = { boxy: "Boxy", ghosty: "Ghosty", rocky: "Rocky", rolly: "Rolly" };

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

function saveError(error: unknown, subject: "label" | "look"): string {
  if (isCloudError(error)) {
    if (error.kind === "conflict" || error.status === 409) {
      return "This Ally changed elsewhere. We refreshed its settings. Review your draft and save again.";
    }
    if (error.kind === "validation" || error.status === 422 || error.kind === "bad-request") {
      return `Check the ${subject} and try again.`;
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
  onOpenRoutine,
}: {
  ally: AllyViewModel;
  workspaceId: string;
  onClose: () => void;
  onSaved: (ally: AllyViewModel) => void;
  onDeletionStatus: (status: AllyDeletionViewModel) => void;
  onRefreshDeletion: () => Promise<AllyDeletionViewModel>;
  onOpenRoutine: (routineId: string) => void;
}) {
  const reducedMotion = useReducedMotion();
  const session = useSession();
  const queryClient = useQueryClient();
  const initial = settingsFor(ally);
  const [draft, setDraft] = useState<SettingsDraft>(initial);
  const [panel, setPanel] = useState<ProfilePanel>("profile");
  const currentAppearance = resolveAllyAppearance(ally);
  const [lookDraft, setLook] = useState<ResolvedAllyAppearance | null>(null);
  const look = lookDraft ?? currentAppearance ?? DEFAULT_LOOK;
  const lookChanged = lookDraft !== null
    && (currentAppearance === null || allyAppearanceKey(lookDraft) !== allyAppearanceKey(currentAppearance));
  const [routinesExpanded, setRoutinesExpanded] = useState(false);
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

  const routinesQuery = useQuery({
    queryKey: [...alliesQueryKey(workspaceId), ally.id, "profile-routines"],
    queryFn: ({ signal }) => session.runCloudOperation(
      (operationSignal) => session.client.listRoutines(workspaceId, { allyId: ally.id, signal: operationSignal }),
      { signal },
    ),
    retry: false,
  });

  const openPanel = (next: ProfilePanel) => {
    setError(null);
    setStatus(null);
    if (next === "look") setLook(null);
    if (panel === "label" && next !== "label") {
      dirtyRef.current = false;
      setDraft(remoteDraftRef.current);
    }
    setPanel(next);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (savingRef.current) return;
    if (panel === "look") {
      if (!lookChanged) return;
      const remote = remoteDraftRef.current;
      await persist({
        label: remote.label,
        showLabel: remote.showLabel,
        appearance: { catalogVersion: WAITLIST_APPEARANCE_CATALOG_VERSION, key: allyAppearanceKey(look) },
      }, "look");
      return;
    }
    if (panel !== "label") return;
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
    await persist({ label, showLabel: Boolean(draft.showLabel && label) }, "label");
  };

  const persist = async (input: Omit<AllySettingsInput, "settingsRevision">, subject: "label" | "look") => {
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
          ...input,
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
      if (mountedRef.current) setPanel("profile");
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
        : saveError(caught, subject));
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
      title={panel === "label" ? "Edit label" : panel === "look" ? "Change look" : `${ally.name} settings`}
      onClose={onClose}
      labelledBy="ally-settings-title"
      className={styles.settingsOverlay}
      closeDisabled={saving || currentDeletionView === "submitting"}
    >
      <form className={styles.settingsContent} onSubmit={currentDeletionView === "confirming" ? handleDelete : handleSubmit} noValidate>
        <motion.div key={currentDeletionView} className={styles.settingsView} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reducedMotion ? 0 : .16 }}>
        {currentDeletionView === "settings" && panel === "profile" ? (
          <>
            <div className={styles.profileIdentity}>
              <button type="button" className={styles.profileAvatar} aria-label="Change look" onClick={() => openPanel("look")} disabled={saving}>
                {currentAppearance ? (
                  <AllyAvatar shape={currentAppearance.shape} color={currentAppearance.color} size={96} label="" />
                ) : <span className={styles.profileAvatarFallback} aria-hidden="true">?</span>}
                <span className={styles.profileAvatarBadge} aria-hidden="true"><PaletteIcon /></span>
              </button>
              <h3>{ally.name}</h3>
              <button type="button" className={styles.profileLabelPill} aria-label="Edit label" onClick={() => openPanel("label")} disabled={saving}>
                <span>{initial.label || "Add a label"}</span>
                <PencilIcon />
              </button>
            </div>
            <section className={styles.profileSection} aria-labelledby="ally-about-title">
              <h4 id="ally-about-title">About</h4>
              <div className={styles.profileList}>
                <details className={styles.profileDisclosure}>
                  <summary>Job</summary>
                  <p>{ally.job}</p>
                </details>
                <details className={styles.profileDisclosure}>
                  <summary>Personality</summary>
                  <p>{ally.personality}</p>
                </details>
              </div>
            </section>
            <ProfileRoutines
              query={routinesQuery}
              expanded={routinesExpanded}
              onExpand={() => setRoutinesExpanded(true)}
              onOpenRoutine={onOpenRoutine}
            />
            <div className={styles.profileList}>
              <button
                ref={deleteTriggerRef}
                type="button"
                className={styles.profileDeleteRow}
                onClick={() => {
                  setDeletionView("confirming");
                  setDeletionStatusCheckAvailable(false);
                  setDeletionErrorMessage(null);
                }}
                disabled={saving}
              >
                Delete Ally
              </button>
            </div>
            <div className={styles.settingsMessages} aria-live="polite">
              {error ? <p id="ally-settings-error" role="alert">{error}</p> : null}
              {status ? <p role="status">{status}</p> : null}
            </div>
          </>
        ) : currentDeletionView === "settings" && panel === "label" ? (
          <>
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
                aria-describedby={error ? "ally-settings-error" : undefined}
                onChange={(event) => updateDraft({ ...draft, label: event.target.value })}
              />
            </div>
            <label className={styles.settingsToggle}>
              <input
                type="checkbox"
                checked={draft.showLabel}
                disabled={saving || !normalizeLabel(draft.label)}
                onChange={(event) => updateDraft({ ...draft, showLabel: event.target.checked })}
              />
              <span><strong>Show label</strong></span>
            </label>
            <div className={styles.settingsMessages} aria-live="polite">
              {error ? <p id="ally-settings-error" role="alert">{error}</p> : null}
              {status ? <p role="status">{status}</p> : null}
            </div>
            <div className={frameStyles.frameSheetActions}>
              <button type="button" className={frameStyles.frameNeutralAction} onClick={() => openPanel("profile")} disabled={saving}>Cancel</button>
              <button type="submit" className={frameStyles.frameAccentAction} disabled={saving}>{saving ? "Saving…" : "Save"}</button>
            </div>
          </>
        ) : currentDeletionView === "settings" ? (
          <>
            <div className={styles.lookPreview}>
              <AllyAvatar shape={look.shape} color={look.color} size={120} label="" />
            </div>
            <fieldset className={styles.lookGroup} disabled={saving}>
              <legend>Shape</legend>
              <div className={styles.lookShapes}>
                {ALLY_SHAPES.map((shape) => (
                  <label key={shape} className={styles.lookShape}>
                    <input type="radio" name="ally-shape" value={shape} checked={look.shape === shape} onChange={() => setLook({ ...look, shape })} />
                    <AllyAvatar shape={shape} color={look.color} size={52} label="" motion="reduced" />
                    <span>{SHAPE_NAMES[shape]}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className={styles.lookGroup} disabled={saving}>
              <legend>Colour</legend>
              <div className={styles.lookColours}>
                {WAITLIST_COLORS.map((color) => (
                  <label key={color} className={styles.lookColour} style={{ background: color }}>
                    <input type="radio" name="ally-colour" value={color} aria-label={color} checked={look.color === color} onChange={() => setLook({ ...look, color })} />
                  </label>
                ))}
              </div>
            </fieldset>
            <div className={styles.settingsMessages} aria-live="polite">
              {error ? <p id="ally-settings-error" role="alert">{error}</p> : null}
              {status ? <p role="status">{status}</p> : null}
            </div>
            <div className={frameStyles.frameSheetActions}>
              <button type="button" className={frameStyles.frameNeutralAction} onClick={() => openPanel("profile")} disabled={saving}>Cancel</button>
              <button
                type="submit"
                className={frameStyles.frameAccentAction}
                disabled={saving || !lookChanged}
              >
                {saving ? "Saving…" : "Save"}
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

function ProfileRoutines({
  query,
  expanded,
  onExpand,
  onOpenRoutine,
}: {
  query: UseQueryResult<RoutineDiscoveryPage>;
  expanded: boolean;
  onExpand: () => void;
  onOpenRoutine: (routineId: string) => void;
}) {
  if (query.isPending) {
    return (
      <section className={styles.profileSection} aria-labelledby="ally-routines-title" aria-busy="true">
        <h4 id="ally-routines-title">Routines</h4>
        <div className={styles.routineSkeleton} />
      </section>
    );
  }
  if (query.isError) {
    return (
      <section className={styles.profileSection} aria-labelledby="ally-routines-title">
        <h4 id="ally-routines-title">Routines</h4>
        <p className={styles.profileInlineError}>
          We couldn&apos;t load routines.{" "}
          <button type="button" onClick={() => void query.refetch()}>Try again</button>
        </p>
      </section>
    );
  }
  const routines = query.data.items;
  if (routines.length === 0) return null;
  const visible = expanded ? routines : routines.slice(0, PROFILE_ROUTINE_PREVIEW);
  return (
    <section className={styles.profileSection} aria-labelledby="ally-routines-title">
      <h4 id="ally-routines-title">Routines</h4>
      <div className={styles.profileRoutines}>
        {visible.map((routine) => (
          <RoutineCard
            key={routine.routineId}
            name={routine.title}
            schedule={routine.scheduleState === "paused" ? "Paused" : formatRoutineSchedule(routine.schedule, false)}
            onOpen={() => onOpenRoutine(routine.routineId)}
          />
        ))}
      </div>
      {!expanded && routines.length > PROFILE_ROUTINE_PREVIEW ? (
        <button type="button" className={styles.profileViewAll} onClick={onExpand}>View all {routines.length} routines</button>
      ) : null}
    </section>
  );
}

function PaletteIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"><path d="M8 2a6 6 0 1 0 0 12c.8 0 1.2-.6 1.2-1.2 0-.8-.6-1-.6-1.8 0-.7.5-1.2 1.2-1.2H11a3 3 0 0 0 3-3C14 4.3 11.3 2 8 2Z" /><circle cx="5" cy="7" r=".6" fill="currentColor" /><circle cx="7.5" cy="4.8" r=".6" fill="currentColor" /><circle cx="10.5" cy="5.6" r=".6" fill="currentColor" /></svg>;
}

function PencilIcon() {
  return <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d="M10.5 2.5 13.5 5.5 5.5 13.5H2.5v-3Z" /></svg>;
}
