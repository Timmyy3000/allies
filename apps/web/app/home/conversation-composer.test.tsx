// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConversationComposer, readableAccentForeground } from "./conversation-frame-primitives";

afterEach(cleanup);

function setMobileHome(matches: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => ({
      matches,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
}

beforeEach(() => setMobileHome(false));

function Composer({ initial = "", submit = (_value: string) => {} }) {
  const [value, setValue] = useState(initial);
  return <ConversationComposer allyName="Sage" value={value} placeholder="Reply Sage" disabled={false} sending={false} onChange={setValue} onSubmit={() => submit(value)} />;
}

describe("large composer drafts", () => {
  it("removes pasted content while preserving the prompt", async () => {
    const submit = vi.fn();
    render(<Composer initial={"Source\n".repeat(25)} submit={submit} />);
    fireEvent.change(screen.getByLabelText("Message Sage"), { target: { value: "Keep my prompt" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove pasted text" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Edit pasted text" })).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(submit).toHaveBeenCalledWith("Keep my prompt");
  });
  it("keeps the prompt editable beside a large paste and sends both", () => {
    const submit = vi.fn();
    render(<Composer initial="Summarize this" submit={submit} />);
    const field = screen.getByLabelText("Message Sage") as HTMLTextAreaElement;
    field.setSelectionRange(field.value.length, field.value.length);
    const pasted = "Source material\n".repeat(25);
    fireEvent.paste(field, { clipboardData: { getData: () => pasted } });
    expect(field.value).toBe("Summarize this");
    expect((screen.getByLabelText("Pasted text content") as HTMLTextAreaElement).value).toBe(pasted);
    fireEvent.change(field, { target: { value: "Explain this simply" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(submit).toHaveBeenCalledWith(`Explain this simply\n\n${pasted}`);
  });

  it("preserves the complete draft through preview edits and submission", () => {
    const submit = vi.fn();
    render(<Composer initial={"Original text\n".repeat(25)} submit={submit} />);
    expect(screen.getByRole("button", { name: "Edit pasted text" })).toBeTruthy();
    const editor = screen.getByLabelText("Pasted text content");
    const edited = "Updated text\n".repeat(30);
    fireEvent.change(editor, { target: { value: edited } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(submit).toHaveBeenCalledWith(edited);
  });

  it("rejects an oversized paste without changing the existing draft", () => {
    render(<Composer initial="Keep this" />);
    const field = screen.getByLabelText("Message Sage") as HTMLTextAreaElement;
    field.setSelectionRange(0, 0);
    const accepted = fireEvent.paste(field, { clipboardData: { getData: () => "x".repeat(16_000) } });
    expect(accepted).toBe(false);
    expect(field.value).toBe("Keep this");
    expect(screen.getAllByRole("alert")[0].textContent).toContain("draft has not changed");
  });

  it("allows a paste that fits after replacing the selected text", () => {
    render(<Composer initial="Replace this" />);
    const field = screen.getByLabelText("Message Sage") as HTMLTextAreaElement;
    field.setSelectionRange(0, field.value.length);
    fireEvent.paste(field, { clipboardData: { getData: () => "x".repeat(16_000) } });
    expect((screen.getByLabelText("Pasted text content") as HTMLTextAreaElement).value).toBe("x".repeat(16_000));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("composer keyboard behavior", () => {
  it("submits with Enter on desktop while Shift+Enter remains a newline", () => {
    setMobileHome(false);
    const submit = vi.fn();
    render(<Composer initial="Hello" submit={submit} />);
    const field = screen.getByLabelText("Message Sage");

    expect(fireEvent.keyDown(field, { key: "Enter", shiftKey: true })).toBe(true);
    expect(submit).not.toHaveBeenCalled();
    expect(fireEvent.keyDown(field, { key: "Enter" })).toBe(false);
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("lets mobile Enter insert a newline and submits only from the send control", () => {
    setMobileHome(true);
    const submit = vi.fn();
    render(<Composer initial="Hello" submit={submit} />);
    const field = screen.getByLabelText("Message Sage");

    expect(fireEvent.keyDown(field, { key: "Enter" })).toBe(true);
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(submit).toHaveBeenCalledWith("Hello");
  });

  it("does not submit an IME composition with Enter on desktop", () => {
    setMobileHome(false);
    const submit = vi.fn();
    render(<Composer initial="こんにちは" submit={submit} />);

    fireEvent.keyDown(screen.getByLabelText("Message Sage"), {
      key: "Enter",
      isComposing: true,
    });
    expect(submit).not.toHaveBeenCalled();
  });
});

describe("accent contrast", () => {
  const colors = ["#ff5800", "#fd304f", "#0d92fd", "#be9bf5", "#3446e9", "#a3f06f", "#fbe65f"];
  const luminance = (color: string) => {
    const channels = color.match(/[\da-f]{2}/gi)!.map((channel) => {
      const value = Number.parseInt(channel, 16) / 255;
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    });
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  };

  it.each(colors)("selects a foreground with at least 4.5:1 contrast for %s", (accent) => {
    const foreground = readableAccentForeground(accent);
    const lighter = Math.max(luminance(accent), luminance(foreground));
    const darker = Math.min(luminance(accent), luminance(foreground));
    expect((lighter + 0.05) / (darker + 0.05)).toBeGreaterThanOrEqual(4.5);
  });

  it("falls back safely for an invalid legacy accent", () => {
    expect(readableAccentForeground("not-a-color")).toBe("#ffffff");
  });
});
