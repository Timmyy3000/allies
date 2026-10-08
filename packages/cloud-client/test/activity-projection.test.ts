import { describe, expect, it } from "vitest";

import type { ActivitySnapshotViewModel } from "../src";
import {
  EMPTY_ACTIVITY_PROJECTION,
  anchorActivityWindow,
  hasPermanentActivityGap,
  isActivityTerminal,
  projectActivitySnapshot,
} from "../src/activity-projection";

function snapshot(
  sequences: number[],
  state: ActivitySnapshotViewModel["state"] = "running",
  lastContiguousSequence = Math.max(0, ...sequences),
) {
  return {
    conversationId: "00000000-0000-4000-8000-000000000001",
    state,
    lastContiguousSequence,
    activities: sequences.map((sequence) => ({
      id: `00000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
      messageId: "00000000-0000-4000-8000-000000000002",
      sequence,
      conversationTurnOrdinal: 2,
      kind: "assistant_delta" as const,
      text: String(sequence),
      state,
      createdAt: "2026-08-20T16:00:00Z",
    })),
  } satisfies ActivitySnapshotViewModel;
}

describe("activity projection", () => {
  it("can resume the same claimed turn after awaiting an action", () => {
    let projection = EMPTY_ACTIVITY_PROJECTION;
    for (const state of ["running", "awaiting_action", "running", "completed"] as const) {
      projection = projectActivitySnapshot(projection, { ...snapshot([1], state), activeMessageId: "head" });
      expect(projection.state).toBe(state);
      expect(projection.turns[0].state).toBe(state);
    }
  });

  it("lets a newly claimed head start queued without regressing the same head", () => {
    const completed = projectActivitySnapshot(EMPTY_ACTIVITY_PROJECTION, {
      ...snapshot([1], "completed"), activeMessageId: "first",
    });
    const next = projectActivitySnapshot(completed, {
      ...snapshot([1], "queued"), activeMessageId: "second",
    });
    expect(next.state).toBe("queued");
    expect(next.activeMessageId).toBe("second");
    const running = projectActivitySnapshot(next, { ...snapshot([], "running"), activeMessageId: "second" });
    expect(projectActivitySnapshot(running, { ...snapshot([], "queued"), activeMessageId: "second" }).state).toBe("running");
  });

  it("orders unseen deltas and ignores repeated snapshots", () => {
    const first = projectActivitySnapshot(EMPTY_ACTIVITY_PROJECTION, snapshot([2, 1]));
    expect(first.turns[0]?.assistantText).toBe("12");
    const repeated = projectActivitySnapshot(first, snapshot([1, 2, 3]));
    expect(repeated.turns[0]?.assistantText).toBe("123");
    expect(repeated.seenSequences).toEqual([1, 2, 3]);
  });

  it("keeps assistant text separated by conversation turn", () => {
    const mixedTurns = snapshot([1, 2, 3]);
    mixedTurns.activities[0]!.conversationTurnOrdinal = 5;
    mixedTurns.activities[0]!.messageId = "00000000-0000-4000-8000-000000000005";
    mixedTurns.activities[1]!.conversationTurnOrdinal = 3;
    mixedTurns.activities[1]!.messageId = "00000000-0000-4000-8000-000000000003";
    mixedTurns.activities[2]!.conversationTurnOrdinal = 5;
    mixedTurns.activities[2]!.messageId = "00000000-0000-4000-8000-000000000005";

    expect(projectActivitySnapshot(EMPTY_ACTIVITY_PROJECTION, mixedTurns).turns).toEqual([
      expect.objectContaining({ turnOrdinal: 3, assistantText: "2" }),
      expect.objectContaining({ turnOrdinal: 5, assistantText: "13" }),
    ]);
  });

  it("advances conversation activity when attempt-local continuity resets", () => {
    const firstTurn = snapshot([1, 2, 3], "completed", 3);
    firstTurn.activities.forEach((activity) => {
      activity.conversationTurnOrdinal = 2;
      activity.messageId = "00000000-0000-4000-8000-000000000002";
    });
    const first = projectActivitySnapshot(EMPTY_ACTIVITY_PROJECTION, firstTurn);

    const secondTurn = snapshot([1, 2, 3, 4, 5, 6], "completed", 3);
    secondTurn.activities.slice(3).forEach((activity) => {
      activity.conversationTurnOrdinal = 4;
      activity.messageId = "00000000-0000-4000-8000-000000000004";
    });
    const second = projectActivitySnapshot(first, secondTurn);

    expect(second.turns).toEqual([
      expect.objectContaining({ turnOrdinal: 2, assistantText: "123" }),
      expect.objectContaining({ turnOrdinal: 4, assistantText: "456" }),
    ]);
    expect(second.lastContiguousSequence).toBe(6);
    expect(second.pendingActivities).toBeUndefined();
  });

  it("holds deltas after a sequence gap and surfaces a terminal gap", () => {
    const partial = projectActivitySnapshot(EMPTY_ACTIVITY_PROJECTION, snapshot([1, 3], "completed", 1));
    expect(partial.turns[0]?.assistantText).toBe("1");
    expect(partial.pendingActivities?.map((activity) => activity.sequence)).toEqual([3]);
    expect(hasPermanentActivityGap(partial)).toBe(true);

    const reconciled = projectActivitySnapshot(partial, snapshot([1, 2, 3], "completed", 3));
    expect(reconciled.turns[0]?.assistantText).toBe("123");
    expect(reconciled.pendingActivities).toBeUndefined();
    expect(hasPermanentActivityGap(reconciled)).toBe(false);
  });

  it("does not let a stale active snapshot reopen a terminal projection", () => {
    const running = projectActivitySnapshot(EMPTY_ACTIVITY_PROJECTION, snapshot([1], "running"));
    const completed = projectActivitySnapshot(running, snapshot([1], "completed"));
    const stale = projectActivitySnapshot(completed, snapshot([1], "running"));

    expect(completed.state).toBe("completed");
    expect(stale.state).toBe("completed");
    expect(stale.turns[0]?.state).toBe("completed");
  });

  it("anchors a replay window that starts after sequence 1 and keeps applying its later pages", () => {
    const first = projectActivitySnapshot(
      anchorActivityWindow(EMPTY_ACTIVITY_PROJECTION, snapshot([3, 4], "running")),
      snapshot([3, 4], "running"),
    );
    expect(first.turns[0]?.assistantText).toBe("34");
    expect(first.pendingActivities).toBeUndefined();

    const next = projectActivitySnapshot(
      anchorActivityWindow(first, snapshot([5, 6], "completed")),
      snapshot([5, 6], "completed"),
    );
    expect(next.turns[0]?.assistantText).toBe("3456");
    expect(hasPermanentActivityGap(next)).toBe(false);
  });

  it("still holds a gap inside an anchored window", () => {
    const page = snapshot([3, 5], "completed");
    const projection = projectActivitySnapshot(anchorActivityWindow(EMPTY_ACTIVITY_PROJECTION, page), page);
    expect(projection.turns[0]?.assistantText).toBe("3");
    expect(projection.pendingActivities?.map((activity) => activity.sequence)).toEqual([5]);
    expect(hasPermanentActivityGap(projection)).toBe(true);
  });

  it("drains a page that arrives after a stream event already parked above it", () => {
    const streamed = projectActivitySnapshot(EMPTY_ACTIVITY_PROJECTION, snapshot([5], "running"));
    const page = snapshot([3, 4, 5], "completed");
    const projection = projectActivitySnapshot(anchorActivityWindow(streamed, page), page);
    expect(projection.turns[0]?.assistantText).toBe("345");
    expect(projection.pendingActivities).toBeUndefined();
  });

  it("recognizes every non-active state as terminal", () => {
    expect(isActivityTerminal("queued")).toBe(false);
    expect(isActivityTerminal("running")).toBe(false);
    expect(isActivityTerminal("awaiting_action")).toBe(false);
    expect(isActivityTerminal("completed")).toBe(true);
    expect(isActivityTerminal("reconciliation_needed")).toBe(true);
  });
});
