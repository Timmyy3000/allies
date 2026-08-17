// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OnboardingStateProvider, useOnboardingStore } from "./onboarding-store";

function PersonalityHarness() {
  const note = useOnboardingStore((state) => state.personalityNote);
  const toggle = useOnboardingStore((state) => state.togglePersonality);

  return (
    <>
      <button type="button" onClick={() => toggle("Concise")}>
        Concise
      </button>
      <output>{note}</output>
    </>
  );
}

describe("onboarding personality suggestions", () => {
  it("inserts a writable prompt with a trailing comma and removes it when deselected", () => {
    render(
      <OnboardingStateProvider>
        <PersonalityHarness />
      </OnboardingStateProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Concise" }));
    expect(screen.getByRole("status").textContent).toBe("Be concise, ");

    fireEvent.click(screen.getByRole("button", { name: "Concise" }));
    expect(screen.getByRole("status").textContent).toBe("");
  });
});
