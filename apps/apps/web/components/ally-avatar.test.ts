import { describe, expect, test } from "vitest";
import {
  ALLY_AVATAR_CYCLE_MS,
  ALLY_ANIMATION_CYCLE_MS,
  DEFAULT_ALLY_COLOR,
  getAllyAsset,
  getAllyCycleDelay,
  normalizeAllyAnimationState,
  normalizeAllyColor,
  normalizeAllyShape,
} from "./ally-avatar";

describe("AllyAvatar contract helpers", () => {
  test("accepts the canonical shapes and rejects unknown shape input", () => {
    expect(normalizeAllyShape("boxy")).toBe("boxy");
    expect(normalizeAllyShape("rolly")).toBe("rolly");
    expect(normalizeAllyShape("circle")).toBeNull();
    expect(normalizeAllyShape(undefined)).toBeNull();
  });

  test("falls back to idle for an unknown animation state", () => {
    expect(normalizeAllyAnimationState("thinking")).toBe("thinking");
    expect(normalizeAllyAnimationState("working")).toBe("idle");
    expect(normalizeAllyAnimationState(undefined)).toBe("idle");
  });

  test("accepts the documented hex color forms and falls back safely", () => {
    expect(normalizeAllyColor(" #abc ")).toBe("#abc");
    expect(normalizeAllyColor("#abcd")).toBe("#abcd");
    expect(normalizeAllyColor("#AABBCC")).toBe("#AABBCC");
    expect(normalizeAllyColor("#AABBCCDD")).toBe("#AABBCCDD");
    expect(normalizeAllyColor("rgb(0, 0, 0)")).toBe(DEFAULT_ALLY_COLOR);
    expect(normalizeAllyColor(undefined)).toBe(DEFAULT_ALLY_COLOR);
  });

  test("maps full-motion and reduced-motion assets without cross-shape fallback", () => {
    expect(getAllyAsset("ghosty", "thinking")).toBe(
      "/ally/thinking/thinking_ghosty.svg",
    );
    expect(getAllyAsset("ghosty", "thinking", true)).toBe(
      "/ally/thinking/thinking_ghosty.reduced.svg",
    );
  });

  test("returns the remaining time to the next four-second boundary", () => {
    expect(getAllyCycleDelay(1_000, 1_000)).toBe(ALLY_AVATAR_CYCLE_MS);
    expect(getAllyCycleDelay(1_000, 2_500)).toBe(2_500);
    expect(getAllyCycleDelay(1_000, 5_000)).toBe(ALLY_AVATAR_CYCLE_MS);
    expect(getAllyCycleDelay(Number.NaN, 2_500)).toBe(ALLY_AVATAR_CYCLE_MS);
  });

  test("uses the supplied animation loop durations", () => {
    expect(ALLY_ANIMATION_CYCLE_MS.idle).toBe(ALLY_AVATAR_CYCLE_MS);
    expect(ALLY_ANIMATION_CYCLE_MS.thinking).toBe(4_502.083);
    expect(
      getAllyCycleDelay(1_000, 2_500, ALLY_ANIMATION_CYCLE_MS.thinking),
    ).toBeCloseTo(3_002.083, 6);
  });
});
