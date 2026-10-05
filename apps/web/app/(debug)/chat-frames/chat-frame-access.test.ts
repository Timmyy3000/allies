import { describe, expect, it } from "vitest";

import { CHAT_FRAME_IDS } from "./chat-frame-fixtures";
import { canAccessChatFrames } from "./chat-frame-access";

describe("chat-frame debug access", () => {
  it("allows only local development", () => {
    expect(canAccessChatFrames({ nodeEnv: "development" })).toBe(true);
    expect(canAccessChatFrames({ nodeEnv: "development", deploymentEnvironment: "local" })).toBe(true);
    expect(canAccessChatFrames({ nodeEnv: "development", deploymentEnvironment: "development" })).toBe(true);
  });

  it.each(["test", "preview", "staging", "production"])("denies %s deployment", (deploymentEnvironment) => {
    expect(canAccessChatFrames({ nodeEnv: "development", deploymentEnvironment })).toBe(false);
  });

  it("fails closed for production and never treats a public variable as a grant", () => {
    expect(canAccessChatFrames({ nodeEnv: "production", deploymentEnvironment: "local" })).toBe(false);
    expect(canAccessChatFrames({ nodeEnv: "production", deploymentEnvironment: "development" })).toBe(false);
    expect(canAccessChatFrames({ nodeEnv: "development", deploymentEnvironment: "preview" })).toBe(false);
  });

  it("keeps the exact approved inventory and excludes the keyboard frame", () => {
    expect(CHAT_FRAME_IDS).toHaveLength(25);
    expect(new Set(CHAT_FRAME_IDS).size).toBe(25);
    expect(CHAT_FRAME_IDS).not.toContain("315:1827");
  });
});
