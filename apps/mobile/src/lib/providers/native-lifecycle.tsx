import { focusManager } from '@tanstack/react-query';
import { AppState, type AppStateStatus } from 'react-native';
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

const NativeAppStateContext = createContext<AppStateStatus>(AppState.currentState ?? 'active');

export function NativeLifecycleBridge({ children }: { children: ReactNode }) {
  const [appState, setAppState] = useState<AppStateStatus>(() => AppState.currentState ?? 'active');

  useEffect(() => {
    focusManager.setEventListener((setFocused) => {
      const currentState = AppState.currentState ?? 'active';
      setAppState(currentState);
      setFocused(currentState === 'active');
      const subscription = AppState.addEventListener('change', (nextState) => {
        setAppState(nextState);
        setFocused(nextState === 'active');
      });

      return () => subscription.remove();
    });

    return () => {
      focusManager.setEventListener(() => undefined);
      focusManager.setFocused(undefined);
    };
  }, []);

  return <NativeAppStateContext.Provider value={appState}>{children}</NativeAppStateContext.Provider>;
}

export function useNativeAppState(): AppStateStatus {
  return useContext(NativeAppStateContext);
}
