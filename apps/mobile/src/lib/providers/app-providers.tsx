import { QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import { createMobileCloudClient, type MobileCloudClient } from '../cloud/native-cloud-client';
import { getMobileEnvironment } from '../env';
import { createQueryClient } from '../query/create-query-client';
import { AllySessionIndexProvider } from '../../features/allies/ally-session-index';
import { MOCK_MODE, MockAppProvider } from '../../features/mock/mock-app';
import { NativeSessionProvider, useNativeSession } from '../session/session-context';
import { createSecureSessionStore } from '../session/secure-session-store';

function createConfiguredClient(): MobileCloudClient | null {
  if (MOCK_MODE) return null;
  try {
    const environment = getMobileEnvironment();
    if (environment.cloudApiUrl === 'https://cloud.invalid') return null;
    return createMobileCloudClient(environment);
  } catch {
    return null;
  }
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);
  const [client] = useState(createConfiguredClient);
  const [store] = useState(() => (client ? createSecureSessionStore() : null));

  return (
    <QueryClientProvider client={queryClient}>
      <NativeSessionProvider
        accountClient={client?.account}
        client={client ?? undefined}
        nativeAuthRedirectUri={client?.nativeAuthRedirectUri}
        onSessionCleared={() => queryClient.clear()}
        store={store ?? undefined}>
        <MockAppProvider>
          <SessionScopedAllyIndex>{children}</SessionScopedAllyIndex>
        </MockAppProvider>
      </NativeSessionProvider>
    </QueryClientProvider>
  );
}

function SessionScopedAllyIndex({ children }: { children: ReactNode }) {
  const session = useNativeSession();
  const identity = session.status === 'signed-in' && session.account
    ? `${session.account.userId}:${session.account.workspace.id}`
    : session.status;

  return <AllySessionIndexProvider key={identity}>{children}</AllySessionIndexProvider>;
}
