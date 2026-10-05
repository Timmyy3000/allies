import { describe, expect, it } from "vitest";
import type { ActivityViewModel } from "@allies/cloud-client";
import {
  EMPTY_ACTIVITY_APPROVAL_PROJECTION,
  mergeActivityApprovals,
  selectActivityApprovals,
} from "./approval-activity";

const messageId = "00000000-0000-4000-8000-000000000001";
const approvalId = "00000000-0000-4000-8000-000000000002";

function activity(sequence: number, status: NonNullable<ActivityViewModel["approval"]>["status"]): ActivityViewModel {
  return {
    id: `00000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
    messageId,
    sequence,
    conversationTurnOrdinal: 1,
    kind: "awaiting_action",
    text: "Approval needed",
    state: "awaiting_action",
    createdAt: "2026-09-18T12:00:00Z",
    approval: {
      id: approvalId,
      status,
      expiresAt: "2026-09-18T12:05:00Z",
      decidedAt: status === "pending" ? null : "2026-09-18T12:01:00Z",
    },
  };
}

describe("activity approval projection", () => {
  it("projects the message binding needed by approval slots", () => {
    const result = mergeActivityApprovals(
      EMPTY_ACTIVITY_APPROVAL_PROJECTION,
      "conversation-1",
      [activity(1, "pending")],
    );

    expect(selectActivityApprovals(result)).toEqual([expect.objectContaining({
      id: approvalId,
      messageId,
      status: "pending",
    })]);
  });

  it("uses the highest sequence and ignores replayed or out-of-order status", () => {
    const completed = mergeActivityApprovals(
      EMPTY_ACTIVITY_APPROVAL_PROJECTION,
      "conversation-1",
      [activity(2, "approved")],
    );
    const replayed = mergeActivityApprovals(
      completed,
      "conversation-1",
      [activity(1, "pending"), activity(2, "approved")],
    );

    expect(selectActivityApprovals(replayed)[0]?.status).toBe("approved");
  });

  it("drops approvals from the previous conversation", () => {
    const first = mergeActivityApprovals(
      EMPTY_ACTIVITY_APPROVAL_PROJECTION,
      "conversation-1",
      [activity(1, "pending")],
    );
    const second = mergeActivityApprovals(first, "conversation-2", []);

    expect(selectActivityApprovals(second)).toEqual([]);
  });
});
