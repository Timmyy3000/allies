// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingStateProvider } from "../_store/onboarding-store";
import { NameAllyScreen } from "./name-ally";

const useCreationWakeMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/allies/authenticated-onboarding-flow", () => ({
  useCreationWake: useCreationWakeMock,
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

function renderName(requestCreationWake: ReturnType<typeof vi.fn> | null = vi.fn(async () => undefined)) {
  useCreationWakeMock.mockReturnValue(requestCreationWake ? { requestCreationWake } : null);
  render(
    <OnboardingStateProvider initialStep="name">
      <NameAllyScreen />
    </OnboardingStateProvider>,
  );
  return screen.getByTestId("ally-name-input");
}

describe("NameAllyScreen creation wake", () => {
  it("does not send on mount, focus, or whitespace, then sends the first meaningful edit once", () => {
    const requestCreationWake = vi.fn(async () => undefined);
    const input = renderName(requestCreationWake);

    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "   " } });
    expect(requestCreationWake).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: " Mira" } });

    expect(requestCreationWake).toHaveBeenCalledOnce();
    expect(requestCreationWake).toHaveBeenCalledWith(" Mira");
  });

  it("waits for IME composition to commit before sending", () => {
    const requestCreationWake = vi.fn(async () => undefined);
    const input = renderName(requestCreationWake);

    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "日" } });
    expect(requestCreationWake).not.toHaveBeenCalled();

    fireEvent.compositionEnd(input, { target: { value: "日本語" } });

    expect(requestCreationWake).toHaveBeenCalledOnce();
    expect(requestCreationWake).toHaveBeenCalledWith("日本語");
  });

  it("leaves anonymous onboarding without a creation sender", () => {
    const requestCreationWake = vi.fn(async () => undefined);
    const input = renderName(null);

    fireEvent.change(input, { target: { value: "Mira" } });

    expect(requestCreationWake).not.toHaveBeenCalled();
  });
});
