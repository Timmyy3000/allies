// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { useLayoutEffect } from "react";
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

  it("keeps hydrate and goTo stable so a resume effect cannot loop", () => {
    function ResumeHarness() {
      const hydrate = useOnboardingStore((state) => state.hydrate);
      const goTo = useOnboardingStore((state) => state.goTo);
      const name = useOnboardingStore((state) => state.name);
      const step = useOnboardingStore((state) => state.step);

      useLayoutEffect(() => {
        hydrate({
          name: "Ada",
          shape: "ghosty",
          color: "#ff5800",
          job: "",
          personalities: [],
          personalityNote: "",
          personalityRaw: null,
        });
        goTo("preview");
      }, [goTo, hydrate]);

      return (
        <output data-testid="resume-loop">
          {name}|{step}
        </output>
      );
    }

    render(
      <OnboardingStateProvider>
        <ResumeHarness />
      </OnboardingStateProvider>,
    );

    expect(screen.getByTestId("resume-loop").textContent).toBe("Ada|preview");
  });
});
