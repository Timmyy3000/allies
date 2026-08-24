import { describe, expect, it } from "vitest";

import { selectAuthReturnTo } from "../../lib/session/auth-route-query";

describe("sign-in return path selection", () => {
  it("keeps valid root-relative paths", () => {
    expect(selectAuthReturnTo("/account?tab=profile#name")).toBe("/account?tab=profile#name");
  });

  it("falls back for unsafe or malformed paths", () => {
    expect(selectAuthReturnTo("https://evil.example/account")).toBe("/account");
    expect(selectAuthReturnTo("/%252F%252Fevil.example")).toBe("/account");
    expect(selectAuthReturnTo(undefined)).toBe("/account");
  });
});
