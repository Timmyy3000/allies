import { Suspense } from "react";

import { HomePageClient } from "./home-page-client";

export default function Home() {
  return (
    <Suspense>
      <HomePageClient />
    </Suspense>
  );
}
