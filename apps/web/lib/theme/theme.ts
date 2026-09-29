export const THEME_PREFERENCES = ["system", "light", "dark"] as const;
export type ThemePreference = (typeof THEME_PREFERENCES)[number];
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "allies.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";
const WIPE_MS = 450;
const CROSSFADE_MS = 150;

export function parseThemePreference(value: unknown): ThemePreference {
  return THEME_PREFERENCES.includes(value as ThemePreference) ? value as ThemePreference : "system";
}

export function readThemePreference(): ThemePreference {
  try {
    return parseThemePreference(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

/** Re-reads the stored preference when another tab changes it. */
export function subscribeThemePreference(onChange: () => void) {
  const listener = (event: StorageEvent) => { if (event.key === THEME_STORAGE_KEY || event.key === null) onChange(); };
  window.addEventListener("storage", listener);
  return () => window.removeEventListener("storage", listener);
}

export function resolveTheme(preference: ThemePreference, systemDark: boolean): ResolvedTheme {
  if (preference === "system") return systemDark ? "dark" : "light";
  return preference;
}

function applyTheme(preference: ThemePreference) {
  const theme = resolveTheme(preference, window.matchMedia(DARK_QUERY).matches);
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.themePreference = preference;
}

/** Runs before first paint and keeps `system` in step with the OS. Mirrors applyTheme. */
export const THEME_INIT_SCRIPT = `(()=>{var k=${JSON.stringify(THEME_STORAGE_KEY)},q=matchMedia(${JSON.stringify(DARK_QUERY)}),r=document.documentElement;function p(){try{var v=localStorage.getItem(k);return v==="light"||v==="dark"?v:"system"}catch(e){return"system"}}function a(){var v=p();r.dataset.theme=v==="system"?(q.matches?"dark":"light"):v;r.dataset.themePreference=v}a();q.addEventListener("change",a)})()`;

type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void) => { ready: Promise<void> };
};

/**
 * Saves the preference and reveals the new theme as a circle growing from `origin`
 * (DSN-006 frame 4), or a short crossfade when motion is reduced.
 */
export function switchTheme(preference: ThemePreference, origin?: { x: number; y: number }) {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Storage can be blocked; the choice still applies for this page.
  }
  const root = document.documentElement;
  const next = resolveTheme(preference, window.matchMedia(DARK_QUERY).matches);
  const doc = document as ViewTransitionDocument;
  if (root.dataset.theme === next || !doc.startViewTransition) {
    applyTheme(preference);
    return;
  }

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  root.dataset.themeTransition = reduced ? "fade" : "wipe";
  const transition = doc.startViewTransition(() => applyTheme(preference));
  void transition.ready.then(() => {
    if (reduced) {
      root.animate({ opacity: [0, 1] }, { duration: CROSSFADE_MS, easing: "linear", pseudoElement: "::view-transition-new(root)" });
      return;
    }
    const x = origin?.x ?? window.innerWidth / 2;
    const y = origin?.y ?? window.innerHeight / 2;
    const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    root.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
      { duration: WIPE_MS, easing: "cubic-bezier(0.22, 1, 0.36, 1)", pseudoElement: "::view-transition-new(root)" },
    );
  }).catch(() => undefined).finally(() => {
    window.setTimeout(() => delete root.dataset.themeTransition, WIPE_MS + 50);
  });
}
