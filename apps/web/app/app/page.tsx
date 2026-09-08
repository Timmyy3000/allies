import type { Metadata } from "next";
import { Suspense } from "react";

import { AppPageClient } from "./app-page-client";

export const metadata: Metadata = {
  title: { absolute: "Allies" },
  alternates: { canonical: "/app" },
  openGraph: {
    title: "Allies",
    url: "/app",
  },
};

export default function AppPage() {
  return (
    <Suspense>
      <AppPageClient />
    </Suspense>
  );
}
