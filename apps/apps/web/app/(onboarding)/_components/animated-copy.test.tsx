// @vitest-environment jsdom

import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { AnimatedCopy } from "./animated-copy";

beforeEach(() => {
  class ResizeObserverStub {
    observe() {}
    disconnect() {}
    unobserve() {}
  }
  Object.defineProperty(window, "ResizeObserver", {
    configurable: true,
    writable: true,
    value: ResizeObserverStub,
  });
  Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
    configurable: true,
    writable: true,
    value: () => null,
  });
});

describe("AnimatedCopy", () => {
  it("shows the finished story immediately when asked to start complete", () => {
    render(
      <AnimatedCopy
        paragraphs={[
          { ally: null, color: "#121212", parts: [{ type: "text", text: "We’re your allies" }] },
          {
            ally: "green",
            color: "#12c25b",
            parts: [{ type: "text", text: "We’re personal helpers." }],
          },
        ]}
        paragraphGap={0}
        beats={[
          { actor: "green", color: "#12c25b", paragraphs: [1] },
        ]}
        initialParagraphs={[0]}
        startComplete
        renderActor={() => null}
      />,
    );

    const story = document.querySelector("[data-story-phase]");
    expect(story?.getAttribute("data-story-phase")).toBe("done");
    expect(story?.textContent).toContain("We’re your allies");
    expect(story?.textContent).toContain("We’re personal helpers.");
    expect(story?.querySelector("[aria-hidden='true'][style*='visibility']")).toBeNull();
  });
});
