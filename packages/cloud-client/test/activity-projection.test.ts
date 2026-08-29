import { describe, expect, it } from "vitest";

import type { ActivitySnapshotViewModel } from "../src";
import {
  EMPTY_ACTIVITY_PROJECTION,
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

  it("recognizes every non-active state as terminal", () => {
    expect(isActivityTerminal("queued")).toBe(false);
    expect(isActivityTerminal("running")).toBe(false);
    expect(isActivityTerminal("awaiting_action")).toBe(true);
    expect(isActivityTerminal("completed")).toBe(true);
    expect(isActivityTerminal("reconciliation_needed")).toBe(true);
  });
});
