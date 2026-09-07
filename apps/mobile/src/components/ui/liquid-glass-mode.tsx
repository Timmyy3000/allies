import { useEffect, type ReactNode } from 'react';
import { DevSettings, Platform } from 'react-native';
import { create } from 'zustand';

export type LiquidGlassMode = 'automatic' | 'regular';

type LiquidGlassModeStore = {
  mode: LiquidGlassMode;
  setMode: (mode: LiquidGlassMode) => void;
};

export const useLiquidGlassModeStore = create<LiquidGlassModeStore>((set) => ({
  mode: 'automatic',
  setMode: (mode) => set({ mode }),
}));

let menuRegistered = false;

function registerDevelopmentMenu() {
  if (!__DEV__ || Platform.OS !== 'ios' || menuRegistered) return;

  menuRegistered = true;
  DevSettings.addMenuItem('Allies UI: Automatic Glass', () => {
    useLiquidGlassModeStore.getState().setMode('automatic');
  });
  DevSettings.addMenuItem('Allies UI: Regular', () => {
    useLiquidGlassModeStore.getState().setMode('regular');
  });
}

export function LiquidGlassModeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    registerDevelopmentMenu();
  }, []);

  return <>{children}</>;
}

export function useLiquidGlassMode() {
  return useLiquidGlassModeStore((state) => state.mode);
}
