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

it("consumes shared-file tokens so publication metadata renders the card", () => {
  const fileId = "11111111-2222-4333-8444-555555555555";
  render(
    <Streamdown mode="static" components={routineLinkComponents()}>
      {`Published\n\n[shared-file](/files/${fileId})`}
    </Streamdown>,
  );
  expect(screen.getByText("Published")).toBeTruthy();
  expect(screen.queryByText("shared-file")).toBeNull();
  expect(screen.queryByRole("link")).toBeNull();
});

it("keeps named file links and unrelated shared-file labels visible", () => {
  const fileId = "11111111-2222-4333-8444-555555555555";
  render(
    <Streamdown mode="static" components={routineLinkComponents()}>
      {`[Report](/files/${fileId}) [shared-file](https://example.com)`}
    </Streamdown>,
  );
  expect(screen.getByRole("link", { name: "Report" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "shared-file" })).toBeTruthy();
});
