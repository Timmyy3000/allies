import { createContext, useContext, type ReactNode } from 'react';

export interface NativeSessionState {
  status: 'unavailable';
  reason: 'native-session-contract-pending';
}

const unavailableSession: NativeSessionState = {
  status: 'unavailable',
  reason: 'native-session-contract-pending',
};

const SessionContext = createContext<NativeSessionState | null>(null);

export function NativeSessionProvider({ children }: { children: ReactNode }) {
  return <SessionContext.Provider value={unavailableSession}>{children}</SessionContext.Provider>;
}

export function useNativeSession(): NativeSessionState {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useNativeSession must be used within NativeSessionProvider');
  return value;
}
