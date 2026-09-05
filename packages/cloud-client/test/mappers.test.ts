import { describe, expect, it } from "vitest";

import { toAccountViewModel } from "../src/mappers/account";
import {
  toActivitySnapshotViewModel,
  toConversationViewModel,
} from "../src/mappers/allies";

describe("toAccountViewModel", () => {
  const account = {
    user: { id: "usr_example" },
    profile: { display_name: "Example User", avatar_url: null },
    session: { id: "ses_example", expires_at: "2026-08-13T12:00:00Z" },
    workspace: {
      id: "wsp_example",
      name: "Personal Workspace",
      role: "owner",
      capabilities: ["workspace:manage"],
    },
  };

  it("maps the wire account into Interface vocabulary", () => {
    expect(toAccountViewModel(account)).toEqual({
      userId: "usr_example",
      displayName: "Example User",
      avatarUrl: null,
      session: { id: "ses_example", expiresAt: "2026-08-13T12:00:00Z" },
      workspace: {
        id: "wsp_example",
        name: "Personal Workspace",
        role: "owner",
        capabilities: ["workspace:manage"],
      },
    });
  });

  it("allows additive wire fields but rejects consumed-field drift", () => {
    expect(toAccountViewModel({ ...account, future: true })).toMatchObject({ userId: "usr_example" });
    expect(() => toAccountViewModel({ ...account, session: { ...account.session, expires_at: "tomorrow" } })).toThrow();
  });
});

describe("durable reply mappers", () => {
  const reply = {
    id: "00000000-0000-4000-8000-000000000008",
    source_message_id: "00000000-0000-4000-8000-000000000004",
    conversation_turn_ordinal: 2,
    content: "The complete durable reply.",
    status: "completed",
    has_full_prefix: true,
    created_at: "2026-08-13T12:00:01Z",
    updated_at: "2026-08-13T12:00:02Z",
  } as const;

  it("maps conversation replies by source message and defaults old responses to an empty array", () => {
    expect(toConversationViewModel({
      id: "00000000-0000-4000-8000-000000000003",
      ally_id: "00000000-0000-4000-8000-000000000002",
      messages: [],
    })).toMatchObject({ assistantReplies: [] });
    expect(toConversationViewModel({
      id: "00000000-0000-4000-8000-000000000003",
      ally_id: "00000000-0000-4000-8000-000000000002",
      messages: [],
      assistant_replies: [reply],
    }).assistantReplies).toEqual([{
      id: reply.id,
      sourceMessageId: reply.source_message_id,
      conversationTurnOrdinal: reply.conversation_turn_ordinal,
      content: reply.content,
      status: reply.status,
      hasFullPrefix: reply.has_full_prefix,
      isTruncated: false,
      createdAt: reply.created_at,
      updatedAt: reply.updated_at,
    }]);
  });

  it("maps the optional current reply on activity snapshots", () => {
    expect(toActivitySnapshotViewModel({
      conversation_id: "00000000-0000-4000-8000-000000000003",
      activities: [],
      state: "completed",
      last_contiguous_sequence: 2,
      assistant_reply: reply,
    }).assistantReply).toMatchObject({
      sourceMessageId: reply.source_message_id,
      content: reply.content,
      hasFullPrefix: true,
    });
    expect(toActivitySnapshotViewModel({
      conversation_id: "00000000-0000-4000-8000-000000000003",
      activities: [],
      state: "completed",
      last_contiguous_sequence: 0,
    }).assistantReply).toBeNull();
  });

  it("preserves explicit reply truncation without changing terminal status", () => {
    expect(toActivitySnapshotViewModel({
      conversation_id: "00000000-0000-4000-8000-000000000003",
      activities: [],
      state: "completed",
      last_contiguous_sequence: 300,
      assistant_reply: { ...reply, is_truncated: true },
    }).assistantReply).toMatchObject({
      content: reply.content,
      status: "completed",
      hasFullPrefix: true,
      isTruncated: true,
    });
  });
});
