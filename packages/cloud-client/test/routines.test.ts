import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  MAX_ROUTINE_EVENT_BYTES,
  normalizeRoutineErrorCode,
  routineApprovalRequestedSchema,
  routineDetailResponseSchema,
  routineDispatchCommandSchema,
  routineDispatchReceiptSchema,
  routineEventReceiptSchema,
  routineManagementRequestSchema,
  routineResultEventSchema,
  routineScheduleSchema,
  toManagementReceipt,
  toRoutineApprovalProjection,
  toRoutineDetail,
  toRoutineResultProjection,
  toRoutineRunProjection,
} from "../src/routines";

type FixtureScope = {
  kind: "workspace";
  workspace_id: string;
  owner_user_id: string;
  ally_id: string;
  cloud_binding_id: string;
};

type FixtureMessage = {
  [key: string]: unknown;
  schema_version: "v1";
  issued_at: string;
  deadline_at: string;
  fingerprint: string;
  scope: FixtureScope;
};

const rev9Fixture = JSON.parse(readFileSync(new URL("./fixtures/routines-v1.json", import.meta.url), "utf8")) as {
  contract: { content_revision: number };
  identity: {
    workspace_id: string;
    owner_user_id: string;
    ally_id: string;
    routine_id: string;
    occurrence_id: string;
    run_id: string;
    main_conversation_id: string;
    run_conversation_id: string;
    cloud_binding_id: string;
    execution_id: string;
    attempt_id: string;
    approval_request_id: string;
    action_attempt_id: string;
  };
  common: { scope: FixtureScope };
  management: {
    create: { receipt: { schedule_generation: number } };
    update: { receipt: { schedule_generation: number } };
    pause: { receipt: { schedule_generation: number } };
    resume: { receipt: { schedule_generation: number } };
    delete: { request: unknown };
  };
  correlation: {
    required_dispatch: string[];
    required_dispatch_receipt: string[];
    required_event: string[];
  };
  dispatch: { command: FixtureMessage; receipt: FixtureMessage };
  result: { event: FixtureMessage };
  approval: { requested: FixtureMessage };
};

const ids = {
  workspace: rev9Fixture.identity.workspace_id,
  owner: rev9Fixture.identity.owner_user_id,
  ally: rev9Fixture.identity.ally_id,
  routine: rev9Fixture.identity.routine_id,
  occurrence: rev9Fixture.identity.occurrence_id,
  run: rev9Fixture.identity.run_id,
  mainConversation: rev9Fixture.identity.main_conversation_id,
  runConversation: rev9Fixture.identity.run_conversation_id,
  binding: rev9Fixture.identity.cloud_binding_id,
  execution: rev9Fixture.identity.execution_id,
  attempt: rev9Fixture.identity.attempt_id,
  approval: rev9Fixture.identity.approval_request_id,
  actionAttempt: rev9Fixture.identity.action_attempt_id,
};

const scope = rev9Fixture.common.scope;

const transport = {
  schema_version: rev9Fixture.dispatch.command.schema_version,
  issued_at: rev9Fixture.dispatch.command.issued_at,
  deadline_at: rev9Fixture.dispatch.command.deadline_at,
  fingerprint: rev9Fixture.dispatch.command.fingerprint,
};

const weeklySchedule = {
  kind: "recurring" as const,
  frequency: "weekly" as const,
  local_time: "09:00:00",
  days_of_week: [1, 3, 5],
  timezone: "Europe/Berlin",
};

function detail(prompt = "Check the synthetic item and report changed or unchanged.") {
  return {
    ...transport,
    kind: "routine.detail" as const,
    producer: "cloud" as const,
    service_identity: "cloud-service" as const,
    command_id: ids.approval,
    idempotency_key: ids.actionAttempt,
    routine_id: ids.routine,
    revision: 5,
    title: "Check availability",
    execution_prompt: prompt,
    schedule_state: "active" as const,
    responsible_ally_id: ids.ally,
    schedule: weeklySchedule,
    next_run_at: "2026-09-11T08:00:00Z",
    scope,
  };
}

function dispatchCommand() {
  return { ...rev9Fixture.dispatch.command };
}

function dispatchReceipt() {
  return { ...rev9Fixture.dispatch.receipt };
}

function resultEvent() {
  return { ...rev9Fixture.result.event };
}

function expectedRun() {
  return toRoutineRunProjection(dispatchCommand(), dispatchReceipt());
}

describe("routines contract boundary", () => {
  it("matches the owner-published revision 9 fixture", () => {
    const fixtureBytes = readFileSync(new URL("./fixtures/routines-v1.json", import.meta.url));
    const run = expectedRun();
    expect(createHash("sha256").update(fixtureBytes).digest("hex")).toBe("259577de2ea7e8343b266995767496d359aef196f1a19d6841e67ef133fb3343");
    expect(rev9Fixture.contract.content_revision).toBe(9);
    expect(rev9Fixture.result.event).toHaveProperty("title_snapshot", rev9Fixture.dispatch.command.title_snapshot);
    expect(rev9Fixture.management.create.receipt.schedule_generation).toBe(1);
    expect(rev9Fixture.management.update.receipt.schedule_generation).toBe(2);
    expect(rev9Fixture.management.pause.receipt.schedule_generation).toBe(3);
    expect(rev9Fixture.management.resume.receipt.schedule_generation).toBe(4);
    expect(toManagementReceipt(rev9Fixture.management.create.receipt).scheduleGeneration).toBe(1);
    expect(toManagementReceipt(rev9Fixture.management.update.receipt).scheduleGeneration).toBe(2);
    expect(toManagementReceipt(rev9Fixture.management.pause.receipt).scheduleGeneration).toBe(3);
    expect(toManagementReceipt(rev9Fixture.management.resume.receipt).scheduleGeneration).toBe(4);
    expect(rev9Fixture.correlation.required_dispatch).not.toContain("execution_id");
    expect(rev9Fixture.correlation.required_dispatch_receipt).toEqual(["execution_id", "attempt_id", "generation"]);
    expect(rev9Fixture.correlation.required_event).toEqual(["event_id", "event_sequence", "attempt_id", "generation"]);
    expect(routineManagementRequestSchema.parse(rev9Fixture.management.delete.request)).toHaveProperty("confirmation_ref");
    expect(routineDispatchCommandSchema.parse(rev9Fixture.dispatch.command).occurrence_disposition).toBe("admitted");
    expect(toRoutineRunProjection(rev9Fixture.dispatch.command, rev9Fixture.dispatch.receipt).occurrenceDisposition).toBe("admitted");
    expect(run.scheduleGeneration).toBe(4);
    expect(toRoutineResultProjection(rev9Fixture.result.event, run)).toMatchObject({
      outcome: "unchanged",
      titleSnapshot: rev9Fixture.dispatch.command.title_snapshot,
    });
    expect(toRoutineApprovalProjection(rev9Fixture.approval.requested).generation).toBe(7);
  });

  it("projects full routine detail and preserves the complete prompt", () => {
    const prompt = "Check the item, including the full evidence and all unchanged details.";
    expect(toRoutineDetail(detail(prompt))).toEqual(expect.objectContaining({
      routineId: ids.routine,
      executionPrompt: prompt,
      schedule: expect.objectContaining({ frequency: "weekly", daysOfWeek: [1, 3, 5] }),
    }));
  });

  it("rejects uppercase UUID aliases at every privileged event boundary", () => {
    const uppercaseUuid = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA";

    expect(routineResultEventSchema.safeParse({ ...resultEvent(), routine_id: uppercaseUuid }).success).toBe(false);
    expect(routineDispatchCommandSchema.safeParse({ ...dispatchCommand(), routine_id: uppercaseUuid }).success).toBe(false);
    expect(routineDispatchReceiptSchema.safeParse({ ...dispatchReceipt(), execution_id: uppercaseUuid }).success).toBe(false);
    expect(routineApprovalRequestedSchema.safeParse({
      ...rev9Fixture.approval.requested,
      approval_request_id: uppercaseUuid,
    }).success).toBe(false);
  });

  it("rejects unknown fields at every closed typed boundary", () => {
    expect(routineDetailResponseSchema.safeParse({ ...detail(), extra: true }).success).toBe(false);
    expect(routineDetailResponseSchema.safeParse({
      ...detail(),
      schedule: { ...weeklySchedule, extra: true },
    }).success).toBe(false);
    expect(routineManagementRequestSchema.safeParse({
      ...transport,
      kind: "routine.manage",
      producer: "cloud",
      service_identity: "cloud-service",
      operation: "create",
      command_id: ids.approval,
      idempotency_key: ids.actionAttempt,
      scope,
    body: {
        title: "Check availability",
        execution_prompt: "Check the item.",
        schedule: weeklySchedule,
        unsupported: "must reject",
      },
    }).success).toBe(false);

    expect(routineManagementRequestSchema.safeParse({
      ...transport,
      kind: "routine.manage",
      producer: "cloud",
      service_identity: "cloud-service",
      operation: "delete",
      command_id: ids.approval,
      idempotency_key: ids.actionAttempt,
      routine_id: ids.routine,
      expected_revision: 4,
      confirmation_ref: "opaque-confirmation-reference:not-a-uuid",
      scope,
    }).success).toBe(true);
  });

  it("enforces schedule grammar, IANA timezones, and UTF-8 prompt bounds", () => {
    expect(routineScheduleSchema.safeParse({
      kind: "recurring",
      frequency: "weekly",
      local_time: "09:00:00",
      days_of_week: [3, 1],
      timezone: "Europe/Berlin",
    }).success).toBe(false);
    expect(routineScheduleSchema.safeParse({
      kind: "once",
      local_at: "2026-02-30T09:00:00",
      timezone: "Europe/Berlin",
    }).success).toBe(false);
    expect(routineScheduleSchema.safeParse({
      kind: "recurring",
      frequency: "daily",
      local_time: "09:00:00",
      timezone: "Mars/Olympus",
    }).success).toBe(false);

    const exactLimitPrompt = "🙂".repeat(4_096);
    expect(toRoutineDetail(detail(exactLimitPrompt)).executionPrompt).toBe(exactLimitPrompt);
    expect(routineDetailResponseSchema.safeParse(detail(`${exactLimitPrompt}x`)).success).toBe(false);
  });

  it("keeps wire transport route-neutral while projecting run and result state", () => {
    const run = toRoutineRunProjection(dispatchCommand(), dispatchReceipt());
    expect(run).toEqual(expect.objectContaining({
      routineId: ids.routine,
      status: "working",
      acceptanceIsCompletion: false,
      executionId: ids.execution,
      occurrenceDisposition: "admitted",
    }));

    const result = toRoutineResultProjection(resultEvent(), run);
    expect(result).toEqual(expect.objectContaining({
      routineId: ids.routine,
      status: "succeeded",
      outcome: "unchanged",
      titleSnapshot: "Check availability later",
      text: "The synthetic item is unchanged.",
    }));
    expect(routineResultEventSchema.safeParse({ ...resultEvent(), title_snapshot: undefined }).success).toBe(false);
    expect(routineResultEventSchema.safeParse({ ...resultEvent(), action_digest: "secret" }).success).toBe(false);
    expect(routineDispatchCommandSchema.safeParse({ ...dispatchCommand(), occurrence_disposition: undefined }).success).toBe(false);
  });

  it("requires result events to match the trusted dispatch/run correlation", () => {
    const run = expectedRun();
    const mismatches: Array<[string, unknown]> = [
      ["routine_id", ids.owner],
      ["routine_revision", run.routineRevision + 1],
      ["title_snapshot", "A different accepted title"],
      ["occurrence_id", ids.owner],
      ["run_id", ids.owner],
      ["main_conversation_id", ids.owner],
      ["run_conversation_id", ids.owner],
      ["execution_id", ids.owner],
      ["attempt_id", ids.owner],
      ["generation", run.generation + 1],
      ["scope", { ...scope, owner_user_id: ids.ally }],
    ];

    for (const [field, value] of mismatches) {
      expect(() => toRoutineResultProjection({ ...resultEvent(), [field]: value }, run)).toThrow(
        "routine result does not match expected dispatch/run correlation",
      );
    }
  });

  it("rejects a dispatch receipt when any scope identity differs", () => {
    const mismatchedScopes = [
      { ...scope, workspace_id: ids.owner },
      { ...scope, owner_user_id: ids.ally },
      { ...scope, ally_id: ids.routine },
      { ...scope, cloud_binding_id: ids.execution },
    ];

    for (const mismatchedScope of mismatchedScopes) {
      expect(() => toRoutineRunProjection(dispatchCommand(), {
        ...dispatchReceipt(),
        scope: mismatchedScope,
      })).toThrow("routine dispatch and receipt scopes do not match");
    }
  });

  it("enforces the released UTF-8 event envelope limit", () => {
    const oversized = {
      ...resultEvent(),
      references: Array.from({ length: 32 }, (_, index) => ({
        label: `reference-${index}-${"r".repeat(240)}`,
        url: `https://example.test/${"a".repeat(2_000)}${index}`,
      })),
    };

    expect(new TextEncoder().encode(JSON.stringify(oversized)).length).toBeGreaterThan(MAX_ROUTINE_EVENT_BYTES);
    expect(routineResultEventSchema.safeParse(oversized).success).toBe(false);
  });

  it("requires pairwise-distinct main, run, and execution identities", () => {
    expect(routineResultEventSchema.safeParse({ ...resultEvent(), execution_id: ids.mainConversation }).success).toBe(false);
    expect(routineResultEventSchema.safeParse({ ...resultEvent(), execution_id: ids.runConversation }).success).toBe(false);
    expect(routineResultEventSchema.safeParse({ ...resultEvent(), run_conversation_id: ids.mainConversation }).success).toBe(false);

    expect(() => toRoutineRunProjection(dispatchCommand(), {
      ...dispatchReceipt(),
      execution_id: ids.mainConversation,
    })).toThrow("routine dispatch conversations and execution identity must differ");
    expect(() => toRoutineRunProjection(dispatchCommand(), {
      ...dispatchReceipt(),
      execution_id: ids.runConversation,
    })).toThrow("routine dispatch conversations and execution identity must differ");
  });

  it("projects approval identity without exposing provider credentials or action digests", () => {
    const requested = { ...rev9Fixture.approval.requested };
    const projection = toRoutineApprovalProjection(requested);
    expect(projection).not.toHaveProperty("actionDigest");
    expect(projection).not.toHaveProperty("providerIdempotencyKey");
    expect(projection.status).toBe("pending");
    expect(routineApprovalRequestedSchema.safeParse({ ...requested, expires_at: requested.created_at }).success).toBe(false);
  });

  it("maps durable management receipts and keeps insertion pending truthful", () => {
    const receipt = toManagementReceipt({
      ...transport,
      kind: "routine.management_receipt",
      producer: "cloud",
      service_identity: "cloud-service",
      command_id: ids.approval,
      idempotency_key: ids.actionAttempt,
      outcome: "saved",
      result_code: "ROUTINE_RESUMED",
      operation: "resume",
      routine_id: ids.routine,
      revision: 4,
      schedule_generation: 2,
      schedule_state: "active",
      resume_effective_at: "2026-09-10T07:30:00Z",
      next_run_at: "2026-09-11T08:00:00Z",
      scope,
    });
    expect(receipt).toEqual(expect.objectContaining({ resultCode: "ROUTINE_RESUMED", scheduleGeneration: 2 }));

    expect(routineEventReceiptSchema.parse({
      ...transport,
      kind: "routine.event_receipt",
      producer: "cloud",
      service_identity: "cloud-service",
      event_id: ids.approval,
      disposition: "applied",
      event_sequence: 3,
      result_insertion: "pending",
      insertion_watermark: null,
      scope,
    }).result_insertion).toBe("pending");
    expect(routineEventReceiptSchema.safeParse({
      ...transport,
      kind: "routine.event_receipt",
      producer: "cloud",
      service_identity: "cloud-service",
      event_id: ids.approval,
      disposition: "applied",
      event_sequence: 3,
      result_insertion: "pending",
      insertion_watermark: 3,
      scope,
    }).success).toBe(false);
    expect(() => toManagementReceipt({
      ...transport,
      kind: "routine.management_receipt",
      producer: "cloud",
      service_identity: "cloud-service",
      command_id: ids.approval,
      idempotency_key: ids.actionAttempt,
      outcome: "saved",
      result_code: "MANAGEMENT_SAVED",
      operation: "resume",
      routine_id: ids.routine,
      revision: 4,
      schedule_state: "active",
      next_run_at: "2026-09-11T08:00:00Z",
      scope,
    })).toThrow();
  });

  it("normalizes only released stable error codes", () => {
    expect(normalizeRoutineErrorCode("REVISION_CONFLICT")).toBe("REVISION_CONFLICT");
    expect(normalizeRoutineErrorCode("CONFIRMATION_REQUIRED")).toBe("CONFIRMATION_REQUIRED");
    expect(normalizeRoutineErrorCode("future-code")).toBe("UNKNOWN");
  });
});
