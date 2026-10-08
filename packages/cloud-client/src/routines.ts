import { z } from "zod";

const MAX_ROUTINE_TEXT_BYTES = 16 * 1024;
const MAX_ROUTINE_EVENT_BYTES = 64 * 1024;
const MAX_ROUTINE_SEQUENCE = 100_000;
const MAX_ROUTINE_TERMINAL_SEQUENCE = 100_001;
const MAX_ROUTINE_REFERENCE_COUNT = 32;
const FINGERPRINT_PATTERN = /^canonical-json-sha256:v1:[0-9a-f]{64}$/;
const UTC_SECOND_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const LOCAL_DATE_TIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/;
const LOCAL_TIME_PATTERN = /^\d{2}:\d{2}:\d{2}$/;

export const canonicalRoutineUuidSchema = z.uuid().refine(
  (value) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(value),
  "UUID must use canonical lowercase hyphenated serialization",
);
const uuidSchema = canonicalRoutineUuidSchema;
const opaqueConfirmationRefSchema = z.string().min(1);

function isValidUtcSecond(value: string): boolean {
  if (!UTC_SECOND_PATTERN.test(value)) return false;
  const parsed = new Date(value);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().replace(".000Z", "Z") === value;
}

function isValidLocalDateTime(value: string): boolean {
  if (!LOCAL_DATE_TIME_PATTERN.test(value)) return false;
  const parsed = new Date(`${value}Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().replace(".000Z", "Z").slice(0, 19) === value;
}

function isValidLocalTime(value: string): boolean {
  if (!LOCAL_TIME_PATTERN.test(value)) return false;
  const parsed = new Date(`1970-01-01T${value}Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().replace(".000Z", "Z").slice(11, 19) === value;
}

export function isRoutineTimezone(value: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: value }).format();
    return true;
  } catch {
    return false;
  }
}

const utcSecondSchema = z.string().refine(isValidUtcSecond, "expected a UTC second timestamp");
const localDateTimeSchema = z.string().refine(isValidLocalDateTime, "expected a local second timestamp");
const localTimeSchema = z.string().refine(isValidLocalTime, "expected a local time");
const timezoneSchema = z.string().min(1).max(128).refine(isRoutineTimezone, "expected an IANA timezone");
const titleSchema = z.string().min(1).max(120).refine((value) => !value.includes("\u0000"), "title contains a NUL character");
const boundedTextSchema = z.string().min(1).refine(
  (value) => !value.includes("\u0000") && new TextEncoder().encode(value).length <= MAX_ROUTINE_TEXT_BYTES,
  "text must be non-empty, NUL-free, and at most 16 KiB in UTF-8",
);

function isWithinRoutineEventEnvelope(value: unknown): boolean {
  const serialized = JSON.stringify(value);
  return serialized !== undefined && new TextEncoder().encode(serialized).length <= MAX_ROUTINE_EVENT_BYTES;
}

const fingerprintSchema = z.string().regex(FINGERPRINT_PATTERN);
const transportIdentitySchema = {
  schema_version: z.literal("v1"),
  issued_at: utcSecondSchema,
  deadline_at: utcSecondSchema,
  fingerprint: fingerprintSchema,
};

function hasValidTransportWindow(value: { issued_at: string; deadline_at: string }): boolean {
  const lifetime = Date.parse(value.deadline_at) - Date.parse(value.issued_at);
  return lifetime > 0 && lifetime <= 60_000;
}

function haveDistinctRoutineIdentities(mainConversationId: string, runConversationId: string, executionId: string): boolean {
  return new Set([mainConversationId, runConversationId, executionId]).size === 3;
}

const scheduleStateSchema = z.enum(["active", "paused", "deleted", "exhausted"]);
const scheduleKindSchema = z.enum(["once", "recurring"]);
const frequencySchema = z.enum(["daily", "weekly", "monthly", "interval"]);
const occurrenceDispositionSchema = z.enum([
  "admitted",
  "replay",
  "skipped_active",
  "delayed",
  "recovered",
  "cancelled",
]);
const runOutcomeSchema = z.enum([
  "queued",
  "working",
  "approval_waiting",
  "succeeded",
  "failed",
  "cancelled",
  "expired",
]);
const resultOutcomeSchema = z.enum(["changed", "unchanged", "failed"]);
const approvalDecisionSchema = z.enum(["approve", "reject"]);
const actionAttemptStateSchema = z.enum([
  "pre_dispatch",
  "dispatching",
  "completed",
  "unknown",
  "manual_reconciliation",
]);

export const routineScopeSchema = z.object({
  kind: z.literal("workspace"),
  workspace_id: uuidSchema,
  owner_user_id: uuidSchema,
  ally_id: uuidSchema,
  cloud_binding_id: uuidSchema,
}).strict();

export type RoutineScope = z.infer<typeof routineScopeSchema>;

const onceScheduleSchema = z.object({
  kind: z.literal("once"),
  local_at: localDateTimeSchema,
  timezone: timezoneSchema,
}).strict();

const dailyScheduleSchema = z.object({
  kind: z.literal("recurring"),
  frequency: z.literal("daily"),
  local_time: localTimeSchema,
  timezone: timezoneSchema,
}).strict();

const weeklyScheduleSchema = z.object({
  kind: z.literal("recurring"),
  frequency: z.literal("weekly"),
  local_time: localTimeSchema,
  days_of_week: z.array(z.number().int().min(1).max(7)).min(1).max(7)
    .refine((days) => days.every((day, index) => index === 0 || days[index - 1]! < day), "weekdays must be ascending and unique"),
  timezone: timezoneSchema,
}).strict();

const monthlyScheduleSchema = z.object({
  kind: z.literal("recurring"),
  frequency: z.literal("monthly"),
  local_time: localTimeSchema,
  day_of_month: z.number().int().min(1).max(31),
  timezone: timezoneSchema,
}).strict();

const intervalScheduleSchema = z.object({
  kind: z.literal("recurring"),
  frequency: z.literal("interval"),
  every_minutes: z.number().int().min(15).max(525_600),
  starts_at: localDateTimeSchema,
  timezone: timezoneSchema,
}).strict();

export const routineScheduleSchema = z.union([
  onceScheduleSchema,
  dailyScheduleSchema,
  weeklyScheduleSchema,
  monthlyScheduleSchema,
  intervalScheduleSchema,
]);

export type RoutineSchedule = z.infer<typeof routineScheduleSchema>;

const routineCreateBodySchema = z.object({
  title: titleSchema,
  execution_prompt: boundedTextSchema,
  schedule: routineScheduleSchema,
}).strict();

const routineUpdateBodySchema = z.object({
  title: titleSchema.optional(),
  execution_prompt: boundedTextSchema.optional(),
  schedule: routineScheduleSchema.optional(),
}).strict().refine(
  (value) => Object.values(value).some((entry) => entry !== undefined),
  "update must include at least one changed field",
);

const routineManageBase = {
  ...transportIdentitySchema,
  kind: z.literal("routine.manage"),
  producer: z.literal("cloud"),
  service_identity: z.literal("cloud-service"),
  command_id: uuidSchema,
  idempotency_key: uuidSchema,
  scope: routineScopeSchema,
};

const routineCreateRequestSchema = z.object({
  ...routineManageBase,
  operation: z.literal("create"),
  body: routineCreateBodySchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

const routineUpdateRequestSchema = z.object({
  ...routineManageBase,
  operation: z.literal("update"),
  routine_id: uuidSchema,
  expected_revision: z.number().int().min(1),
  body: routineUpdateBodySchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

const routinePauseResumeRequestSchema = z.object({
  ...routineManageBase,
  operation: z.enum(["pause", "resume"]),
  routine_id: uuidSchema,
  expected_revision: z.number().int().min(1),
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

const routineDeleteRequestSchema = z.object({
  ...routineManageBase,
  operation: z.literal("delete"),
  routine_id: uuidSchema,
  expected_revision: z.number().int().min(1),
  confirmation_ref: opaqueConfirmationRefSchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

const routineGetRequestSchema = z.object({
  ...routineManageBase,
  operation: z.literal("get"),
  routine_id: uuidSchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

const routineListRequestSchema = z.object({
  ...routineManageBase,
  operation: z.literal("list"),
  limit: z.number().int().min(1).max(100),
  cursor: z.string().min(1).max(512).nullable(),
  ally_id: uuidSchema.optional(),
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

export const routineManagementRequestSchema = z.union([
  routineCreateRequestSchema,
  routineUpdateRequestSchema,
  routinePauseResumeRequestSchema,
  routineDeleteRequestSchema,
  routineGetRequestSchema,
  routineListRequestSchema,
]);

export type RoutineManagementRequest = z.infer<typeof routineManagementRequestSchema>;

const managementReceiptResultCodeSchema = z.enum(["MANAGEMENT_SAVED", "ROUTINE_RESUMED"]);
const managementMutationSchema = z.enum(["create", "update", "pause", "resume", "delete"]);
const managementReceiptShape = {
  ...transportIdentitySchema,
  kind: z.literal("routine.management_receipt"),
  producer: z.literal("cloud"),
  service_identity: z.literal("cloud-service"),
  command_id: uuidSchema,
  idempotency_key: uuidSchema,
  outcome: z.literal("saved"),
  result_code: managementReceiptResultCodeSchema,
  operation: managementMutationSchema,
  routine_id: uuidSchema,
  revision: z.number().int().min(1),
  schedule_state: scheduleStateSchema,
  next_run_at: utcSecondSchema.nullable(),
  schedule_generation: z.number().int().min(1).optional(),
  resume_effective_at: utcSecondSchema.optional(),
  scope: routineScopeSchema,
};

export const managementReceiptSchema = z.object(managementReceiptShape)
  .strict()
  .refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time")
  .refine((value) => value.operation === "resume" ? value.result_code === "ROUTINE_RESUMED" : value.result_code === "MANAGEMENT_SAVED", {
    path: ["result_code"],
    message: "management receipt result code does not match its operation",
  });

export type ManagementReceiptWire = z.infer<typeof managementReceiptSchema>;

const routineDetailResponseShape = {
  ...transportIdentitySchema,
  kind: z.literal("routine.detail"),
  producer: z.literal("cloud"),
  service_identity: z.literal("cloud-service"),
  command_id: uuidSchema,
  idempotency_key: uuidSchema,
  routine_id: uuidSchema,
  revision: z.number().int().min(1),
  title: titleSchema,
  execution_prompt: boundedTextSchema,
  schedule_state: scheduleStateSchema,
  responsible_ally_id: uuidSchema,
  schedule: routineScheduleSchema,
  next_run_at: utcSecondSchema.nullable(),
  scope: routineScopeSchema,
};

export const routineDetailResponseSchema = z.object(routineDetailResponseShape)
  .strict()
  .refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

const routineSummaryWireSchema = z.object({
  routine_id: uuidSchema,
  revision: z.number().int().min(1),
  title: titleSchema,
  schedule_state: scheduleStateSchema,
  responsible_ally_id: uuidSchema,
  schedule: routineScheduleSchema,
  next_run_at: utcSecondSchema.nullable(),
}).strict();

export const routinePageResponseSchema = z.object({
  ...transportIdentitySchema,
  kind: z.literal("routine.page"),
  producer: z.literal("cloud"),
  service_identity: z.literal("cloud-service"),
  command_id: uuidSchema,
  idempotency_key: uuidSchema,
  items: z.array(routineSummaryWireSchema).max(100),
  next_cursor: z.string().min(1).max(512).nullable(),
  scope: routineScopeSchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

export type RoutineDetailWire = z.infer<typeof routineDetailResponseSchema>;
export type RoutinePageWire = z.infer<typeof routinePageResponseSchema>;

const routineDispatchCommandShape = {
  ...transportIdentitySchema,
  kind: z.literal("routine.dispatch"),
  producer: z.literal("cloud"),
  service_identity: z.literal("cloud-service"),
  command_id: uuidSchema,
  idempotency_key: uuidSchema,
  routine_id: uuidSchema,
  routine_revision: z.number().int().min(1),
  schedule_generation: z.number().int().min(1),
  occurrence_id: uuidSchema,
  run_id: uuidSchema,
  scheduled_at: utcSecondSchema,
  delayed: z.boolean(),
  occurrence_disposition: occurrenceDispositionSchema,
  main_conversation_id: uuidSchema,
  run_conversation_id: uuidSchema,
  cloud_binding_id: uuidSchema,
  execution_prompt: boundedTextSchema,
  title_snapshot: titleSchema,
  scope: routineScopeSchema,
};

export const routineDispatchCommandSchema = z.object(routineDispatchCommandShape)
  .strict()
  .refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time")
  .refine((value) => value.cloud_binding_id === value.scope.cloud_binding_id, {
    path: ["cloud_binding_id"],
    message: "dispatch binding must match scope",
  })
  .refine((value) => value.main_conversation_id !== value.run_conversation_id, {
    path: ["run_conversation_id"],
    message: "main and run conversations must differ",
  });

export const routineDispatchReceiptSchema = z.object({
  ...transportIdentitySchema,
  kind: z.literal("routine.dispatch_receipt"),
  producer: z.literal("foundry"),
  service_identity: z.literal("foundry-runtime"),
  command_id: uuidSchema,
  idempotency_key: uuidSchema,
  outcome: z.enum(["accepted", "duplicate"]),
  occurrence_id: uuidSchema,
  run_id: uuidSchema,
  execution_id: uuidSchema,
  attempt_id: uuidSchema,
  generation: z.number().int().min(0),
  acceptance_is_completion: z.literal(false),
  scope: routineScopeSchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

const routineReferenceSchema = z.object({
  label: z.string().min(1).max(255).refine((value) => !value.includes("\u0000")),
  url: z.string().min(1).max(2048).refine((value) => {
    try {
      const url = new URL(value);
      return (url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password;
    } catch {
      return false;
    }
  }, "reference URL must use http(s) without credentials"),
}).strict();

export const routineResultEventSchema = z.object({
  ...transportIdentitySchema,
  kind: z.literal("routine.result"),
  producer: z.literal("foundry"),
  service_identity: z.literal("foundry-runtime"),
  event_id: uuidSchema,
  event_sequence: z.number().int().min(1).max(MAX_ROUTINE_TERMINAL_SEQUENCE),
  routine_id: uuidSchema,
  occurrence_id: uuidSchema,
  run_id: uuidSchema,
  routine_revision: z.number().int().min(1),
  title_snapshot: titleSchema,
  execution_id: uuidSchema,
  attempt_id: uuidSchema,
  generation: z.number().int().min(0),
  main_conversation_id: uuidSchema,
  run_conversation_id: uuidSchema,
  outcome: resultOutcomeSchema,
  text: boundedTextSchema,
  references: z.array(routineReferenceSchema).max(MAX_ROUTINE_REFERENCE_COUNT),
  delayed: z.boolean(),
  scope: routineScopeSchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time")
  .refine(isWithinRoutineEventEnvelope, "event envelope must be at most 64 KiB in UTF-8")
  .refine((value) => haveDistinctRoutineIdentities(value.main_conversation_id, value.run_conversation_id, value.execution_id), {
    path: ["execution_id"],
    message: "main conversation, run conversation, and execution identities must differ",
  });

export const routineEventReceiptSchema = z.object({
  ...transportIdentitySchema,
  kind: z.literal("routine.event_receipt"),
  producer: z.literal("cloud"),
  service_identity: z.literal("cloud-service"),
  event_id: uuidSchema,
  disposition: z.enum(["applied", "duplicate"]),
  event_sequence: z.number().int().min(1).max(MAX_ROUTINE_TERMINAL_SEQUENCE),
  result_insertion: z.enum(["pending", "inserted"]),
  insertion_watermark: z.number().int().min(1).nullable(),
  scope: routineScopeSchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time")
  .refine((value) => value.result_insertion === "pending" ? value.insertion_watermark === null : value.insertion_watermark !== null, {
    path: ["insertion_watermark"],
    message: "pending insertion must not carry a watermark; inserted results must",
  });

export const routineApprovalRequestedSchema = z.object({
  ...transportIdentitySchema,
  kind: z.literal("routine.approval_requested"),
  producer: z.literal("foundry"),
  service_identity: z.literal("foundry-runtime"),
  event_id: uuidSchema,
  event_sequence: z.number().int().min(1).max(MAX_ROUTINE_SEQUENCE),
  approval_request_id: uuidSchema,
  action_attempt_id: uuidSchema,
  run_id: uuidSchema,
  execution_id: uuidSchema,
  attempt_id: uuidSchema,
  generation: z.number().int().min(0),
  status: z.literal("pending"),
  created_at: utcSecondSchema,
  expires_at: utcSecondSchema,
  action_digest: z.string().regex(/^[0-9a-f]{64}$/),
  provider_idempotency_key: z.string().min(1).max(255),
  scope: routineScopeSchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time")
  .refine(isWithinRoutineEventEnvelope, "event envelope must be at most 64 KiB in UTF-8")
  .refine((value) => Date.parse(value.expires_at) > Date.parse(value.created_at), {
    path: ["expires_at"],
    message: "approval expiry must be after creation",
  });

export const routineApprovalDecisionSchema = z.object({
  ...transportIdentitySchema,
  kind: z.literal("routine.approval_decision"),
  producer: z.literal("cloud"),
  service_identity: z.literal("cloud-service"),
  command_id: uuidSchema,
  idempotency_key: uuidSchema,
  approval_request_id: uuidSchema,
  action_attempt_id: uuidSchema,
  run_id: uuidSchema,
  attempt_id: uuidSchema,
  generation: z.number().int().min(0),
  decision: approvalDecisionSchema,
  decided_at: utcSecondSchema,
  scope: routineScopeSchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

const approvalRequestStatusSchema = z.enum(["authorizing", "rejected", "expired", "cancelled", "pending"]);
const approvalRunStatusSchema = z.enum(["working", "approval_waiting", "failed", "cancelled", "expired"]);

export const routineApprovalReceiptSchema = z.object({
  ...transportIdentitySchema,
  kind: z.literal("routine.approval_receipt"),
  producer: z.literal("foundry"),
  service_identity: z.literal("foundry-runtime"),
  command_id: uuidSchema,
  idempotency_key: uuidSchema,
  result_code: z.string().min(1).max(64),
  request_status: approvalRequestStatusSchema,
  run_status: approvalRunStatusSchema,
  permission_consumed: z.boolean(),
  action_attempt_state: actionAttemptStateSchema,
  scope: routineScopeSchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

export const routineCancelWaitSchema = z.object({
  ...transportIdentitySchema,
  kind: z.literal("routine.cancel_wait"),
  producer: z.literal("cloud"),
  service_identity: z.literal("cloud-service"),
  command_id: uuidSchema,
  idempotency_key: uuidSchema,
  approval_request_id: uuidSchema,
  run_id: uuidSchema,
  attempt_id: uuidSchema,
  generation: z.number().int().min(0),
  reason: z.string().regex(/^[a-z][a-z0-9_-]{0,63}$/),
  replacing_occurrence_id: uuidSchema,
  scope: routineScopeSchema,
}).strict().refine(hasValidTransportWindow, "deadline must be within 60 seconds of issue time");

export const routineErrorCodeSchema = z.enum([
  "INVALID_INPUT",
  "NOT_FOUND",
  "REVISION_CONFLICT",
  "CONFIRMATION_REQUIRED",
  "CONFIRMATION_STALE",
  "CONFIRMATION_REPLAYED",
  "CONFIRMATION_WRONG_CONVERSATION",
  "CONFIRMATION_WRONG_OWNER",
  "CONFIRMATION_WRONG_WORKSPACE",
  "CONFIRMATION_WRONG_ALLY",
  "CONFIRMATION_WRONG_BINDING",
  "CONFIRMATION_WRONG_ROUTINE",
  "MANAGEMENT_SAVED",
  "ROUTINE_DELETED",
  "ROUTINE_PAUSED",
  "PAUSE_UNSUPPORTED",
  "CANDIDATE_SUPERSEDED",
  "STALE_DUE_CANDIDATE",
  "NOT_DUE",
  "ROUTINE_RESUMED",
  "ROUTINE_ALREADY_ACTIVE",
  "OCCURRENCE_ADMITTED",
  "OCCURRENCE_REPLAY",
  "OCCURRENCE_SKIPPED_ACTIVE",
  "REPLACEMENT_PENDING",
  "APPROVAL_AUTHORIZED",
  "APPROVAL_REJECTED",
  "APPROVAL_EXPIRED",
  "APPROVAL_CANCELLED",
  "APPROVAL_ALREADY_AUTHORIZING",
  "STALE_GENERATION",
  "CORRELATION_MISMATCH",
  "IDEMPOTENCY_CONFLICT",
  "ACTION_OUTCOME_UNKNOWN",
  "ACTION_MANUAL_RECONCILIATION",
  "RESULT_INSERTED_ONCE",
]);

export type RoutineErrorCode = z.infer<typeof routineErrorCodeSchema>;
export type RoutineScheduleState = z.infer<typeof scheduleStateSchema>;
export type RoutineRunOutcome = z.infer<typeof runOutcomeSchema>;
export type RoutineResultOutcome = z.infer<typeof resultOutcomeSchema>;
export type RoutineActionAttemptState = z.infer<typeof actionAttemptStateSchema>;
export type RoutineOccurrenceDisposition = z.infer<typeof occurrenceDispositionSchema>;

export function normalizeRoutineErrorCode(value: unknown): RoutineErrorCode | "UNKNOWN" {
  const result = routineErrorCodeSchema.safeParse(value);
  return result.success ? result.data : "UNKNOWN";
}

export interface RoutineScheduleViewModel {
  kind: RoutineSchedule["kind"];
  frequency?: "daily" | "weekly" | "monthly" | "interval";
  localAt?: string;
  localTime?: string;
  daysOfWeek?: number[];
  dayOfMonth?: number;
  everyMinutes?: number;
  startsAt?: string;
  timezone: string;
}

export interface RoutineDetail {
  routineId: string;
  revision: number;
  title: string;
  executionPrompt: string;
  scheduleState: RoutineScheduleState;
  responsibleAllyId: string;
  schedule: RoutineScheduleViewModel;
  nextRunAt: string | null;
  scope: RoutineScope;
}

export interface RoutineSummary extends Omit<RoutineDetail, "executionPrompt"> {}

export interface RoutinePage {
  items: RoutineSummary[];
  nextCursor: string | null;
  scope: RoutineScope;
}

export interface ManagementReceipt {
  commandId: string;
  idempotencyKey: string;
  outcome: "saved";
  resultCode: "MANAGEMENT_SAVED" | "ROUTINE_RESUMED";
  operation: "create" | "update" | "pause" | "resume" | "delete";
  routineId: string;
  revision: number;
  scheduleState: RoutineScheduleState;
  nextRunAt: string | null;
  scheduleGeneration?: number;
  resumeEffectiveAt?: string;
  scope: RoutineScope;
}

export interface RoutineRunProjection {
  routineId: string;
  routineRevision: number;
  scheduleGeneration: number;
  occurrenceId: string;
  runId: string;
  executionId: string;
  attemptId: string;
  generation: number;
  scheduledAt: string;
  delayed: boolean;
  occurrenceDisposition: RoutineOccurrenceDisposition;
  mainConversationId: string;
  runConversationId: string;
  titleSnapshot: string;
  scope: RoutineScope;
  status: "working";
  acceptanceIsCompletion: false;
}

export interface RoutineResultProjection {
  eventId: string;
  eventSequence: number;
  routineId: string;
  occurrenceId: string;
  runId: string;
  routineRevision: number;
  titleSnapshot: string;
  executionId: string;
  attemptId: string;
  generation: number;
  mainConversationId: string;
  runConversationId: string;
  outcome: RoutineResultOutcome;
  status: Extract<RoutineRunOutcome, "succeeded" | "failed">;
  text: string;
  references: { label: string; url: string }[];
  delayed: boolean;
  scope: RoutineScope;
}

export interface RoutineApprovalProjection {
  eventId: string;
  eventSequence: number;
  approvalRequestId: string;
  actionAttemptId: string;
  runId: string;
  executionId: string;
  attemptId: string;
  generation: number;
  status: "pending";
  createdAt: string;
  expiresAt: string;
  scope: RoutineScope;
}

export interface RoutineApprovalReceipt {
  commandId: string;
  idempotencyKey: string;
  resultCode: string;
  requestStatus: z.infer<typeof approvalRequestStatusSchema>;
  runStatus: z.infer<typeof approvalRunStatusSchema>;
  permissionConsumed: boolean;
  actionAttemptState: RoutineActionAttemptState;
  scope: RoutineScope;
}

function toRoutineScheduleViewModel(schedule: RoutineSchedule): RoutineScheduleViewModel {
  if (schedule.kind === "once") {
    return { kind: "once", localAt: schedule.local_at, timezone: schedule.timezone };
  }
  if (schedule.frequency === "daily") {
    return { kind: "recurring", frequency: "daily", localTime: schedule.local_time, timezone: schedule.timezone };
  }
  if (schedule.frequency === "interval") {
    return {
      kind: "recurring",
      frequency: "interval",
      everyMinutes: schedule.every_minutes,
      startsAt: schedule.starts_at,
      timezone: schedule.timezone,
    };
  }
  if (schedule.frequency === "weekly") {
    return {
      kind: "recurring",
      frequency: "weekly",
      localTime: schedule.local_time,
      daysOfWeek: [...schedule.days_of_week],
      timezone: schedule.timezone,
    };
  }
  return {
    kind: "recurring",
    frequency: "monthly",
    localTime: schedule.local_time,
    dayOfMonth: schedule.day_of_month,
    timezone: schedule.timezone,
  };
}

export function toRoutineScope(input: unknown): RoutineScope {
  return routineScopeSchema.parse(input);
}

export function toRoutineSchedule(input: unknown): RoutineScheduleViewModel {
  return toRoutineScheduleViewModel(routineScheduleSchema.parse(input));
}

export function toRoutineDetail(input: unknown): RoutineDetail {
  const detail = routineDetailResponseSchema.parse(input);
  return {
    routineId: detail.routine_id,
    revision: detail.revision,
    title: detail.title,
    executionPrompt: detail.execution_prompt,
    scheduleState: detail.schedule_state,
    responsibleAllyId: detail.responsible_ally_id,
    schedule: toRoutineScheduleViewModel(detail.schedule),
    nextRunAt: detail.next_run_at,
    scope: detail.scope,
  };
}

export function toRoutinePage(input: unknown): RoutinePage {
  const page = routinePageResponseSchema.parse(input);
  return {
    items: page.items.map((item) => ({
      routineId: item.routine_id,
      revision: item.revision,
      title: item.title,
      scheduleState: item.schedule_state,
      responsibleAllyId: item.responsible_ally_id,
      schedule: toRoutineScheduleViewModel(item.schedule),
      nextRunAt: item.next_run_at,
      scope: page.scope,
    })),
    nextCursor: page.next_cursor,
    scope: page.scope,
  };
}

export function toManagementReceipt(input: unknown): ManagementReceipt {
  const receipt = managementReceiptSchema.parse(input);
  return {
    commandId: receipt.command_id,
    idempotencyKey: receipt.idempotency_key,
    outcome: receipt.outcome,
    resultCode: receipt.result_code,
    operation: receipt.operation,
    routineId: receipt.routine_id,
    revision: receipt.revision,
    scheduleState: receipt.schedule_state,
    nextRunAt: receipt.next_run_at,
    ...(receipt.schedule_generation === undefined ? {} : { scheduleGeneration: receipt.schedule_generation }),
    ...(receipt.resume_effective_at === undefined ? {} : { resumeEffectiveAt: receipt.resume_effective_at }),
    scope: receipt.scope,
  };
}

function routineScopesMatch(left: RoutineScope, right: RoutineScope): boolean {
  return left.kind === right.kind
    && left.workspace_id === right.workspace_id
    && left.owner_user_id === right.owner_user_id
    && left.ally_id === right.ally_id
    && left.cloud_binding_id === right.cloud_binding_id;
}

export function toRoutineRunProjection(commandInput: unknown, receiptInput: unknown): RoutineRunProjection {
  const command = routineDispatchCommandSchema.parse(commandInput);
  const receipt = routineDispatchReceiptSchema.parse(receiptInput);
  if (command.command_id !== receipt.command_id || command.idempotency_key !== receipt.idempotency_key) {
    throw new Error("routine dispatch and receipt identities do not match");
  }
  if (command.occurrence_id !== receipt.occurrence_id || command.run_id !== receipt.run_id) {
    throw new Error("routine dispatch and receipt run identities do not match");
  }
  if (!haveDistinctRoutineIdentities(command.main_conversation_id, command.run_conversation_id, receipt.execution_id)) {
    throw new Error("routine dispatch conversations and execution identity must differ");
  }
  if (!routineScopesMatch(command.scope, receipt.scope)) {
    throw new Error("routine dispatch and receipt scopes do not match");
  }
  return {
    routineId: command.routine_id,
    routineRevision: command.routine_revision,
    scheduleGeneration: command.schedule_generation,
    occurrenceId: command.occurrence_id,
    runId: command.run_id,
    executionId: receipt.execution_id,
    attemptId: receipt.attempt_id,
    generation: receipt.generation,
    scheduledAt: command.scheduled_at,
    delayed: command.delayed,
    occurrenceDisposition: command.occurrence_disposition,
    mainConversationId: command.main_conversation_id,
    runConversationId: command.run_conversation_id,
    titleSnapshot: command.title_snapshot,
    scope: command.scope,
    status: "working",
    acceptanceIsCompletion: false,
  };
}

export function toRoutineResultProjection(input: unknown, expectedRun: RoutineRunProjection): RoutineResultProjection {
  const result = routineResultEventSchema.parse(input);
  if (
    result.routine_id !== expectedRun.routineId
    || result.routine_revision !== expectedRun.routineRevision
    || result.title_snapshot !== expectedRun.titleSnapshot
    || result.occurrence_id !== expectedRun.occurrenceId
    || result.run_id !== expectedRun.runId
    || result.main_conversation_id !== expectedRun.mainConversationId
    || result.run_conversation_id !== expectedRun.runConversationId
    || result.execution_id !== expectedRun.executionId
    || result.attempt_id !== expectedRun.attemptId
    || result.generation !== expectedRun.generation
    || !routineScopesMatch(result.scope, expectedRun.scope)
  ) {
    throw new Error("routine result does not match expected dispatch/run correlation");
  }
  return {
    eventId: result.event_id,
    eventSequence: result.event_sequence,
    routineId: result.routine_id,
    occurrenceId: result.occurrence_id,
    runId: result.run_id,
    routineRevision: result.routine_revision,
    titleSnapshot: result.title_snapshot,
    executionId: result.execution_id,
    attemptId: result.attempt_id,
    generation: result.generation,
    mainConversationId: result.main_conversation_id,
    runConversationId: result.run_conversation_id,
    outcome: result.outcome,
    status: result.outcome === "failed" ? "failed" : "succeeded",
    text: result.text,
    references: result.references.map((reference) => ({ ...reference })),
    delayed: result.delayed,
    scope: result.scope,
  };
}

export function toRoutineApprovalProjection(input: unknown): RoutineApprovalProjection {
  const approval = routineApprovalRequestedSchema.parse(input);
  return {
    eventId: approval.event_id,
    eventSequence: approval.event_sequence,
    approvalRequestId: approval.approval_request_id,
    actionAttemptId: approval.action_attempt_id,
    runId: approval.run_id,
    executionId: approval.execution_id,
    attemptId: approval.attempt_id,
    generation: approval.generation,
    status: approval.status,
    createdAt: approval.created_at,
    expiresAt: approval.expires_at,
    scope: approval.scope,
  };
}

export function toRoutineApprovalReceipt(input: unknown): RoutineApprovalReceipt {
  const receipt = routineApprovalReceiptSchema.parse(input);
  return {
    commandId: receipt.command_id,
    idempotencyKey: receipt.idempotency_key,
    resultCode: receipt.result_code,
    requestStatus: receipt.request_status,
    runStatus: receipt.run_status,
    permissionConsumed: receipt.permission_consumed,
    actionAttemptState: receipt.action_attempt_state,
    scope: receipt.scope,
  };
}

export type RoutineDispatchCommand = z.infer<typeof routineDispatchCommandSchema>;
export type RoutineDispatchReceipt = z.infer<typeof routineDispatchReceiptSchema>;
export type RoutineResultEvent = z.infer<typeof routineResultEventSchema>;
export type RoutineEventReceipt = z.infer<typeof routineEventReceiptSchema>;
export type RoutineApprovalRequested = z.infer<typeof routineApprovalRequestedSchema>;
export type RoutineApprovalDecision = z.infer<typeof routineApprovalDecisionSchema>;
export type RoutineCancelWait = z.infer<typeof routineCancelWaitSchema>;
export type RoutineReference = z.infer<typeof routineReferenceSchema>;

export {
  MAX_ROUTINE_EVENT_BYTES,
  MAX_ROUTINE_REFERENCE_COUNT,
  MAX_ROUTINE_SEQUENCE,
  MAX_ROUTINE_TERMINAL_SEQUENCE,
  MAX_ROUTINE_TEXT_BYTES,
  actionAttemptStateSchema,
  approvalDecisionSchema,
  occurrenceDispositionSchema,
  resultOutcomeSchema,
  runOutcomeSchema,
  scheduleKindSchema,
  scheduleStateSchema,
  frequencySchema,
  managementReceiptResultCodeSchema,
};
