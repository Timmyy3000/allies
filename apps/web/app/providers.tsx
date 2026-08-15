"use client";

import { createCloudClient } from "@allies/cloud-client";
import { QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { prepareBrowserCloudRequest } from "../lib/cloud/browser-request";
import { getWebEnvironment } from "../lib/env";
import { createQueryClient } from "../lib/query/create-query-client";
import { SessionProvider } from "../lib/session/session-context";

export default function AppProviders({ children }: { children: ReactNode }) {
  const [environment] = useState(getWebEnvironment);
  const [queryClient] = useState(createQueryClient);
  const [cloudClient] = useState(() =>
    createCloudClient({
      // No request is made while the waitlist is disabled; this fallback keeps
      // the shared client constructible for the public static story.
      baseUrl: environment.cloudApiUrl ?? "https://cloud.invalid",
      prepareRequest: prepareBrowserCloudRequest,
    }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider client={cloudClient} restoreOnMount={environment.waitlistEnabled}>
        {children}
      </SessionProvider>
    </QueryClientProvider>
  );
}
