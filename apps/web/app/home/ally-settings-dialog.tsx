"use client";

import type { AllyDeletionViewModel, AllySettingsInput, AllyViewModel, RoutineDiscoveryDetail, RoutineDiscoveryPage } from "@allies/cloud-client";
import { isCloudError } from "@allies/cloud-client";
import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { motion, useReducedMotion } from "motion/react";

import { AllyAvatar } from "../../components/ally-avatar";
import { AllyLookPicker } from "../../components/ally-look-picker";
import { allyAppearanceKey, resolveAllyAppearance, type ResolvedAllyAppearance } from "../../lib/allies/appearance";
import type { GmailReturn } from "../../lib/integrations/gmail-connect";
import { useSession } from "../../lib/session/session-context";
import { alliesQueryKey } from "../../lib/allies/query-keys";
import { WAITLIST_APPEARANCE_CATALOG_VERSION, WAITLIST_COLORS } from "../../lib/waitlist/catalog";

import { AllySafeInputs } from "./ally-safe-inputs";
import { AllyAccess } from "./ally-access";
import { formatRoutineSchedule } from "./conversation-frame";
import { BottomSheet, readableAccentForeground } from "./conversation-frame-primitives";
import frameStyles from "./conversation-frame.module.css";
import styles from "./ally-settings-dialog.module.css";

type SettingsDraft = {
  label: string;
  showLabel: boolean;
};

type ProfilePanel = "profile" | "label" | "look" | "routine";
type DeletionState = "active" | "pending" | "repair_required";
type DeletionView = "settings" | "confirming" | "submitting" | "pending" | "repair_required";

export const ALLY_DELETION_INITIAL_POLL_MS = 2_000;
export const ALLY_DELETION_MAX_POLL_MS = 30_000;
export const ALLY_DELETION_MAX_POLL_DURATION_MS = 10 * 60 * 1_000;
const PROFILE_ROUTINE_PREVIEW = 3;
const DEFAULT_LOOK: ResolvedAllyAppearance = { shape: "ghosty", color: WAITLIST_COLORS[0] };
const LABEL_MAX_LENGTH = 40;

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
  gmailReturn = null,
}: {
  ally: AllyViewModel;
  workspaceId: string;
  onClose: () => void;
  onSaved: (ally: AllyViewModel) => void;
  onDeletionStatus: (status: AllyDeletionViewModel) => void;
  onRefreshDeletion: () => Promise<AllyDeletionViewModel>;
  onOpenRoutine: (routineId: string) => void;
  gmailReturn?: GmailReturn | null;
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
  const [selectedRoutineId, setSelectedRoutineId] = useState<string | null>(null);
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

  const routineDetailQuery = useQuery({
    queryKey: [...alliesQueryKey(workspaceId), ally.id, "profile-routine", selectedRoutineId ?? "none"],
    enabled: panel === "routine" && Boolean(selectedRoutineId),
    queryFn: ({ signal }) => session.runCloudOperation(
      (operationSignal) => session.client.getRoutine(workspaceId, selectedRoutineId ?? "", operationSignal),
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
    await persist({ label, showLabel: Boolean(label) }, "label");
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

  const closeSubsheet = () => openPanel("profile");
  const closeSubsheetOnEscape = () => {
    if (panel === "profile" || currentDeletionView !== "settings") return false;
    if (!saving) closeSubsheet();
    return true;
  };
  const accent = currentAppearance?.color ?? DEFAULT_LOOK.color;
  const labelCount = [...draft.label].length;

  return (
    <BottomSheet
      modal
      hideHeader
      onClose={onClose}
      onEscape={closeSubsheetOnEscape}
      labelledBy="ally-settings-title"
      className={styles.settingsOverlay}
      closeDisabled={saving || currentDeletionView === "submitting"}
    >
      <h2 id="ally-settings-title" className={styles.visuallyHidden}>{ally.name} settings</h2>
      <form className={styles.settingsContent} onSubmit={currentDeletionView === "confirming" ? handleDelete : handleSubmit} noValidate>
        <div className={styles.profileTopBar} inert={panel !== "profile" && currentDeletionView === "settings" ? true : undefined}>
          <button type="button" className={styles.profileBack} aria-label="Close profile" onClick={onClose} disabled={saving || currentDeletionView === "submitting"}>
            <BackChevronIcon />
          </button>
        </div>
        <motion.div key={currentDeletionView} className={styles.settingsView} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reducedMotion ? 0 : .16 }}>
        {currentDeletionView === "settings" ? (
          <div className={styles.profilePage} inert={panel !== "profile" ? true : undefined}>
            <div className={styles.profileIdentity}>
              <button type="button" className={styles.profileAvatar} aria-label="Change look" onClick={() => openPanel("look")} disabled={saving}>
                {currentAppearance ? (
                  <AllyAvatar shape={currentAppearance.shape} color={currentAppearance.color} size={136} label="" />
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
              <div className={styles.profileSectionHead}><h4 id="ally-about-title">About</h4></div>
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
              accent={accent}
              expanded={routinesExpanded}
              onExpand={() => setRoutinesExpanded(true)}
              onOpenRoutine={(routineId) => {
                setSelectedRoutineId(routineId);
                openPanel("routine");
              }}
            />
            <div className={styles.profileSections} style={{ "--access-accent": accent } as CSSProperties}>
              <AllyAccess workspaceId={workspaceId} allyId={ally.id} returned={gmailReturn} />
              <AllySafeInputs workspaceId={workspaceId} ally={ally} />
            </div>
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
            {panel === "profile" ? (
              <div className={styles.settingsMessages} aria-live="polite">
                {error ? <p id="ally-settings-error" role="alert">{error}</p> : null}
                {status ? <p role="status">{status}</p> : null}
              </div>
            ) : null}
          </div>
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

        {currentDeletionView === "settings" && panel !== "profile" ? (
          <div className={styles.subsheetScrim} onClick={(event) => { if (event.target === event.currentTarget && !saving) closeSubsheet(); }}>
            <motion.section
              className={styles.subsheet}
              role="group"
              aria-labelledby="ally-subsheet-title"
              initial={reducedMotion ? false : { y: 24, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ duration: reducedMotion ? 0 : .18, ease: "easeOut" }}
            >
              <div className={styles.subsheetHead}>
                {panel === "routine" ? (
                  <span className={styles.routineSheetIcon} style={{ color: accent, background: `${accent}24` }} aria-hidden="true"><TimerIcon /></span>
                ) : (
                  <h3 id="ally-subsheet-title">{panel === "label" ? `${ally.name}'s label` : `How should ${ally.name} look?`}</h3>
                )}
                <button type="button" className={styles.subsheetClose} aria-label="Close" onClick={closeSubsheet} disabled={saving}><CloseIcon /></button>
              </div>

              {panel === "label" ? (
                <>
                  <input
                    id="ally-label"
                    aria-label="Label"
                    className={styles.labelInput}
                    type="text"
                    value={draft.label}
                    disabled={saving}
                    maxLength={LABEL_MAX_LENGTH}
                    autoComplete="off"
                    autoFocus
                    aria-invalid={Boolean(error && !status)}
                    aria-describedby={error ? "ally-label-count ally-settings-error" : "ally-label-count"}
                    onChange={(event) => updateDraft({ ...draft, label: event.target.value })}
                  />
                  <span id="ally-label-count" className={styles.labelCount}>{labelCount}/{LABEL_MAX_LENGTH}</span>
                </>
              ) : panel === "look" ? (
                <AllyLookPicker
                  shape={look.shape}
                  color={look.color}
                  colors={WAITLIST_COLORS}
                  dotColor={look.color}
                  swatchSize={40}
                  className={styles.lookPicker}
                  onShapeChange={(shape) => setLook({ ...look, shape })}
                  onColorChange={(color) => setLook({ ...look, color })}
                />
              ) : (
                <RoutineSheetBody query={routineDetailQuery} allyName={ally.name} />
              )}

              <div className={styles.settingsMessages} aria-live="polite">
                {error ? <p id="ally-settings-error" role="alert">{error}</p> : null}
                {status ? <p role="status">{status}</p> : null}
              </div>

              {panel === "label" ? (
                <button type="submit" className={styles.subsheetPrimary} disabled={saving}>{saving ? "Saving…" : "Save"}</button>
              ) : panel === "look" ? (
                <button
                  type="submit"
                  className={styles.subsheetPrimary}
                  style={{ background: look.color, color: readableAccentForeground(look.color) }}
                  disabled={saving || !lookChanged}
                >
                  {saving ? "Saving…" : "Use this look"}
                </button>
              ) : (
                <button type="button" className={styles.routineDeleteInChat} onClick={() => selectedRoutineId && onOpenRoutine(selectedRoutineId)}>
                  Delete in chat <ArrowUpRightIcon />
                </button>
              )}
            </motion.section>
          </div>
        ) : null}
      </form>
    </BottomSheet>
  );
}

function relativeNextRun(nextRunAt: string | null, now = new Date()): string | null {
  if (!nextRunAt) return null;
  const next = new Date(nextRunAt);
  if (Number.isNaN(next.getTime())) return null;
  const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const days = Math.round((startOfDay(next) - startOfDay(now)) / 86_400_000);
  if (days <= 0) return "Next today";
  if (days === 1) return "Next tomorrow";
  return `Next in ${days} days`;
}

function formatRoutineDay(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}

function ProfileRoutines({
  query,
  accent,
  expanded,
  onExpand,
  onOpenRoutine,
}: {
  query: UseQueryResult<RoutineDiscoveryPage>;
  accent: string;
  expanded: boolean;
  onExpand: () => void;
  onOpenRoutine: (routineId: string) => void;
}) {
  const head = (meta?: string) => (
    <div className={styles.profileSectionHead}>
      <h4 id="ally-routines-title">Routines</h4>
      {meta ? <span>{meta}</span> : null}
    </div>
  );
  if (query.isPending) {
    return (
      <section className={styles.profileSection} aria-labelledby="ally-routines-title" aria-busy="true">
        {head()}
        <div className={styles.routineSkeleton} />
      </section>
    );
  }
  if (query.isError) {
    return (
      <section className={styles.profileSection} aria-labelledby="ally-routines-title">
        {head()}
        <p className={styles.profileInlineError}>
          We couldn&apos;t load routines.{" "}
          <button type="button" onClick={() => void query.refetch()}>Try again</button>
        </p>
      </section>
    );
  }
  const routines = query.data.items;
  if (routines.length === 0) return null;
  const active = routines.filter((routine) => routine.scheduleState === "active").length;
  const visible = expanded ? routines : routines.slice(0, PROFILE_ROUTINE_PREVIEW);
  return (
    <section className={styles.profileSection} aria-labelledby="ally-routines-title">
      {head(`${active} active`)}
      <div className={styles.profileRoutines}>
        {visible.map((routine) => {
          const paused = routine.scheduleState === "paused";
          const detail = paused
            ? "Paused"
            : [formatRoutineSchedule(routine.schedule, false), relativeNextRun(routine.nextRunAt)].filter(Boolean).join(" · ");
          return (
            <button
              key={routine.routineId}
              type="button"
              className={styles.routineRow}
              style={{ background: `${accent}14` }}
              onClick={() => onOpenRoutine(routine.routineId)}
            >
              <span className={styles.routineRowIcon} style={{ color: accent, background: `${accent}24` }} aria-hidden="true"><TimerIcon /></span>
              <span className={styles.routineRowCopy}>
                <strong>{routine.title}</strong>
                <span style={{ color: paused ? undefined : accent }}>{detail}</span>
              </span>
              <ChevronRightIcon />
            </button>
          );
        })}
      </div>
      {!expanded && routines.length > PROFILE_ROUTINE_PREVIEW ? (
        <button type="button" className={styles.profileViewAll} onClick={onExpand}>View all {routines.length} routines</button>
      ) : null}
    </section>
  );
}

function RoutineSheetBody({ query, allyName }: { query: UseQueryResult<RoutineDiscoveryDetail>; allyName: string }) {
  if (query.isPending) return <div className={styles.routineSkeleton} aria-busy="true" />;
  if (query.isError) {
    return (
      <p className={styles.profileInlineError}>
        We couldn&apos;t load this routine.{" "}
        <button type="button" onClick={() => void query.refetch()}>Try again</button>
      </p>
    );
  }
  const routine = query.data;
  const rows: [string, string | null][] = [
    ["Repeats", formatRoutineSchedule(routine.schedule, false)],
    ["Next run", routine.scheduleState === "paused" ? "Paused" : formatRoutineDay(routine.nextRunAt)],
    ["Started", formatRoutineDay(routine.createdAt)],
  ];
  return (
    <>
      <h3 id="ally-subsheet-title" className={styles.routineSheetTitle}>{routine.title}</h3>
      <dl className={styles.routineFacts}>
        {rows.filter(([, value]) => value).map(([label, value]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
      <div className={styles.routinePrompt}>
        <span>What {allyName} does</span>
        <p>{routine.executionPrompt}</p>
      </div>
    </>
  );
}

function PaletteIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"><path d="M8 2a6 6 0 1 0 0 12c.8 0 1.2-.6 1.2-1.2 0-.8-.6-1-.6-1.8 0-.7.5-1.2 1.2-1.2H11a3 3 0 0 0 3-3C14 4.3 11.3 2 8 2Z" /><circle cx="5" cy="7" r=".6" fill="currentColor" /><circle cx="7.5" cy="4.8" r=".6" fill="currentColor" /><circle cx="10.5" cy="5.6" r=".6" fill="currentColor" /></svg>;
}

function PencilIcon() {
  return <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d="M10.5 2.5 13.5 5.5 5.5 13.5H2.5v-3Z" /></svg>;
}

function BackChevronIcon() {
  return <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12.5 4 6.5 10l6 6" /></svg>;
}

function CloseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M5 5l10 10M15 5 5 15" /></svg>;
}

function ChevronRightIcon() {
  return <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="#a0a0a0" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M6 3.5 10.5 8 6 12.5" /></svg>;
}

function TimerIcon() {
  return <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"><circle cx="10" cy="11" r="6.5" /><path d="M10 8v3.2l2 1.3M8 2.5h4" /></svg>;
}

function ArrowUpRightIcon() {
  return <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 11 11 5M6 5h5v5" /></svg>;
}
