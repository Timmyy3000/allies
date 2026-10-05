"use client";

import sheet from "../home/ally-settings-dialog.module.css";
import { THEME_PREFERENCES, type ThemePreference } from "../../lib/theme/theme";

import { SheetLayer } from "./account-parts";
import styles from "./account.module.css";

export const THEME_LABELS: Record<ThemePreference, string> = { system: "System", light: "Light", dark: "Dark" };

/** DSN-006 frame 3: live mini previews; picking one closes the sheet and runs the theme wipe. */
export function AppearanceSheet({ value, onPick, onClose }: {
  value: ThemePreference;
  onPick: (preference: ThemePreference) => void;
  onClose: () => void;
}) {
  return (
    <SheetLayer onDismiss={onClose}>
      <section className={sheet.subsheet} role="dialog" aria-modal="true" aria-labelledby="appearance-title">
        <div className={sheet.subsheetHead}>
          <h3 id="appearance-title">Appearance</h3>
          <button type="button" className={sheet.subsheetClose} aria-label="Close" onClick={onClose}>×</button>
        </div>
        <div className={styles.themeOptions} role="radiogroup" aria-labelledby="appearance-title">
          {THEME_PREFERENCES.map((preference) => (
            <button
              key={preference}
              type="button"
              role="radio"
              aria-checked={value === preference}
              className={styles.themeOption}
              onClick={() => onPick(preference)}
            >
              <span className={styles.themePreview} data-preview={preference} aria-hidden="true">
                {preference !== "dark" ? <span className={styles.previewHalf} data-tone="light"><ThemePreviewLines /></span> : null}
                {preference !== "light" ? <span className={styles.previewHalf} data-tone="dark"><ThemePreviewLines /></span> : null}
              </span>
              <span>{THEME_LABELS[preference]}</span>
            </button>
          ))}
        </div>
      </section>
    </SheetLayer>
  );
}

function ThemePreviewLines() {
  return (
    <>
      <i data-shape="avatar" />
      <i data-shape="line" />
      <i data-shape="row" />
      <i data-shape="row" />
      <i data-shape="cta" />
    </>
  );
}
