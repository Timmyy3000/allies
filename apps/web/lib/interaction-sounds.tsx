"use client";

import { play, setEnabled, setVolume, type PlayOptions, type SoundName } from "cuelume";
import { useEffect, useSyncExternalStore, type ReactNode } from "react";

const STORAGE_KEY = "allies:interaction-sounds:v1";
let enabled = false;
const listeners = new Set<() => void>();

export function playInteractionSound(sound: SoundName, options?: PlayOptions) {
  if (enabled) play(sound, options);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function updateEnabled(next: boolean) {
  enabled = next;
  setEnabled(next);
  listeners.forEach((listener) => listener());
}

const getSnapshot = () => enabled;
const getServerSnapshot = () => false;

export function InteractionSoundsProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    let saved = false;
    try {
      saved = localStorage.getItem(STORAGE_KEY) === "on";
    } catch {
      // Sound still works for this visit when browser storage is unavailable.
    }
    setVolume(0.25);
    updateEnabled(saved);
    return () => updateEnabled(false);
  }, []);

  return children;
}

function changeEnabled(next: boolean) {
  updateEnabled(next);
  try {
    localStorage.setItem(STORAGE_KEY, next ? "on" : "off");
  } catch {
    // Keep the user's choice for this visit even if it cannot be persisted.
  }
  if (next) playInteractionSound("toggle", { emphasis: "subtle" });
}

export function useInteractionSounds() {
  return { enabled: useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot), changeEnabled };
}
