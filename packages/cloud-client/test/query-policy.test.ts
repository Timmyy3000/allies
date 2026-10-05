import { describe, expect, it } from "vitest";

import { shouldRetryCloudQuery } from "../src/query-policy";

describe("shouldRetryCloudQuery", () => {
  it.each(["network", "timeout", "server"] as const)("retries %s once", (kind) => {
    expect(shouldRetryCloudQuery(1, { kind })).toBe(true);
    expect(shouldRetryCloudQuery(2, { kind })).toBe(false);
  });

  it.each(["unauthorized", "throttled", "contract", "aborted"] as const)(
    "does not retry %s",
    (kind) => expect(shouldRetryCloudQuery(1, { kind })).toBe(false),
  );
});
