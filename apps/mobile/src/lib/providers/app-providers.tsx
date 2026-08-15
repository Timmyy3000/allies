import { QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import { createQueryClient } from '../query/create-query-client';
import { NativeSessionProvider } from '../session/session-context';

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <NativeSessionProvider>{children}</NativeSessionProvider>
    </QueryClientProvider>
  );
}
