import { describe, expect, it } from "vitest";

import { readIntegrationReturn } from "./integration-connect";

describe("readIntegrationReturn", () => {
  it("reads Cloud's connect outcome from the return URL", () => {
    expect(readIntegrationReturn(new URLSearchParams("gmail=connected"))).toEqual({ provider: "gmail", status: "connected" });
    expect(readIntegrationReturn(new URLSearchParams("gmail_error=access_denied"))).toEqual({ provider: "gmail", status: "failed", message: "Gmail wasn't connected." });
    expect(readIntegrationReturn(new URLSearchParams("gmail_error=scope_insufficient"))).toMatchObject({ status: "failed" });
    expect(readIntegrationReturn(new URLSearchParams("gmail_error=<script>"))).toEqual({ provider: "gmail", status: "failed", message: "That link expired. Try connecting again." });
    expect(readIntegrationReturn(new URLSearchParams(""))).toBeNull();
  });

  it("tells Calendar's outcome apart from Gmail's", () => {
    expect(readIntegrationReturn(new URLSearchParams("calendar=connected"))).toEqual({ provider: "calendar", status: "connected" });
    expect(readIntegrationReturn(new URLSearchParams("calendar_error=access_denied"))).toEqual({ provider: "calendar", status: "failed", message: "Calendar wasn't connected." });
    expect(readIntegrationReturn(new URLSearchParams("calendar_error=scope_insufficient"))).toMatchObject({ provider: "calendar", message: expect.stringContaining("Calendar") });
  });
});
