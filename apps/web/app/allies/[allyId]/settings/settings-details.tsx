"use client";

import { useRef, useState, type FormEvent } from "react";
import type { AllyViewModel } from "@allies/cloud-client";
import { AllyAvatar, ALLY_SHAPES, type AllyShape } from "@/components/ally-avatar";
import { WAITLIST_APPEARANCE_CATALOG_VERSION, WAITLIST_COLORS } from "@/lib/waitlist/catalog";
import styles from "./settings.module.css";

export function AllySettingsDetails({ ally, label = "", onSaveLabel }: {
  ally: AllyViewModel;
  label?: string;
  onSaveLabel?: (label: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState(label);
  const [saved, setSaved] = useState(label);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const saving = useRef(false);
  const [shape, color, ...extra] = ally.appearance.key.split(":");
  const knownColor = WAITLIST_COLORS.find((value) => value.slice(1) === color?.toLowerCase());
  const knownAppearance = ally.appearance.catalogVersion === WAITLIST_APPEARANCE_CATALOG_VERSION
    && ALLY_SHAPES.includes(shape as AllyShape) && knownColor && extra.length === 0;
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!onSaveLabel || saving.current || !draft.trim() || draft.trim() === saved) return;
    saving.current = true;
    setPending(true);
    setError(null);
    setStatus(null);
    const value = draft.trim();
    try {
      await onSaveLabel(value);
      setSaved(value);
      setDraft(value);
      setStatus("Label saved");
    } catch {
      setError("We couldn't save the label. Try again.");
    } finally {
      saving.current = false;
      setPending(false);
    }
  };

  return <div className={styles.details}>
    <div className={styles.identity}>
      {knownAppearance ? <AllyAvatar shape={shape as AllyShape} color={knownColor} size={88} label={`${ally.name} avatar`} />
        : <div className={styles.fallback} aria-label={`${ally.name} avatar unavailable`}>{ally.name.slice(0, 1)}</div>}
      <h2>{ally.name}</h2>
    </div>
    <form onSubmit={(event) => void save(event)} className={styles.labelForm}>
      <label htmlFor="ally-label">Label</label>
      <input id="ally-label" value={draft} readOnly={!onSaveLabel} disabled={pending} placeholder="No label yet"
        aria-describedby={!onSaveLabel ? "label-unavailable" : error ? "label-error" : "label-status"}
        aria-invalid={Boolean(error)} onChange={(event) => { setDraft(event.target.value); setError(null); setStatus(null); }} />
      {onSaveLabel ? <button type="submit" disabled={pending || !draft.trim() || draft.trim() === saved}>{pending ? "Saving…" : "Save label"}</button>
        : <p id="label-unavailable" className={styles.hint}>Edit this label from your ally’s chat settings.</p>}
      <p id="label-status" role="status">{status}</p>
      {error ? <p id="label-error" className={styles.error} role="alert">{error}</p> : null}
    </form>
    <dl className={styles.fields}>
      <div><dt>Job</dt><dd>{ally.job || "No job provided."}</dd></div>
      <div><dt>Personality</dt><dd>{ally.personality || "No personality provided."}</dd></div>
    </dl>
  </div>;
}
