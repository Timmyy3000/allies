// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const audio = vi.hoisted(() => ({ bind: vi.fn(), play: vi.fn(), setEnabled: vi.fn(), setVolume: vi.fn() }));
vi.mock("cuelume", () => audio);

import { InteractionSoundsProvider, playInteractionSound, useInteractionSounds } from "./interaction-sounds";

function SoundToggle() {
  const { enabled, changeEnabled } = useInteractionSounds();
  return <input aria-label="Sound" type="checkbox" checked={enabled} onChange={(event) => changeEnabled(event.target.checked)} />;
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("interaction sounds", () => {
  it("starts silent, persists opt-in, restores it, and mutes immediately", () => {
    playInteractionSound("success");
    expect(audio.play).not.toHaveBeenCalled();
    const view = render(<InteractionSoundsProvider><SoundToggle /></InteractionSoundsProvider>);
    expect(audio.setEnabled).toHaveBeenLastCalledWith(false);
    expect(audio.setVolume).toHaveBeenCalledWith(0.25);
    expect(audio.play).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("checkbox"));
    expect(audio.setEnabled).toHaveBeenLastCalledWith(true);
    expect(localStorage.getItem("allies:interaction-sounds:v1")).toBe("on");
    expect(audio.play).toHaveBeenCalledOnce();
    view.unmount();
    expect(audio.setEnabled).toHaveBeenLastCalledWith(false);

    render(<InteractionSoundsProvider><SoundToggle /></InteractionSoundsProvider>);
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true);
    expect(audio.play).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(audio.setEnabled).toHaveBeenLastCalledWith(false);
    expect(localStorage.getItem("allies:interaction-sounds:v1")).toBe("off");
    expect(audio.play).toHaveBeenCalledOnce();
  });

  it("keeps the toggle usable when browser storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Blocked"); });
    render(<InteractionSoundsProvider><SoundToggle /></InteractionSoundsProvider>);
    fireEvent.click(screen.getByRole("checkbox"));
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true);
    expect(audio.setEnabled).toHaveBeenLastCalledWith(true);
  });

  it("treats an unknown stored value as muted", () => {
    localStorage.setItem("allies:interaction-sounds:v1", "true");
    render(<InteractionSoundsProvider><SoundToggle /></InteractionSoundsProvider>);
    expect(audio.setEnabled).toHaveBeenLastCalledWith(false);
  });
});
