import { describe, expect, it } from "vitest";

import { getAccentPalette } from "./next-button";

describe("getAccentPalette", () => {
  it("uses dark text on light accents", () => {
    expect(getAccentPalette("#fbe65f").accentForeground).toBe("#121212");
  });

  it("uses light text on dark accents", () => {
    expect(getAccentPalette("#3446e9").accentForeground).toBe("#fff");
  });
});
