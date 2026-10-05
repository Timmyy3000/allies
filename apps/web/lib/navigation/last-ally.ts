const KEY = "allies:last-ally";

export function rememberLastAlly(allyId: string | null): void {
  if (!allyId || allyId === "new") return;
  try { sessionStorage.setItem(KEY, allyId); } catch { /* Storage can be unavailable; returning home is fine. */ }
}

export function lastAllyHomePath(): string {
  try {
    const allyId = sessionStorage.getItem(KEY);
    return allyId ? `/home/${encodeURIComponent(allyId)}` : "/home";
  } catch { return "/home"; }
}
