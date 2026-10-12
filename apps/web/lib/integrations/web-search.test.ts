import { describe, expect, it } from "vitest";

import { webSearchAccessProblem, webSearchConnectProblem } from "./web-search";

describe("webSearchConnectProblem", () => {
  it.each([
    [{ kind: "validation", status: 422, code: "web_search_key_rejected" }, "Parallel rejected this key. Check it and paste it again."],
    [{ kind: "validation", status: 422, code: "validation_error" }, "That key doesn't look right."],
    [{ kind: "bad-request" }, "That key doesn't look right."],
    [{ kind: "server", status: 503, code: "web_search_check_failed" }, "Couldn't check the key right now. Try again."],
    [{ kind: "server", status: 503, code: "vault_unavailable" }, "Web search can't store keys right now. Try again later."],
    [{ kind: "conflict", status: 409, code: "integration_conflict" }, "Web search changed while saving. Try again."],
    [{ kind: "server", status: 503, code: "provider_unavailable" }, "Parallel isn't responding. Try again."],
    [{ kind: "forbidden", status: 403 }, "You can't change access for this workspace."],
    [new Error("socket hang up"), "Something went wrong. Try again."],
  ])("explains %j", (error, message) => {
    expect(webSearchConnectProblem(error, "Parallel")).toBe(message);
  });
});

describe("webSearchAccessProblem", () => {
  it("asks the user to connect first when web search is not connected", () => {
    expect(webSearchAccessProblem({ kind: "conflict", status: 409, code: "web_search_not_connected" }))
      .toBe("Connect web search before changing access.");
  });

  it("keeps the workspace access message for a forbidden change", () => {
    expect(webSearchAccessProblem({ kind: "forbidden", status: 403 })).toBe("You can't change access for this workspace.");
  });
});
