import { describe, expect, it } from "vitest";
import { mergeConversationMessageCopies } from "../src/message-queue";
import type { MessageViewModel } from "../src/mappers/allies";

const pending: MessageViewModel = {
  id: "message", sender: "user", content: "Saved intent", sequence: 3,
  status: "queued", queueState: "unclaimed", createdAt: "2026-09-06T12:00:00Z",
};

describe("Cloud message reconciliation", () => {
  it("retains a redacted tombstone over old acceptance and history in either order", () => {
    const deleted: MessageViewModel = {
      ...pending, content: "", status: "stopped", queueState: null, deletedAt: "2026-09-06T12:01:00Z",
    };
    expect(mergeConversationMessageCopies([pending], [deleted], [pending])).toEqual([deleted]);
    expect(mergeConversationMessageCopies([deleted], [pending])).toEqual([deleted]);
  });

  it("does not regress a claim or terminal result when delayed acceptance arrives", () => {
    const claimed: MessageViewModel = { ...pending, queueState: "claimed" };
    const running: MessageViewModel = { ...claimed, status: "in_progress" };
    const completed: MessageViewModel = { ...running, status: "completed", queueState: null };
    expect(mergeConversationMessageCopies([claimed], [pending])).toEqual([claimed]);
    expect(mergeConversationMessageCopies([completed], [running], [pending])).toEqual([completed]);
  });
});
