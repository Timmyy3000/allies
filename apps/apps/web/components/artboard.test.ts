import { describe, expect, test } from "vitest";

import { ART_W, getArtboardScale } from "./artboard";

describe("Artboard scaling", () => {
  test("does not enlarge the mobile artboard on desktop", () => {
    expect(getArtboardScale(1440)).toBe(1);
  });

  test("scales down to fit a narrow container", () => {
    expect(getArtboardScale(320)).toBeCloseTo(320 / ART_W);
  });
});
