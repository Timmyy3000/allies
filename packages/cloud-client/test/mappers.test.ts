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

describe("routine chat projection mappers", () => {
  const conversationId = "00000000-0000-4000-8000-000000000003";
  const routineId = "00000000-0000-4000-8000-000000000010";
  const occurrenceId = "00000000-0000-4000-8000-000000000011";
  const runId = "00000000-0000-4000-8000-000000000012";
  const executionId = "00000000-0000-4000-8000-000000000013";
  const attemptId = "00000000-0000-4000-8000-000000000014";
  const resultId = "00000000-0000-4000-8000-000000000015";
  const schedule = {
    kind: "recurring" as const,
    frequency: "daily" as const,
    local_time: "09:30:00",
    timezone: "UTC",
  };

  it("maps creation, running, and result projections while retaining insertion state", () => {
    const routineItems = [
      {
        id: routineId,
        kind: "created" as const,
        routine_id: routineId,
        conversation_id: conversationId,
        title_snapshot: "Morning brief",
        routine_revision: 2,
        schedule_generation: 1,
        status: "created",
        schedule,
        occurred_at: "2026-09-09T08:00:00Z",
      },
      {
        id: runId,
        kind: "running" as const,
        routine_id: routineId,
        conversation_id: conversationId,
        title_snapshot: "Morning brief",
        routine_revision: 2,
        schedule_generation: 1,
        status: "approval_waiting",
        schedule,
        occurred_at: "2026-09-09T09:30:01Z",
        occurrence_id: occurrenceId,
        run_id: runId,
        delayed: false,
        approval_request_id: "00000000-0000-4000-8000-000000000016",
        approval_status: "pending",
        approval_expires_at: "2026-09-09T09:35:01Z",
      },
      {
        id: resultId,
        kind: "result" as const,
        routine_id: routineId,
        conversation_id: conversationId,
        title_snapshot: "Morning brief",
        routine_revision: 2,
        schedule_generation: 1,
        status: "changed",
        schedule,
        occurred_at: "2026-09-09T09:31:00Z",
        occurrence_id: occurrenceId,
        run_id: runId,
        execution_id: executionId,
        attempt_id: attemptId,
        generation: 1,
        result_id: resultId,
        result_insertion: "pending" as const,
        text: "The brief is ready.",
        references: [{ label: "Source", url: "https://example.com/source" }],
        delayed: false,
      },
    ];

    const mapped = toConversationViewModel({
      id: conversationId,
      ally_id: "00000000-0000-4000-8000-000000000002",
      messages: [],
      routine_items: routineItems,
    }).routineItems;

    expect(mapped).toHaveLength(3);
    expect(mapped[0]).toMatchObject({
      id: routineId,
      kind: "created",
      routineId,
      titleSnapshot: "Morning brief",
      schedule: { kind: "recurring", frequency: "daily", localTime: "09:30:00", timezone: "UTC" },
      resultInsertion: null,
    });
    expect(mapped[1]).toMatchObject({ runId, approvalRequestId: "00000000-0000-4000-8000-000000000016" });
    expect(mapped[2]).toMatchObject({
      resultId,
      executionId,
      attemptId,
      generation: 1,
      resultInsertion: "pending",
      references: [{ label: "Source", url: "https://example.com/source" }],
    });
  });

  it("rejects projection identity drift, cross-conversation items, and unsafe references", () => {
    const running = {
      id: runId,
      kind: "running" as const,
      routine_id: routineId,
      conversation_id: conversationId,
      title_snapshot: "Morning brief",
      routine_revision: 2,
      schedule_generation: 1,
      status: "working",
      schedule,
      occurred_at: "2026-09-09T09:30:01Z",
      occurrence_id: occurrenceId,
      run_id: routineId,
    };
    expect(() => toConversationViewModel({
      id: conversationId,
      ally_id: "00000000-0000-4000-8000-000000000002",
      messages: [],
      routine_items: [running],
    })).toThrow();

    expect(() => toConversationViewModel({
      id: conversationId,
      ally_id: "00000000-0000-4000-8000-000000000002",
      messages: [],
      routine_items: [{
        id: resultId,
        kind: "result",
        routine_id: routineId,
        conversation_id: "00000000-0000-4000-8000-000000000099",
        title_snapshot: "Morning brief",
        routine_revision: 2,
        schedule_generation: 1,
        status: "changed",
        schedule,
        occurred_at: "2026-09-09T09:31:00Z",
        result_id: resultId,
        result_insertion: "inserted",
        text: "Done",
        references: [{ label: "Unsafe", url: "javascript:alert(1)" }],
      }],
    })).toThrow();

    expect(() => toConversationViewModel({
      id: conversationId,
      ally_id: "00000000-0000-4000-8000-000000000002",
      messages: [],
      routine_items: [],
    }, "00000000-0000-4000-8000-000000000099")).toThrow();
  });
});
