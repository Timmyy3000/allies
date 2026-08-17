import { describe, expect, it } from "vitest";

import {
  greetingFingerprint,
  parsePersonality,
  serializeAppearance,
  serializeConfiguration,
  serializePersonality,
  WaitlistMappingError,
} from "./catalog";

describe("waitlist v1 mappings", () => {
  it("pins the appearance catalog key", () => {
    expect(serializeAppearance("boxy", "#FF5800")).toEqual({
      appearance_catalog_version: "v1",
      appearance_key: "boxy:ff5800",
    });
  });

  it("serializes personality in canonical order and omits empty values", () => {
    expect(serializePersonality(["Funny", "Analytical"], "  Keep me moving.  ")).toBe(
      "Keep me moving.",
    );
    expect(serializePersonality([], "   ")).toBeUndefined();
  });

  it("preserves an untouched Cloud personality outside the local preset catalog", () => {
    expect(parsePersonality("Warm, reflective, and concise")).toEqual({
      personalities: [],
      personalityNote: "Warm, reflective, and concise",
    });
    expect(
      serializeConfiguration({
        name: "Nova",
        shape: "boxy",
        color: "#ff5800",
        job: "Keep me on track",
        personalities: [],
        personalityNote: "",
        personalityOverride: "Warm, reflective, and concise",
      }).personality,
    ).toBe("Warm, reflective, and concise");
  });

  it("round-trips a note-only personality without duplicating its prefix", () => {
    const parsed = parsePersonality("Note: Be kind");

    expect(parsed).toEqual({ personalities: [], personalityNote: "Be kind" });
    expect(serializePersonality(parsed.personalities, parsed.personalityNote)).toBe("Be kind");
  });

  it("does not let appearance-only changes alter the greeting fingerprint", () => {
    const first = greetingFingerprint({
      name: "Nova",
      job: "Plan my week",
      personalities: ["Concise"],
      personalityNote: "",
    });
    const same = greetingFingerprint({
      name: "Nova",
      job: "Plan my week",
      personalities: ["Concise"],
      personalityNote: "",
    });

    expect(first).toBe(same);
  });

  it("returns an allowlisted configuration payload", () => {
    expect(
      serializeConfiguration({
        name: "Nova",
        shape: "ghosty",
        color: "#FD304F",
        job: "Keep me on track",
        personalities: ["Funny", "Concise"],
        personalityNote: "Be kind",
      }),
    ).toEqual({
      name: "Nova",
      appearance_catalog_version: "v1",
      appearance_key: "ghosty:fd304f",
      job: "Keep me on track",
      personality: "Be kind",
    });
  });

  it("rejects unknown appearance values with a reason code", () => {
    expect(() => serializeAppearance("triangle", "#ff5800")).toThrowError(
      new WaitlistMappingError("appearance_shape_unknown", "Choose a supported Ally shape."),
    );
  });
});
