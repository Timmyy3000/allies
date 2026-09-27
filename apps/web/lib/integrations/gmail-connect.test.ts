import { describe, expect, it } from "vitest";

import { readGmailReturn } from "./gmail-connect";

describe("readGmailReturn", () => {
  it("reads Cloud's connect outcome from the return URL", () => {
    expect(readGmailReturn(new URLSearchParams("gmail=connected"))).toEqual({ status: "connected" });
    expect(readGmailReturn(new URLSearchParams("gmail_error=access_denied"))).toEqual({ status: "failed", message: "Gmail wasn't connected." });
    expect(readGmailReturn(new URLSearchParams("gmail_error=scope_insufficient"))).toMatchObject({ status: "failed" });
    expect(readGmailReturn(new URLSearchParams("gmail_error=<script>"))).toEqual({ status: "failed", message: "That link expired. Try connecting again." });
    expect(readGmailReturn(new URLSearchParams(""))).toBeNull();
  });
});
