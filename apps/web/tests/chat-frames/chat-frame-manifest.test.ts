import { describe, expect, it } from "vitest";

import { CHAT_FRAME_IDS } from "../../app/(debug)/chat-frames/chat-frame-fixtures";
import manifest from "./chat-frame-visual-manifest.json";

describe("chat frame visual inventory", () => {
  it("keeps the fixture and manifest sets exact and excludes the keyboard frame", () => {
    const manifestIds = manifest.frames.map((frame) => frame.nodeId);

    expect(manifestIds).toHaveLength(25);
    expect(new Set(manifestIds)).toEqual(new Set(CHAT_FRAME_IDS));
    expect(manifestIds).not.toContain("315:1827");
    expect(manifest.excludedFrameIds).toEqual(["315:1827"]);
  });

  it("keeps every fixture tied to a deterministic capture path", () => {
    expect(manifest.frames.every((frame) => (
      frame.expectedSnapshot.endsWith(`chat-frame-${frame.nodeId.replace(":", "-")}.png`)
    ))).toBe(true);
    expect(manifest.frames.every((frame) => frame.evidenceSha256)).toBe(true);
  });
});
