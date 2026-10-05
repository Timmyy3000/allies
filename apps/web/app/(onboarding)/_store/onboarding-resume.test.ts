// @vitest-environment jsdom

import { afterEach, describe, expect, it } from "vitest";

import {
  ONBOARDING_GOOGLE_RETURN_TO,
  ONBOARDING_RESUME_STORAGE_KEY,
  clearOnboardingResume,
  hasOnboardingResumePending,
  isOnboardingResumeQuery,
  parseOnboardingResume,
  readOnboardingResume,
  resolvePostAuthPath,
  writeOnboardingResume,
} from "./onboarding-resume";

afterEach(() => {
  window.sessionStorage.clear();
});

describe("onboarding resume snapshot", () => {
  it("persists a valid ally draft and rejects tampered storage", () => {
    const snapshot = {
      name: "Tolani",
      shape: "ghosty" as const,
      color: "#3446e9",
      job: "Plan the week",
      personalities: ["Concise"],
      personalityNote: "Be concise, ",
      personalityRaw: null,
    };

    writeOnboardingResume(snapshot);
    expect(readOnboardingResume()).toEqual(snapshot);
    expect(hasOnboardingResumePending()).toBe(true);
    expect(resolvePostAuthPath("/home")).toBe("/");

    window.sessionStorage.setItem(
      ONBOARDING_RESUME_STORAGE_KEY,
      JSON.stringify({ ...snapshot, shape: "not-an-ally" }),
    );
    expect(readOnboardingResume()).toBeNull();

    clearOnboardingResume();
    expect(readOnboardingResume()).toBeNull();
    expect(hasOnboardingResumePending()).toBe(false);
    expect(resolvePostAuthPath("/home")).toBe("/home");
  });

  it("returns Google to the base route and resumes from stored draft", () => {
    expect(ONBOARDING_GOOGLE_RETURN_TO).toBe("/");
    expect(isOnboardingResumeQuery("welcome")).toBe(true);
    expect(isOnboardingResumeQuery("home")).toBe(false);
    expect(parseOnboardingResume({ name: 12 })).toBeNull();
  });
});
