// @vitest-environment jsdom
import { beforeEach, expect, test } from "vitest";
import { lastAllyHomePath, rememberLastAlly } from "./last-ally";

beforeEach(() => sessionStorage.clear());

test("returns to the last opened Ally, ignoring the create route", () => {
  expect(lastAllyHomePath()).toBe("/home");
  rememberLastAlly("ally-1");
  rememberLastAlly("new");
  rememberLastAlly(null);
  expect(lastAllyHomePath()).toBe("/home/ally-1");
});
