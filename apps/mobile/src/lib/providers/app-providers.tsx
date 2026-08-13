import { QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import { getMobileEnvironment } from '../env';
import { createQueryClient } from '../query/create-query-client';
import { NativeSessionProvider } from '../session/session-context';

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);
  // Native auth is deferred, but public Cloud configuration must still fail fast.
  getMobileEnvironment();

  return (
    <QueryClientProvider client={queryClient}>
      <NativeSessionProvider>{children}</NativeSessionProvider>
    </QueryClientProvider>
  );
}
