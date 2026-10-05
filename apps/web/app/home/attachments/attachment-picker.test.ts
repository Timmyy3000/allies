import { describe, expect, it } from "vitest";

import { middleEllipsis } from "./attachment-picker";

describe("middleEllipsis", () => {
  it("keeps the beginning and extension of a long filename", () => {
    const name = "Indirekte_Fragen_Konnektoren_Trotzdem_Deshalb_Grammatik_A2_Hueber_Verlag.pdf";
    const shortened = middleEllipsis(name, 32);

    expect(Array.from(shortened)).toHaveLength(32);
    expect(shortened).toMatch(/^Indirekte_Fragen/);
    expect(shortened).toMatch(/….*\.pdf$/);
  });

  it("leaves short filenames unchanged", () => {
    expect(middleEllipsis("notes.pdf")).toBe("notes.pdf");
  });
});
