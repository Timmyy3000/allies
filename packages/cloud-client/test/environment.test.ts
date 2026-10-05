import { describe, expect, it } from "vitest";

import { parsePublicCloudUrl } from "../src/environment";

describe("parsePublicCloudUrl", () => {
  it("accepts HTTPS and local HTTP URLs without path ambiguity", () => {
    expect(parsePublicCloudUrl("https://cloud.example.com/")).toBe("https://cloud.example.com");
    expect(parsePublicCloudUrl("http://localhost:8000")).toBe("http://localhost:8000");
  });

  it.each([
    "http://cloud.example.com",
    "https://user:password@cloud.example.com",
    "https://cloud.example.com/api/v1",
    "not-a-url",
  ])("rejects unsafe or ambiguous values: %s", (value) => {
    expect(() => parsePublicCloudUrl(value)).toThrow();
  });
});
