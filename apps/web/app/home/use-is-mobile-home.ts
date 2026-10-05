"use client";

import { useSyncExternalStore } from "react";

export const MOBILE_HOME_QUERY = "(max-width: 1023px)";

function subscribeMobileHome(callback: () => void) {
  if (typeof window === "undefined") return () => undefined;
  const mediaQuery = window.matchMedia(MOBILE_HOME_QUERY);
  mediaQuery.addEventListener("change", callback);
  return () => mediaQuery.removeEventListener("change", callback);
}

function getMobileHomeSnapshot() {
  return typeof window !== "undefined" && window.matchMedia(MOBILE_HOME_QUERY).matches;
}

export function useIsMobileHome() {
  return useSyncExternalStore(subscribeMobileHome, getMobileHomeSnapshot, () => false);
}
