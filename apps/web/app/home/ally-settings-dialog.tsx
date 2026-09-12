"use client";

import Link from "next/link";
import type { AllyViewModel } from "@allies/cloud-client";
import { isCloudError } from "@allies/cloud-client";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { useSession } from "../../lib/session/session-context";
import { alliesQueryKey } from "../../lib/allies/query-keys";

import { BottomSheet } from "./conversation-frame-primitives";
import frameStyles from "./conversation-frame.module.css";
import styles from "./ally-settings-dialog.module.css";

type SettingsDraft = {
  label: string;
  showLabel: boolean;
};

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

export function AllySettingsDialog({
  ally,
  workspaceId,
  onClose,
  onSaved,
}: {
  ally: AllyViewModel;
  workspaceId: string;
  onClose: () => void;
  onSaved: (ally: AllyViewModel) => void;
}) {
  const session = useSession();
  const queryClient = useQueryClient();
  const initial = settingsFor(ally);
  const [draft, setDraft] = useState<SettingsDraft>(initial);
  const dirtyRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
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

  useEffect(() => () => saveControllerRef.current?.abort(), []);

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

  return (
    <BottomSheet
      modal
      title={`${ally.name} settings`}
      onClose={onClose}
      labelledBy="ally-settings-title"
      className={styles.settingsOverlay}
      closeDisabled={saving}
    >
      <form className={styles.settingsContent} onSubmit={handleSubmit} noValidate>
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
        <div className={styles.settingsMessages} aria-live="polite">
          {error ? <p id="ally-settings-error" role="alert">{error}</p> : null}
          {status ? <p role="status">{status}</p> : null}
        </div>
        <div className={frameStyles.frameSheetActions}>
          <button type="button" className={frameStyles.frameNeutralAction} onClick={onClose} disabled={saving}>Cancel</button>
          <button type="submit" className={frameStyles.frameAccentAction} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </BottomSheet>
  );
}
