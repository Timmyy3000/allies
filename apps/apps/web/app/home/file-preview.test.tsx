// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImageLightbox } from "./conversation-frame-primitives";

afterEach(cleanup);

describe("file preview lightbox", () => {
  it("shows a loading skeleton with no layout shift", () => {
    render(<ImageLightbox onClose={() => undefined} alt="report" fileName="report.pdf" mime="application/pdf" sizeBytes={2048} state="loading" />);
    expect(screen.getByRole("status", { name: "Loading preview" })).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "report.pdf preview" }).getAttribute("aria-busy")).toBe("true");
  });

  it("renders images natively with correct size metadata", () => {
    render(<ImageLightbox onClose={() => undefined} alt="photo" fileName="photo.png" mime="image/png" sizeBytes={1536} state="ready" src="https://files.example/photo.png" />);
    expect(screen.getByRole("img", { name: "photo" }).getAttribute("src")).toBe("https://files.example/photo.png");
    expect(screen.getByText("1.5 KB")).toBeTruthy();
  });

  it("renders pdf bytes in a sandboxed frame", () => {
    render(<ImageLightbox onClose={() => undefined} alt="doc" fileName="doc.pdf" mime="application/pdf" sizeBytes={1048576} state="ready" src="https://files.example/doc.pdf" />);
    const frame = screen.getByTitle("doc.pdf");
    expect(frame.tagName).toBe("IFRAME");
    expect(frame.getAttribute("sandbox")).toContain("allow-same-origin");
    expect(screen.getByText("1 MB")).toBeTruthy();
  });

  it("shows docx and unknown types as an explicit card with actions, never blank", () => {
    render(<ImageLightbox onClose={() => undefined} alt="notes" fileName="notes.docx" mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document" sizeBytes={2048} state="ready" src="https://files.example/notes.docx" />);
    expect(screen.getByText("notes.docx")).toBeTruthy();
    expect(screen.getByText("2 KB")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download" }).getAttribute("href")).toBe("https://files.example/notes.docx");
    expect(screen.getByRole("link", { name: "Open" }).getAttribute("href")).toBe("https://files.example/notes.docx");
  });

  it("keeps the legacy image placeholder when only alt is provided", () => {
    const { container } = render(<ImageLightbox onClose={() => undefined} alt="preview shape" />);
    expect(screen.getByRole("dialog", { name: "Image preview" })).toBeTruthy();
    expect(container.querySelector('[role="img"]')).toBeTruthy();
  });

  it("reports load errors with a safe retry", () => {
    const onRetry = vi.fn();
    render(<ImageLightbox onClose={() => undefined} alt="broken" fileName="broken.pdf" mime="application/pdf" sizeBytes={10} state="error" onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
