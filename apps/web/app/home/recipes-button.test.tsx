// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RecipesButton } from "./recipes-button";

afterEach(() => { cleanup(); vi.useRealTimers(); });
it("announces, restarts, and dismisses the coming-soon notification", () => {
  vi.useFakeTimers();
  render(<RecipesButton className="">Chef</RecipesButton>);
  fireEvent.click(screen.getByRole("button", { name: "Recipes" }));
  expect(screen.getByRole("status").textContent).toContain("Recipes are coming soon.");
  act(() => vi.advanceTimersByTime(3000));
  fireEvent.click(screen.getByRole("button", { name: "Recipes" }));
  act(() => vi.advanceTimersByTime(3000));
  expect(screen.getByText("Recipes are coming soon.")).toBeTruthy();
  act(() => vi.advanceTimersByTime(1000));
  expect(screen.queryByText("Recipes are coming soon.")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Recipes" }));
  fireEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
  expect(screen.queryByText("Recipes are coming soon.")).toBeNull();
});
