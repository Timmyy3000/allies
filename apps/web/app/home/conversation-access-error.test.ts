import { describe, expect, it } from "vitest";

import {
  classifyConversationAccessError,
  conversationAccessCopy,
} from "./conversation-access-error";

describe("conversation access errors", () => {
  it.each([
    [{ kind: "unauthorized" }, "session-expired"],
    [{ kind: "client", status: 401 }, "session-expired"],
    [{ kind: "security" }, "forbidden"],
    [{ kind: "forbidden" }, "forbidden"],
    [{ kind: "client", status: 403 }, "forbidden"],
    [{ kind: "not-found" }, "inaccessible"],
    [{ kind: "client", status: 404 }, "inaccessible"],
    [{ kind: "network" }, "recoverable"],
    [new Error("temporary"), "recoverable"],
  ] as const)("classifies %j as %s", (error, expected) => {
    expect(classifyConversationAccessError(error)).toBe(expected);
  });

  it("uses non-enumerating copy for inaccessible conversations", () => {
    expect(conversationAccessCopy("forbidden")).toEqual({
      title: "This conversation isn't available",
      detail: "You don't have permission to open it here.",
    });
    expect(conversationAccessCopy("inaccessible")).toEqual({
      title: "This conversation isn't available",
      detail: "Choose another Ally to keep talking.",
    });
  });
});
