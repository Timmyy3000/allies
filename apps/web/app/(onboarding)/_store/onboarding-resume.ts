import { createContext } from "react";

import { ALLY_SHAPES, type AllyShape } from "../../../components/ally-avatar";

export const OnboardingAuthResumeContext = createContext(false);

export const ONBOARDING_GOOGLE_RETURN_TO = "/";
export const ONBOARDING_RESUME_STORAGE_KEY = "allies.onboarding.resume.v1";
export const ONBOARDING_RESUME_PENDING_KEY = "allies.onboarding.resume.pending";
export const ONBOARDING_RESUME_PENDING_VALUE = "welcome";

export type OnboardingResumeSnapshot = {
  name: string;
  shape: AllyShape;
  color: string | null;
  job: string;
  personalities: string[];
  personalityNote: string;
  personalityRaw: string | null;
};

function isAllyShape(value: unknown): value is AllyShape {
  return typeof value === "string" && (ALLY_SHAPES as readonly string[]).includes(value);
}

function isHexColor(value: unknown): value is string {
  return typeof value === "string" && /^#[\da-f]{6}$/i.test(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

export function isOnboardingResumeQuery(value: string | null | undefined): boolean {
  return value === "welcome";
}

export function hasOnboardingResumePending(): boolean {
  try {
    return window.sessionStorage.getItem(ONBOARDING_RESUME_PENDING_KEY) === ONBOARDING_RESUME_PENDING_VALUE;
  } catch {
    return false;
  }
}

export function hasOnboardingResume(): boolean {
  return hasOnboardingResumePending() || readOnboardingResume() !== null;
}

export function resolvePostAuthPath(returnTo: string): string {
  return hasOnboardingResumePending() ? ONBOARDING_GOOGLE_RETURN_TO : returnTo;
}

export function parseOnboardingResume(value: unknown): OnboardingResumeSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.name !== "string") return null;
  if (!isAllyShape(candidate.shape)) return null;
  if (candidate.color !== null && !isHexColor(candidate.color)) return null;
  if (typeof candidate.job !== "string") return null;
  if (!isStringArray(candidate.personalities)) return null;
  if (typeof candidate.personalityNote !== "string") return null;
  if (candidate.personalityRaw !== null && typeof candidate.personalityRaw !== "string") {
    return null;
  }

  return {
    name: candidate.name,
    shape: candidate.shape,
    color: candidate.color,
    job: candidate.job,
    personalities: candidate.personalities,
    personalityNote: candidate.personalityNote,
    personalityRaw: candidate.personalityRaw,
  };
}

export function writeOnboardingResume(snapshot: OnboardingResumeSnapshot): void {
  window.sessionStorage.setItem(ONBOARDING_RESUME_STORAGE_KEY, JSON.stringify(snapshot));
  window.sessionStorage.setItem(ONBOARDING_RESUME_PENDING_KEY, ONBOARDING_RESUME_PENDING_VALUE);
}

export function readOnboardingResume(): OnboardingResumeSnapshot | null {
  try {
    const raw = window.sessionStorage.getItem(ONBOARDING_RESUME_STORAGE_KEY);
    if (!raw) return null;
    return parseOnboardingResume(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function clearOnboardingResume(): void {
  window.sessionStorage.removeItem(ONBOARDING_RESUME_STORAGE_KEY);
  window.sessionStorage.removeItem(ONBOARDING_RESUME_PENDING_KEY);
}
