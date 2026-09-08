"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import styles from "./pwa-install.module.css";

export const PWA_INSTALL_DISMISSAL_KEY = "allies:pwa-install:v1:dismissed-at";
export const PWA_INSTALL_COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000;
const INSTALL_EVENT = "beforeinstallprompt";
const INSTALLED_EVENT = "appinstalled";
const INVITATION_DELAY_MS = 3_000;

type InstallChoice = { outcome: "accepted" | "dismissed" };

export type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void> | void;
  userChoice: Promise<InstallChoice>;
};

type PwaInstallContextValue = {
  canInstall: boolean;
  prompting: boolean;
  showInvitation: boolean;
  dismiss: () => void;
  promptInstall: () => Promise<void>;
};

type PwaState = {
  dismissedAt: number | null;
  hasNativePrompt: boolean;
  hydrated: boolean;
  installed: boolean;
  isIOS: boolean;
  isStandalone: boolean;
  now: number;
  prompting: boolean;
  storageUsable: boolean;
};

const initialState: PwaState = {
  dismissedAt: null,
  hasNativePrompt: false,
  hydrated: false,
  installed: false,
  isIOS: false,
  isStandalone: false,
  now: 0,
  prompting: false,
  storageUsable: true,
};

const PwaInstallContext = createContext<PwaInstallContextValue | null>(null);

function isInstallChoice(value: unknown): value is InstallChoice {
  if (!value || typeof value !== "object") return false;
  const outcome = (value as { outcome?: unknown }).outcome;
  return outcome === "accepted" || outcome === "dismissed";
}

function getInstallEvent(event: Event): BeforeInstallPromptEvent | null {
  try {
    const candidate = event as Partial<BeforeInstallPromptEvent>;
    if (typeof candidate.prompt !== "function") return null;
    if (!candidate.userChoice || typeof candidate.userChoice.then !== "function") return null;
    return candidate as BeforeInstallPromptEvent;
  } catch {
    return null;
  }
}

function detectIOS(): boolean {
  if (typeof navigator === "undefined") return false;
  const userAgent = navigator.userAgent;
  const isTouchMac = navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
  return /iPad|iPhone|iPod/u.test(userAgent) || isTouchMac;
}

function detectStandalone(): boolean {
  if (typeof window === "undefined") return false;
  try {
    if (typeof window.matchMedia === "function" && window.matchMedia("(display-mode: standalone)").matches) {
      return true;
    }
  } catch {
    // A missing media query should not hide the iOS navigator signal.
  }
  return typeof navigator !== "undefined"
    && (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

function readDismissal(): { dismissedAt: number | null; storageUsable: boolean } {
  try {
    const raw = window.localStorage.getItem(PWA_INSTALL_DISMISSAL_KEY);
    if (raw === null) return { dismissedAt: null, storageUsable: true };
    const dismissedAt = Number(raw);
    if (!Number.isSafeInteger(dismissedAt) || dismissedAt < 0) {
      return { dismissedAt: null, storageUsable: false };
    }
    const now = Date.now();
    if (dismissedAt > now && !persistDismissal(now)) {
      return { dismissedAt: null, storageUsable: false };
    }
    return { dismissedAt: Math.min(dismissedAt, now), storageUsable: true };
  } catch {
    return { dismissedAt: null, storageUsable: false };
  }
}

function persistDismissal(timestamp: number): boolean {
  try {
    window.localStorage.setItem(PWA_INSTALL_DISMISSAL_KEY, String(timestamp));
    return true;
  } catch {
    return false;
  }
}

export function PwaInstallProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState(initialState);
  const eventRef = useRef<BeforeInstallPromptEvent | null>(null);
  const consumedEventsRef = useRef(new WeakSet<BeforeInstallPromptEvent>());
  const promptingRef = useRef(false);
  const mountedRef = useRef(false);
  const cooldownTimerRef = useRef<number | null>(null);

  const scheduleCooldownExpiry = useCallback((dismissedAt: number) => {
    if (cooldownTimerRef.current !== null) window.clearTimeout(cooldownTimerRef.current);
    const delay = Math.max(0, dismissedAt + PWA_INSTALL_COOLDOWN_MS - Date.now());
    cooldownTimerRef.current = window.setTimeout(() => {
      cooldownTimerRef.current = null;
      if (mountedRef.current) setState((current) => ({ ...current, now: Date.now() }));
    }, delay);
  }, []);

  const dismiss = useCallback(() => {
    const timestamp = Date.now();
    const persisted = persistDismissal(timestamp);
    setState((current) => ({
      ...current,
      dismissedAt: timestamp,
      now: timestamp,
      storageUsable: current.storageUsable && persisted,
    }));
    scheduleCooldownExpiry(timestamp);
  }, [scheduleCooldownExpiry]);

  const promptInstall = useCallback(async () => {
    const current = eventRef.current;
    if (!current || promptingRef.current) return;
    promptingRef.current = true;
    if (mountedRef.current) setState((previous) => ({ ...previous, prompting: true }));
    try {
      await current.prompt();
      const choice = await current.userChoice;
      if (isInstallChoice(choice) && choice.outcome === "dismissed") dismiss();
    } catch {
      // Browser prompt failures only consume this event; no dismissal is claimed.
    } finally {
      if (eventRef.current === current) {
        eventRef.current = null;
        if (mountedRef.current) setState((previous) => ({ ...previous, hasNativePrompt: false }));
      }
      consumedEventsRef.current.add(current);
      promptingRef.current = false;
      if (mountedRef.current) setState((previous) => ({ ...previous, prompting: false }));
    }
  }, [dismiss]);

  useEffect(() => {
    mountedRef.current = true;

    const handleBeforeInstallPrompt = (event: Event) => {
      event.preventDefault();
      const promptEvent = getInstallEvent(event);
      if (!promptEvent) return;
      if (consumedEventsRef.current.has(promptEvent)) return;
      eventRef.current = promptEvent;
      setState((current) => ({ ...current, hasNativePrompt: true }));
    };
    const handleInstalled = () => {
      eventRef.current = null;
      setState((current) => ({ ...current, hasNativePrompt: false, installed: true }));
    };

    window.addEventListener(INSTALL_EVENT, handleBeforeInstallPrompt);
    window.addEventListener(INSTALLED_EVENT, handleInstalled);

    let media: MediaQueryList | null = null;
    try {
      if (typeof window.matchMedia === "function") media = window.matchMedia("(display-mode: standalone)");
    } catch {
      media = null;
    }
    const handleDisplayModeChange = () => {
      setState((current) => ({ ...current, isStandalone: detectStandalone() }));
    };
    if (media) {
      if (typeof media.addEventListener === "function") media.addEventListener("change", handleDisplayModeChange);
      else if (typeof media.addListener === "function") media.addListener(handleDisplayModeChange);
    }

    const initialize = () => {
      const dismissal = readDismissal();
      const now = Date.now();
      setState((current) => ({
        ...current,
        dismissedAt: dismissal.dismissedAt,
        hydrated: true,
        isIOS: detectIOS(),
        isStandalone: detectStandalone(),
        now,
        storageUsable: dismissal.storageUsable,
      }));
      if (dismissal.dismissedAt !== null && now - dismissal.dismissedAt < PWA_INSTALL_COOLDOWN_MS) {
        scheduleCooldownExpiry(dismissal.dismissedAt);
      }
    };
    const initializationTimer = window.setTimeout(initialize, 0);

    return () => {
      mountedRef.current = false;
      eventRef.current = null;
      window.clearTimeout(initializationTimer);
      if (cooldownTimerRef.current !== null) window.clearTimeout(cooldownTimerRef.current);
      window.removeEventListener(INSTALL_EVENT, handleBeforeInstallPrompt);
      window.removeEventListener(INSTALLED_EVENT, handleInstalled);
      if (media) {
        if (typeof media.removeEventListener === "function") media.removeEventListener("change", handleDisplayModeChange);
        else if (typeof media.removeListener === "function") media.removeListener(handleDisplayModeChange);
      }
    };
  }, [scheduleCooldownExpiry]);

  const cooldownActive = state.dismissedAt !== null
    && state.now - state.dismissedAt < PWA_INSTALL_COOLDOWN_MS;
  const showInvitation = state.hydrated
    && state.storageUsable
    && !state.installed
    && !state.isStandalone
    && !cooldownActive
    && (state.hasNativePrompt || state.isIOS);
  const value = useMemo<PwaInstallContextValue>(() => ({
    canInstall: state.hasNativePrompt && !state.prompting,
    prompting: state.prompting,
    showInvitation,
    dismiss,
    promptInstall,
  }), [dismiss, promptInstall, showInvitation, state.hasNativePrompt, state.prompting]);

  return <PwaInstallContext.Provider value={value}>{children}</PwaInstallContext.Provider>;
}

export function InstallInvitation() {
  const context = useContext(PwaInstallContext);
  const [instructionsOpen, setInstructionsOpen] = useState(false);
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(true), INVITATION_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, []);
  if (!context) return null;

  const { canInstall, prompting, showInvitation } = context;
  if (!settled || !showInvitation) return null;

  const openInstructions = () => {
    if (canInstall) {
      void context.promptInstall();
      return;
    }
    setInstructionsOpen(true);
  };
  const handlePrimaryAction = () => {
    if (instructionsOpen) {
      setInstructionsOpen(false);
      context.dismiss();
      return;
    }
    openInstructions();
  };

  return (
    <>
      <aside className={styles.invitation} aria-labelledby="pwa-install-title" data-testid="install-invitation">
        <h2 className={styles.title} id="pwa-install-title">Install Allies</h2>
        {instructionsOpen ? (
          <div className={styles.instructions} role="status" aria-labelledby="pwa-ios-instructions-title">
            <h3 className={styles.title} id="pwa-ios-instructions-title">Add Allies to your Home Screen</h3>
            <p>Tap Share, then choose “Add to Home Screen”.</p>
          </div>
        ) : (
          <p className={styles.copy}>Keep Allies close with a quick home screen shortcut.</p>
        )}
        <div className={styles.actions}>
          <button
            className={`${styles.button} ${styles.primary}`}
            type="button"
            onClick={handlePrimaryAction}
            disabled={prompting}
          >
            {instructionsOpen ? "Got it" : "Install Allies"}
          </button>
          <button className={`${styles.button} ${styles.secondary}`} type="button" onClick={() => { setInstructionsOpen(false); context.dismiss(); }}>
            Not now
          </button>
        </div>
      </aside>
    </>
  );
}
