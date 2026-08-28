import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

export function appendReachableAllyId(current: string[], allyId: string): string[] {
  const normalized = allyId.trim();
  return !normalized || current.includes(normalized) ? current : [...current, normalized];
}

interface AllySessionIndexContextValue {
  reachableAllyIds: string[];
  addReachableAllyId(allyId: string): void;
  clearReachableAllyIds(): void;
}

const AllySessionIndexContext = createContext<AllySessionIndexContextValue | null>(null);

export function AllySessionIndexProvider({ children }: { children: ReactNode }) {
  const [reachableAllyIds, setReachableAllyIds] = useState<string[]>([]);

  const addReachableAllyId = useCallback((allyId: string) => {
    setReachableAllyIds((current) => appendReachableAllyId(current, allyId));
  }, []);

  const clearReachableAllyIds = useCallback(() => {
    setReachableAllyIds([]);
  }, []);

  const value = useMemo(
    () => ({ reachableAllyIds, addReachableAllyId, clearReachableAllyIds }),
    [addReachableAllyId, clearReachableAllyIds, reachableAllyIds],
  );

  return <AllySessionIndexContext.Provider value={value}>{children}</AllySessionIndexContext.Provider>;
}

export function useAllySessionIndex(): AllySessionIndexContextValue {
  const value = useContext(AllySessionIndexContext);
  if (!value) throw new Error('useAllySessionIndex must be used within AllySessionIndexProvider');
  return value;
}
