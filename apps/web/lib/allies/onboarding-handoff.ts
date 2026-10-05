import { createAllyInputSchema, type CreateAllyInput } from "@allies/cloud-client";

const STORAGE_KEY = "allies.onboarding.handoff.v1";

export function hasOnboardingHandoff(): boolean {
  return window.sessionStorage.getItem(STORAGE_KEY) !== null;
}

export type OnboardingHandoff = {
  input: CreateAllyInput;
  key: string;
  owner: { userId: string; workspaceId: string } | null;
};

export function readOnboardingHandoff(): OnboardingHandoff | null {
  try {
    const value = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? "null");
    if (!value || typeof value.key !== "string" || value.key.length > 100 || !value.key.startsWith("ally-create-")) return null;
    const input = createAllyInputSchema.safeParse(value.input);
    if (!input.success) return null;
    if (value.owner !== null && (!value.owner || typeof value.owner.userId !== "string" || typeof value.owner.workspaceId !== "string")) return null;
    return { input: input.data, key: value.key, owner: value.owner };
  } catch {
    return null;
  }
}

export function saveOnboardingHandoff(input: CreateAllyInput): void {
  const parsed = createAllyInputSchema.parse(input);
  const previous = readOnboardingHandoff();
  if (previous && JSON.stringify(previous.input) === JSON.stringify(parsed)) return;
  if (previous?.owner) throw new Error("Finish your saved Ally before starting another.");
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
    input: parsed, key: `ally-create-${crypto.randomUUID()}`, owner: null,
  } satisfies OnboardingHandoff));
}

export function bindOnboardingHandoff(userId: string, workspaceId: string): OnboardingHandoff {
  const command = readOnboardingHandoff();
  if (!command) throw new Error("Your saved preview is incomplete. Return to your preview to continue.");
  if (command.owner && (command.owner.userId !== userId || command.owner.workspaceId !== workspaceId)) {
    throw new Error("This saved Ally belongs to another account. Sign in to that account to continue.");
  }
  const bound = { ...command, owner: { userId, workspaceId } };
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(bound));
  return bound;
}

export function clearOnboardingHandoff(): void {
  window.sessionStorage.removeItem(STORAGE_KEY);
}
