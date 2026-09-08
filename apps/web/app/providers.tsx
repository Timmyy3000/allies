"use client";

import { createCloudClient } from "@allies/cloud-client";
import { QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { prepareBrowserCloudRequest } from "../lib/cloud/browser-request";
import { createCloudCsrfTokenOwner } from "../lib/cloud/csrf-token";
import { getWebEnvironment } from "../lib/env";
import { createQueryClient } from "../lib/query/create-query-client";
import { SessionProvider } from "../lib/session/session-context";
import { PwaInstallProvider } from "../lib/pwa/pwa-install";

export default function AppProviders({ children }: { children: ReactNode }) {
  const [environment] = useState(getWebEnvironment);
  const [queryClient] = useState(createQueryClient);
  const [csrf] = useState(createCloudCsrfTokenOwner);
  const [cloudClient] = useState(() =>
    createCloudClient({
      // Keep the public story renderable when Cloud is not configured.
      baseUrl: environment.cloudApiUrl ?? "https://cloud.invalid",
      prepareRequest: (request) => prepareBrowserCloudRequest(request, csrf),
    }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider client={cloudClient} csrf={csrf}>
        <PwaInstallProvider>{children}</PwaInstallProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}
