import { describe, expect, it } from "vitest";

import { profileFormSchema } from "./profile-schema";

describe("profileFormSchema", () => {
  it("trims and collapses whitespace", () => {
    expect(profileFormSchema.parse({ displayName: "  Ada   Lovelace  " })).toEqual({
      displayName: "Ada Lovelace",
    });
  });

  it("accepts normalized names at both length boundaries", () => {
    expect(profileFormSchema.safeParse({ displayName: "A" }).success).toBe(true);
    expect(profileFormSchema.safeParse({ displayName: "A".repeat(80) }).success).toBe(true);
    expect(profileFormSchema.safeParse({ displayName: "😀".repeat(80) }).success).toBe(true);
    expect(profileFormSchema.safeParse({ displayName: "😀".repeat(81) }).success).toBe(false);
  });

  it("rejects empty, overlong, and Unicode category C characters", () => {
    expect(profileFormSchema.safeParse({ displayName: "   " }).success).toBe(false);
    expect(profileFormSchema.safeParse({ displayName: "A".repeat(81) }).success).toBe(false);
    expect(profileFormSchema.safeParse({ displayName: "Ada\u200b" }).success).toBe(false);
    expect(profileFormSchema.safeParse({ displayName: "Ada\nLovelace" }).success).toBe(false);
  });

  it("returns an inferred parsed display-name value without mutating the draft", () => {
    const draft = { displayName: "  Ada  " };
    const parsed = profileFormSchema.parse(draft);

    expect(parsed.displayName).toBe("Ada");
    expect(draft.displayName).toBe("  Ada  ");
  });
});
