import { describe, expect, it } from "vitest";
import type { ConversationViewModel } from "@allies/cloud-client";
import { latestAllyReply } from "./ally-preview";

const conversation: ConversationViewModel = {
  id: "conversation", allyId: "ally", nextCursor: null, routineItems: [],
  messages: [
    { id: "greeting", sender: "assistant", content: "Hello", sequence: 1, status: "completed", createdAt: "2026-09-10T10:00:00Z", retryable: false },
    { id: "user", sender: "user", content: "Thanks", sequence: 3, status: "completed", createdAt: "2026-09-10T12:00:00Z", retryable: false },
  ],
  assistantReplies: [{ id: "reply", sourceMessageId: "earlier-user", conversationTurnOrdinal: 2, content: "Your calendar is ready", status: "completed", hasFullPrefix: true, createdAt: "2026-09-10T11:00:00Z", updatedAt: "2026-09-10T11:00:00Z" }],
};

describe("latestAllyReply", () => {
  it("uses the latest durable Ally reply even when a newer user message exists", () => {
    expect(latestAllyReply(conversation)?.content).toBe("Your calendar is ready");
  });
  it("keeps the preceding Ally text when a new reply is still empty", () => {
    expect(latestAllyReply({ ...conversation, assistantReplies: [{ ...conversation.assistantReplies[0], content: " " }] })?.content).toBe("Hello");
  });
  it("never substitutes a user's message when there is no Ally text", () => {
    expect(latestAllyReply({ ...conversation, messages: [conversation.messages[1]], assistantReplies: [] })).toBeNull();
  });
});

it("ignores suffix-only replies and allows older history to supply the preview", () => {
  const partial = { ...conversation, assistantReplies: [{ ...conversation.assistantReplies[0], hasFullPrefix: false, content: "suffix only" }] };
  expect(latestAllyReply(partial)?.content).toBe("Hello");
  expect(latestAllyReply({ ...partial, messages: [conversation.messages[1]] })).toBeNull();
});
