import { describe, expect, it } from "vitest";

import type { AllyViewModel, MessageViewModel } from "@allies/cloud-client";
import { ALLY_SLEEP_AFTER_MS, isAllySleeping } from "./home-workspace";

const NOW = Date.parse("2026-10-09T16:30:00.000Z");
const longAgo = new Date(NOW - ALLY_SLEEP_AFTER_MS - 60_000).toISOString();

const ally = (overrides: Partial<AllyViewModel> = {}) => ({
  provisioningState: "bound",
  ...overrides,
} as AllyViewModel);

const latestMessage = { createdAt: longAgo } as MessageViewModel;

describe("isAllySleeping", () => {
  it("sleeps once the last message and any local activity are past the window", () => {
    expect(isAllySleeping(ally(), latestMessage, NOW)).toBe(true);
  });

  it("stays awake while the server reports recent or in-flight work", () => {
    expect(isAllySleeping(ally({ recentActivity: true }), latestMessage, NOW)).toBe(false);
  });

  it("stays awake for an Ally that is not bound yet", () => {
    expect(isAllySleeping(ally({ provisioningState: "pending" }), latestMessage, NOW)).toBe(false);
  });
});
