import type { CloudError, CloudErrorKind } from "./errors";

const retryable = new Set<CloudErrorKind>(["network", "timeout", "server"]);

export function shouldRetryCloudQuery(failureCount: number, error: Pick<CloudError, "kind">): boolean {
  return failureCount < 2 && retryable.has(error.kind);
}
