import { isCloudError, shouldRetryCloudQuery } from '@allies/cloud-client';
import { QueryClient } from '@tanstack/react-query';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (failureCount, error) => isCloudError(error) && shouldRetryCloudQuery(failureCount, error),
        retryDelay: 250,
      },
      mutations: { retry: false },
    },
  });
}
