import { describe, expect, it } from "vitest";

import { normalizeCloudError } from "../src/errors";

describe("normalizeCloudError", () => {
  it.each([
    [400, "bad-request"],
    [401, "unauthorized"],
    [404, "not-found"],
    [409, "conflict"],
    [415, "unsupported-media"],
    [422, "validation"],
    [429, "throttled"],
    [503, "server"],
  ] as const)("maps HTTP %i to %s", (status, kind) => {
    expect(normalizeCloudError(status, { status: "error", message: "No", data: null })).toMatchObject({
      kind,
      status,
    });
  });

  it("keeps only safe validation fields", () => {
    const error = normalizeCloudError(422, {
      status: "error",
      message: "Invalid",
      data: {
        code: "validation_error",
        details: {
          errors: [{ field: "display_name", message: "Required", token: "secret" }],
        },
      },
    });

    expect(error.code).toBe("validation_error");
    expect(error.fieldIssues).toEqual([{ field: "display_name", message: "Required" }]);
    expect(JSON.stringify(error)).not.toContain("secret");
  });
});
