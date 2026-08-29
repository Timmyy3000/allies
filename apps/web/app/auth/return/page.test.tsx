import { describe, expect, it } from "vitest";

import { selectAuthError, selectAuthReturnTo } from "../../../lib/session/auth-route-query";

describe("auth return query selection", () => {
  it("keeps only safe local return paths", () => {
    expect(selectAuthReturnTo("/account?source=google")).toBe("/account?source=google");
    expect(selectAuthReturnTo("//evil.example")).toBe("/home");
  });

  it("allowlists callback categories without exposing raw query values", () => {
    expect(selectAuthError("access_denied")).toBe("access_denied");
    expect(selectAuthError("unexpected_provider_payload")).toBeUndefined();
    expect(selectAuthError(undefined)).toBeUndefined();
  });
});
