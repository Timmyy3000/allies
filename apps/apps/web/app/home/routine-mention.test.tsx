// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RoutineUserText, routineLinkComponents } from "./routine-mention";
import { Streamdown } from "streamdown";

afterEach(cleanup);
const id = "00000000-0000-4000-8000-000000000010";

it("renders references as accessible labels and opens their exact routine", () => {
  const open = vi.fn();
  const { container } = render(<RoutineUserText text={`Delete [Morning \\[brief\\]](#routine/${id}).`} onOpen={open} />);
  expect(container.textContent).toBe("Delete Morning [brief].");
  fireEvent.click(screen.getByRole("button", { name: "Morning [brief]" }));
  expect(open).toHaveBeenCalledWith(id);
});

it("displays the exact legacy deletion format without exposing metadata", () => {
  const text = `Please start the confirmation flow to delete the routine "Morning brief".\nroutine_id=${id}; expected_revision=1;\ntitle_snapshot="Morning brief"`;
  const { container } = render(<RoutineUserText text={text} onOpen={vi.fn()} />);
  expect(container.textContent).toBe("Please delete the routine Morning brief.");
});

it("leaves ordinary text and malformed references unchanged", () => {
  const text = "routine_id=not-an-id [example](https://example.com)";
  const { container } = render(<RoutineUserText text={text} />);
  expect(container.textContent).toBe(text);
  expect(screen.queryByRole("button")).toBeNull();
});

it("uses the same reference button for assistant markdown links", () => {
  const open = vi.fn();
  render(<Streamdown mode="static" components={routineLinkComponents(open)}>{`See [Morning brief](#routine/${id}).`}</Streamdown>);
  fireEvent.click(screen.getByRole("button", { name: "Morning brief" }));
  expect(open).toHaveBeenCalledWith(id);
});

it("renders legacy shared-file tokens as inline file links", () => {
  const fileId = "11111111-2222-4333-8444-555555555555";
  render(
    <Streamdown mode="static" components={routineLinkComponents()}>
      {`Published\n\n[shared-file](/files/${fileId})`}
    </Streamdown>,
  );
  expect(screen.getByText("Published")).toBeTruthy();
  const link = screen.getByRole("link", { name: "Open file" });
  expect(link.getAttribute("href")).toBe(`/files/${fileId}`);
  expect(link.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
});

it("opens named file links in the private preview and preserves unrelated links", () => {
  const fileId = "11111111-2222-4333-8444-555555555555";
  const openFile = vi.fn();
  render(
    <Streamdown mode="static" components={routineLinkComponents(undefined, openFile)}>
      {`[German verbs](/files/${fileId}) [shared-file](https://example.com)`}
    </Streamdown>,
  );
  const fileLink = screen.getByRole("link", { name: "German verbs" });
  fireEvent.click(fileLink);
  expect(openFile).toHaveBeenCalledWith(fileId);
  expect(fileLink.hasAttribute("data-file-reference")).toBe(true);
  expect(screen.getByRole("link", { name: "shared-file" })).toBeTruthy();
});

it("opens same-origin absolute and parameterized file links in the preview", () => {
  const fileId = "11111111-2222-4333-8444-555555555555";
  const openFile = vi.fn();
  render(
    <Streamdown mode="static" components={routineLinkComponents(undefined, openFile)}>
      {`[Absolute](${window.location.origin}/files/${fileId}) [Parameterized](/files/${fileId}?download=1#preview)`}
    </Streamdown>,
  );
  fireEvent.click(screen.getByRole("link", { name: "Absolute" }));
  fireEvent.click(screen.getByRole("link", { name: "Parameterized" }));
  expect(openFile).toHaveBeenNthCalledWith(1, fileId);
  expect(openFile).toHaveBeenNthCalledWith(2, fileId);
});

it("does not intercept cross-origin file-shaped links", () => {
  const fileId = "11111111-2222-4333-8444-555555555555";
  const openFile = vi.fn();
  render(
    <Streamdown mode="static" components={routineLinkComponents(undefined, openFile)}>
      {`[External](https://example.com/files/${fileId})`}
    </Streamdown>,
  );
  const link = screen.getByRole("link", { name: "External" });
  expect(link.hasAttribute("data-file-reference")).toBe(false);
  expect(openFile).not.toHaveBeenCalled();
});
