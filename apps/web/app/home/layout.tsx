"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { rememberLastAlly } from "../../lib/navigation/last-ally";
import { HomeWorkspace } from "./home-workspace";

export default function HomeLayout({ children }: { children: ReactNode }) {
  // Read the pathname, not the route segment: ally switches use pushState
  // without a server round trip, and only usePathname follows those.
  const segment = usePathname().split("/")[2];
  const selectedAllyId = segment ? decodeURIComponent(segment) : null;
  useEffect(() => rememberLastAlly(selectedAllyId), [selectedAllyId]);

  return (
    <>
      <HomeWorkspace selectedAllyId={selectedAllyId} />
      {children}
    </>
  );
}
