"use client";

import type { ReactNode } from "react";
import { useSelectedLayoutSegment } from "next/navigation";

import { HomeWorkspace } from "./home-workspace";

export default function HomeLayout({ children }: { children: ReactNode }) {
  const selectedAllyId = useSelectedLayoutSegment();

  return (
    <>
      <HomeWorkspace selectedAllyId={selectedAllyId} />
      {children}
    </>
  );
}
