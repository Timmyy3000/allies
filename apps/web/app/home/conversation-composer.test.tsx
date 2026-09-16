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

function Composer({ initial = "", submit = () => {}, onFilesDrop, disabled = false, dropScope = "sage", onAttach }: {
  initial?: string;
  submit?: (value: string) => void;
  onFilesDrop?: (files: File[], origin: DOMRect) => boolean;
  disabled?: boolean;
  dropScope?: string;
  onAttach?: (anchor: HTMLElement) => void;
}) {
  const [value, setValue] = useState(initial);
  return <div data-testid="conversation-frame-shell"><div data-testid="conversation-transcript" /><ConversationComposer allyName="Sage" value={value} placeholder="Reply Sage" disabled={disabled} sending={false} onChange={setValue} onSubmit={() => submit(value)} onFilesDrop={onFilesDrop} dropScope={dropScope} onAttach={onAttach} /></div>;
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

  it("lets mobile Enter insert a newline while Ctrl+Enter still submits", () => {
    setMobileHome(true);
    const submit = vi.fn();
    render(<Composer initial="Hello" submit={submit} />);
    const field = screen.getByLabelText("Message Sage");

    expect(fireEvent.keyDown(field, { key: "Enter" })).toBe(true);
    expect(submit).not.toHaveBeenCalled();
    expect(fireEvent.keyDown(field, { key: "Enter", ctrlKey: true })).toBe(false);
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

describe("composer file drops", () => {
  it("adds pasted clipboard images through the attachment pipeline", () => {
    const onFilesDrop = vi.fn(() => true);
    const image = new File(["pixels"], "screenshot.png", { type: "image/png" });
    render(<Composer onFilesDrop={onFilesDrop} initial="Keep this draft" />);
    const field = screen.getByLabelText("Message Sage");

    expect(fireEvent.paste(field, {
      clipboardData: {
        items: [{ kind: "file", type: "image/png", getAsFile: () => image }],
        files: [image],
        getData: () => "",
      },
    })).toBe(false);

    expect(onFilesDrop).toHaveBeenCalledWith([image], expect.objectContaining({ width: 0, height: 0 }));
    expect(screen.getByText("Images added to your draft.")).toBeTruthy();
    expect((field as HTMLTextAreaElement).value).toBe("Keep this draft");
  });

  it("keeps accompanying clipboard text when adding an image", () => {
    const onFilesDrop = vi.fn(() => true);
    const image = new File(["pixels"], "screenshot.png", { type: "image/png" });
    render(<Composer onFilesDrop={onFilesDrop} initial="Keep " />);
    const field = screen.getByLabelText("Message Sage") as HTMLTextAreaElement;
    field.setSelectionRange(5, 5);

    fireEvent.paste(field, {
      clipboardData: {
        items: [
          { kind: "file", type: "image/png", getAsFile: () => image },
          { kind: "string", type: "text/plain", getAsFile: () => null },
        ],
        files: [image],
        getData: (type: string) => type === "text/plain" ? "this caption" : "",
      },
    });

    expect(onFilesDrop).toHaveBeenCalledWith([image], expect.anything());
    expect(field.value).toBe("Keep this caption");
    expect(screen.getByText("Images and text added to your draft.")).toBeTruthy();
  });

  it("leaves the draft unchanged when pasted clipboard images are rejected", () => {
    const onFilesDrop = vi.fn(() => false);
    const image = new File(["pixels"], "screenshot.png", { type: "image/png" });
    render(<Composer onFilesDrop={onFilesDrop} initial="Keep this draft" />);
    const field = screen.getByLabelText("Message Sage");

    fireEvent.paste(field, {
      clipboardData: {
        items: [{ kind: "file", type: "image/png", getAsFile: () => image }],
        files: [image],
        getData: () => "",
      },
    });

    expect(screen.getByText("These images could not be added. Your draft has not changed.")).toBeTruthy();
    expect((field as HTMLTextAreaElement).value).toBe("Keep this draft");
  });

  it("reports unavailable attachments without replacing the draft with a pasted image", () => {
    const image = new File(["pixels"], "screenshot.png", { type: "image/png" });
    render(<Composer initial="Keep this draft" />);
    const field = screen.getByLabelText("Message Sage");

    fireEvent.paste(field, {
      clipboardData: {
        items: [{ kind: "file", type: "image/png", getAsFile: () => image }],
        files: [image],
        getData: () => "",
      },
    });

    expect(screen.getByText("Attachments are unavailable right now.")).toBeTruthy();
    expect((field as HTMLTextAreaElement).value).toBe("Keep this draft");
  });

  it("keeps ordinary clipboard text on the existing paste path", () => {
    const onFilesDrop = vi.fn(() => true);
    render(<Composer onFilesDrop={onFilesDrop} />);
    const field = screen.getByLabelText("Message Sage");

    expect(fireEvent.paste(field, {
      clipboardData: { items: [], files: [], getData: () => "ordinary text" },
    })).toBe(true);
    expect(onFilesDrop).not.toHaveBeenCalled();
  });

  it("filters mixed drops and reports accepted files", () => {
    const onFilesDrop = vi.fn(() => true);
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    render(<Composer onFilesDrop={onFilesDrop} />);
    const composer = screen.getByTestId("conversation-composer");
    const dataTransfer = {
      types: ["Files", "text/plain"],
      items: [
        { kind: "string", getAsFile: () => null },
        { kind: "file", getAsFile: () => file },
      ],
      files: [file],
      dropEffect: "none",
    };
    fireEvent.dragEnter(composer, { dataTransfer });
    expect(screen.getByText("Drop files to attach")).toBeTruthy();
    fireEvent.drop(composer, { dataTransfer });
    expect(onFilesDrop).toHaveBeenCalledWith([file], expect.objectContaining({ width: 0, height: 0 }));
    expect(screen.getByText("Files added to your draft.")).toBeTruthy();
  });

  it("rejects directories without invoking the attachment callback", () => {
    const onFilesDrop = vi.fn(() => true);
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    render(<Composer onFilesDrop={onFilesDrop} />);
    const dataTransfer = {
      types: ["Files"],
      items: [{
        kind: "file",
        getAsFile: () => file,
        webkitGetAsEntry: () => ({ isDirectory: true }),
      }],
      files: [file],
      dropEffect: "none",
    };
    fireEvent.drop(screen.getByTestId("conversation-composer"), { dataTransfer });
    expect(onFilesDrop).not.toHaveBeenCalled();
    expect(screen.getByText("These files could not be added. Your draft has not changed.")).toBeTruthy();
  });

  it("prevents file navigation outside the composer without accepting the drop", () => {
    const onFilesDrop = vi.fn(() => true);
    render(<Composer onFilesDrop={onFilesDrop} initial="keep this draft" />);
    const file = new File(["hello"], "notes.txt");
    const dataTransfer = { types: ["Files"], items: [], files: [file], dropEffect: "none" };

    expect(fireEvent.dragOver(document.body, { dataTransfer })).toBe(false);
    expect(fireEvent.drop(document.body, { dataTransfer })).toBe(false);
    expect(onFilesDrop).not.toHaveBeenCalled();
    expect(screen.getByText("Drop files in the composer to attach them.")).toBeTruthy();
    expect((screen.getByLabelText("Message Sage") as HTMLTextAreaElement).value).toBe("keep this draft");
  });

  it("accepts a file dropped anywhere in the active chat viewport", () => {
    const onFilesDrop = vi.fn(() => true);
    render(<Composer onFilesDrop={onFilesDrop} />);
    const viewport = screen.getByTestId("conversation-frame-shell");
    const file = new File(["hello"], "notes.txt");
    const dataTransfer = { types: ["Files"], items: [], files: [file], dropEffect: "none" };

    fireEvent.dragEnter(viewport, { dataTransfer });
    expect(viewport.getAttribute("data-file-drop-active")).toBe("true");
    fireEvent.drop(viewport, { dataTransfer });

    expect(onFilesDrop).toHaveBeenCalledWith([file], expect.objectContaining({ width: 0, height: 0 }));
    expect(screen.getByText("Files added to your draft.")).toBeTruthy();
    expect(viewport.getAttribute("data-file-drop-active")).toBeNull();
  });

  it("keeps the drop state active while moving between chat viewport children", () => {
    render(<Composer onFilesDrop={() => true} />);
    const viewport = screen.getByTestId("conversation-frame-shell");
    const composer = screen.getByTestId("conversation-composer");
    const transcript = screen.getByTestId("conversation-transcript");
    const file = new File(["hello"], "notes.txt");
    const dataTransfer = { types: ["Files"], items: [], files: [file], dropEffect: "none" };
    const leave = (target: HTMLElement, relatedTarget: EventTarget) => {
      const event = new Event("dragleave", { bubbles: true, cancelable: true });
      Object.defineProperties(event, {
        dataTransfer: { value: dataTransfer },
        relatedTarget: { value: relatedTarget },
      });
      fireEvent(target, event);
    };

    fireEvent.dragEnter(composer, { dataTransfer });
    leave(composer, transcript);

    expect(viewport.getAttribute("data-file-drop-active")).toBe("true");
    expect(screen.getByText("Drop files to attach")).toBeTruthy();

    leave(transcript, document.body);
    expect(viewport.getAttribute("data-file-drop-active")).toBeNull();
  });

  it("does not intercept text-only drags and rejects file drops while disabled", () => {
    const onFilesDrop = vi.fn(() => true);
    const { rerender } = render(<Composer onFilesDrop={onFilesDrop} />);
    expect(fireEvent.dragOver(document.body, {
      dataTransfer: { types: ["text/plain"], items: [], files: [], dropEffect: "none" },
    })).toBe(true);

    rerender(<Composer onFilesDrop={onFilesDrop} disabled />);
    const file = new File(["hello"], "notes.txt");
    fireEvent.drop(screen.getByTestId("conversation-composer"), {
      dataTransfer: { types: ["Files"], items: [], files: [file], dropEffect: "none" },
    });
    expect(onFilesDrop).not.toHaveBeenCalled();
    expect(screen.getByText("Attachments are unavailable right now.")).toBeTruthy();
  });

  it("clears drag state on Escape, scope changes, and unmount", () => {
    const onFilesDrop = vi.fn(() => true);
    const file = new File(["hello"], "notes.txt");
    const dataTransfer = { types: ["Files"], items: [], files: [file], dropEffect: "none" };
    const view = render(<Composer onFilesDrop={onFilesDrop} dropScope="one" />);
    let composer = screen.getByTestId("conversation-composer");
    fireEvent.dragEnter(composer, { dataTransfer });
    expect(composer.getAttribute("data-drop-active")).toBe("true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(composer.getAttribute("data-drop-active")).toBeNull();
    expect(screen.queryByText("Drop files to attach")).toBeNull();
    fireEvent.dragEnter(composer, { dataTransfer });
    view.rerender(<Composer onFilesDrop={onFilesDrop} dropScope="two" />);
    composer = screen.getByTestId("conversation-composer");
    expect(composer.getAttribute("data-drop-active")).toBeNull();
    expect(screen.queryByText("Drop files to attach")).toBeNull();
    view.unmount();
    expect(fireEvent.drop(document.body, { dataTransfer })).toBe(true);
  });

  it("keeps the keyboard-accessible picker path available", () => {
    const onAttach = vi.fn();
    render(<Composer onFilesDrop={() => true} onAttach={onAttach} />);
    const button = screen.getByRole("button", { name: "Add attachment" });
    button.focus();
    fireEvent.click(button);
    expect(onAttach).toHaveBeenCalledWith(button);
  });
});

describe("accent contrast", () => {
  const palette = [
    ["#ff5800", "#ffffff"],
    ["#fd304f", "#ffffff"],
    ["#0d92fd", "#ffffff"],
    ["#be9bf5", "#000000"],
    ["#3446e9", "#ffffff"],
    ["#a3f06f", "#000000"],
    ["#fbe65f", "#000000"],
  ];

  it.each(palette)("uses the approved foreground for %s", (accent, foreground) => {
    expect(readableAccentForeground(accent)).toBe(foreground);
  });

  it("falls back safely for an invalid legacy accent", () => {
    expect(readableAccentForeground("not-a-color")).toBe("#ffffff");
  });
});
