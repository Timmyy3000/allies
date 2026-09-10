import { z } from "zod";
import { messageFileSchema, preparationSchema, publicationSchema, type MessageFile, type FilePublication } from "../files";
import { activityApprovalSchema, toActivityApproval, type ActivityApproval } from "./approvals";
import {
  canonicalRoutineUuidSchema,
  routineScheduleSchema,
  toRoutineSchedule,
  type RoutineScheduleViewModel,
} from "../routines";

const uuidSchema = z.uuid();

const appearanceSchema = z
  .object({
    catalog_version: z.string().min(1).max(32),
    key: z.string().min(1).max(128),
  })
  .loose();

const provisioningStateSchema = z.enum([
  "bound",
  "pending",
  "retryable",
  "failed",
  "repair_required",
  "incompatible",
]);

const senderSchema = z.enum(["user", "assistant"]);
const messageStatusSchema = z.enum([
  "queued",
  "in_progress",
  "awaiting_action",
  "completed",
  "failed",
  "stopped",
]);
export const activityStateSchema = z.enum([
  "queued",
  "running",
  "awaiting_action",
  "completed",
  "stopped",
  "failed",
  "reconciliation_needed",
]);
export const activityKindSchema = z.enum([
  "execution",
  "assistant_delta",
  "activity_started",
  "activity_completed",
  "awaiting_action",
  "execution_completed",
  "execution_stopped",
  "execution_failed",
]);
const timestampSchema = z.iso.datetime({ offset: true });
const labelTextSchema = z.string()
  .refine((value) => !/[\p{Cc}\p{Cf}]/u.test(value), "Use a single-line label");
export const allyLabelSchema = labelTextSchema
  .refine((value) => [...value].length <= 80, "Use at most 80 characters")
  .refine(
  (value) => value === "" || /^\S+(?: \S+){1,2}$/u.test(value),
  "Use two or three words",
);

export const allyResponseSchema = z
  .object({
    id: uuidSchema,
    binding_id: uuidSchema,
    operation_id: uuidSchema,
    name: z.string().min(1).max(80),
    job: z.string().min(1).max(200),
    personality: z.string().min(1).max(4000),
    appearance: appearanceSchema,
    provisioning_state: provisioningStateSchema,
    retryable: z.boolean(),
    label: allyLabelSchema.default(""),
    show_label: z.boolean().default(false),
    settings_revision: z.number().int().nonnegative().default(0),
  })
  .loose();

export const allyListResponseSchema = z.object({ allies: z.array(allyResponseSchema) }).loose();

export const onboardingAttemptResponseSchema = z
  .object({
    attempt_token: z.string().min(32).max(256),
    greeting: z.string().min(1),
  })
  .loose();

export const messageResponseSchema = z
  .object({
    id: uuidSchema,
    sender: senderSchema,
    content: z.string(),
    sequence: z.number().int().positive(),
    status: messageStatusSchema,
    created_at: timestampSchema,
    retryable: z.boolean().default(false),
    queue_state: z.enum(["claimed", "unclaimed"]).nullable().optional(),
    deleted_at: timestampSchema.nullable().optional(),
    preparation: preparationSchema.optional(),
    revision: z.number().int().nonnegative().optional(),
    files: z.array(messageFileSchema).max(10).optional(),
  })
  .loose();

export const assistantReplyResponseSchema = z
  .object({
    id: uuidSchema,
    source_message_id: uuidSchema,
    conversation_turn_ordinal: z.number().int().positive(),
    content: z.string(),
    status: messageStatusSchema,
    has_full_prefix: z.boolean(),
    is_truncated: z.boolean().default(false),
    publications: z.array(publicationSchema).max(100).optional(),
    created_at: timestampSchema,
    updated_at: timestampSchema,
  })
  .loose();

const routineChatTitleSchema = z
  .string()
  .min(1)
  .max(120)
  .refine((value) => !value.includes("\u0000"), "routine title contains a NUL character");
const routineChatTextSchema = z
  .string()
  .min(1)
  .refine(
    (value) => !value.includes("\u0000") && new TextEncoder().encode(value).byteLength <= 16 * 1024,
    "routine text must be non-empty, NUL-free, and at most 16 KiB in UTF-8",
  );
const routineChatStatusSchema = z
  .string()
  .regex(/^[a-z][a-z0-9_-]{0,63}$/u, "routine status must be a bounded token");
const routineChatReferenceSchema = z
  .object({
    label: z.string().min(1).max(255).refine((value) => !value.includes("\u0000")),
    url: z.string().min(1).max(2048).refine((value) => {
      try {
        const url = new URL(value);
        return (url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password;
      } catch {
        return false;
      }
    }, "routine reference URL must use http(s) without credentials"),
  })
  .strict();

export const routineChatItemResponseSchema = z
  .object({
    id: canonicalRoutineUuidSchema,
    kind: z.enum(["created", "running", "result"]),
    routine_id: canonicalRoutineUuidSchema,
    conversation_id: canonicalRoutineUuidSchema,
    source_message_id: canonicalRoutineUuidSchema.nullish(),
    title_snapshot: routineChatTitleSchema,
    routine_revision: z.number().int().min(1).max(100_000_000),
    schedule_generation: z.number().int().min(1).max(100_000_000),
    status: routineChatStatusSchema,
    schedule: routineScheduleSchema,
    occurred_at: timestampSchema,
    occurrence_id: canonicalRoutineUuidSchema.nullish(),
    run_id: canonicalRoutineUuidSchema.nullish(),
    execution_id: canonicalRoutineUuidSchema.nullish(),
    attempt_id: canonicalRoutineUuidSchema.nullish(),
    generation: z.number().int().min(0).max(100_000).nullish(),
    result_id: canonicalRoutineUuidSchema.nullish(),
    result_insertion: z.enum(["pending", "inserted"]).nullish(),
    text: routineChatTextSchema.nullish(),
    references: z.array(routineChatReferenceSchema).max(32).default([]),
    delayed: z.boolean().nullish(),
    approval_id: canonicalRoutineUuidSchema.nullish(),
    approval_request_id: canonicalRoutineUuidSchema.nullish(),
    approval_status: routineChatStatusSchema.nullish(),
    approval_decision: z.enum(["approve", "reject"]).nullish(),
    action_digest: z.string().regex(/^[0-9a-f]{64}$/u).nullish(),
    action_attempt_id: canonicalRoutineUuidSchema.nullish(),
    approval_expires_at: timestampSchema.nullish(),
  })
  .loose()
  .superRefine((item, context) => {
    if (item.kind === "created") {
      if (item.id !== item.routine_id) {
        context.addIssue({ code: "custom", path: ["id"], message: "created routine item id must equal routine_id" });
      }
      if (item.run_id || item.result_id || item.occurrence_id) {
        context.addIssue({ code: "custom", path: ["run_id"], message: "created routine item cannot carry run identities" });
      }
      return;
    }
    if (item.kind === "running") {
      if (!item.run_id || item.id !== item.run_id) {
        context.addIssue({ code: "custom", path: ["run_id"], message: "running routine item id must equal run_id" });
      }
      if (item.result_id || item.result_insertion) {
        context.addIssue({ code: "custom", path: ["result_id"], message: "running routine item cannot carry result identity" });
      }
      return;
    }
    if (!item.result_id || item.id !== item.result_id) {
      context.addIssue({ code: "custom", path: ["result_id"], message: "result routine item id must equal result_id" });
    }
    if (!item.result_insertion) {
      context.addIssue({ code: "custom", path: ["result_insertion"], message: "result routine item must declare insertion state" });
    }
  });

export const conversationResponseSchema = z
  .object({
    id: uuidSchema,
    ally_id: uuidSchema,
    messages: z.array(messageResponseSchema),
    queue: z.array(messageResponseSchema).max(101).optional(),
    assistant_replies: z.array(assistantReplyResponseSchema).default([]),
    routine_items: z.array(routineChatItemResponseSchema).max(100).default([]),
    next_cursor: z.string().min(1).max(512).nullable().optional(),
  })
  .loose();

export const messageAcceptanceResponseSchema = z
  .object({
    conversation_id: uuidSchema,
    message: messageResponseSchema,
    execution: z.record(z.string(), z.unknown()).nullable().optional(),
    replayed: z.boolean(),
  })
  .loose();

const activityResponseSchema = z
  .object({
    id: uuidSchema,
    message_id: uuidSchema,
    sequence: z.number().int().positive(),
    conversation_turn_ordinal: z.number().int().positive(),
    kind: activityKindSchema,
    text: z.string(),
    state: activityStateSchema,
    created_at: timestampSchema,
    activity_attempt_id: z.string().regex(/^attempt-[0-9a-f]{32}$/).nullish(),
    activity_id: z.string().regex(/^activity-[0-9a-f]{32}$/).nullish(),
    activity_kind: z.string().regex(/^[a-z_]{1,32}$/).nullish(),
    outcome: z.enum(["completed", "failed", "stopped"]).nullish(),
    duration_ms: z.number().int().min(0).max(86_400_000).nullish(),
    approval: activityApprovalSchema.nullish(),
  })
  .loose();

export const activitySnapshotResponseSchema = z
  .object({
    conversation_id: uuidSchema,
    active_message_id: uuidSchema.nullable().optional(),
    activities: z.array(activityResponseSchema).max(200),
    state: activityStateSchema,
    last_contiguous_sequence: z.number().int().nonnegative(),
    last_contiguous_activity_sequence: z.number().int().nonnegative().optional(),
    resume_cursor: z.string().min(1).max(512).nullable().optional(),
    next_cursor: z.string().min(1).max(512).nullable().optional(),
    oldest_sequence: z.number().int().nonnegative().nullable().optional(),
    latest_sequence: z.number().int().nonnegative().nullable().optional(),
    retention_gap: z.boolean().optional(),
    assistant_reply: assistantReplyResponseSchema.nullable().optional(),
  })
  .loose();

export const allySeedInputSchema = z.object({
  name: z.string().min(1).max(80),
  job: z.string().min(1).max(200),
  personality: z.string().min(1).max(4000),
  appearanceCatalogVersion: z.string().min(1).max(32),
  appearanceKey: z.string().min(1).max(128),
});

export const createAllyInputSchema = allySeedInputSchema.extend({
  onboardingAttempt: z.string().min(32).max(256),
  reply: z.string().min(1).max(4000),
});

export const allySettingsInputSchema = z.object({
  label: labelTextSchema
    .transform((value) => value.trim().replace(/\s+/gu, " "))
    .pipe(allyLabelSchema),
  showLabel: z.boolean(),
  settingsRevision: z.number().int().nonnegative(),
}).strict().refine((value) => !value.showLabel || value.label !== "", {
  path: ["showLabel"], message: "Add a label before showing it",
});

export type AllySettingsInput = z.input<typeof allySettingsInputSchema>;

export type ProvisioningState = z.infer<typeof provisioningStateSchema>;
export type MessageSender = z.infer<typeof senderSchema>;
export type MessageStatus = z.infer<typeof messageStatusSchema>;
export type ActivityState = z.infer<typeof activityStateSchema>;
export type ActivityKind = z.infer<typeof activityKindSchema>;

export interface AllyAppearanceViewModel {
  catalogVersion: string;
  key: string;
}
export interface AllyViewModel {
  id: string;
  bindingId: string;
  operationId: string;
  name: string;
  job: string;
  personality: string;
  appearance: AllyAppearanceViewModel;
  provisioningState: ProvisioningState;
  retryable: boolean;
  label?: string;
  showLabel?: boolean;
  settingsRevision?: number;
}

export interface AllySeedInput {
  name: string;
  job: string;
  personality: string;
  appearanceCatalogVersion: string;
  appearanceKey: string;
}

export interface CreateAllyInput extends AllySeedInput {
  onboardingAttempt: string;
  reply: string;
}

export interface OnboardingAttemptViewModel {
  attemptToken: string;
  greeting: string;
}

export interface MessageViewModel {
  preparation?: z.infer<typeof preparationSchema>;
  revision?: number;
  files?: MessageFile[];
  id: string;
  sender: MessageSender;
  content: string;
  sequence: number;
  status: MessageStatus;
  createdAt: string;
  retryable?: boolean;
  queueState?: "claimed" | "unclaimed" | null;
  deletedAt?: string | null;
}

export interface AssistantReplyViewModel {
  publications?: FilePublication[];
  id: string;
  sourceMessageId: string;
  conversationTurnOrdinal: number;
  content: string;
  status: MessageStatus;
  hasFullPrefix: boolean;
  isTruncated?: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface ConversationViewModel {
  id: string;
  allyId: string;
  messages: MessageViewModel[];
  queue?: MessageViewModel[];
  assistantReplies: AssistantReplyViewModel[];
  routineItems: RoutineChatItemViewModel[];
  nextCursor: string | null;
}

export type RoutineChatItemKind = "created" | "running" | "result";

export interface RoutineChatReferenceViewModel {
  label: string;
  url: string;
}

export interface RoutineChatItemViewModel {
  id: string;
  kind: RoutineChatItemKind;
  routineId: string;
  conversationId: string;
  sourceMessageId?: string | null;
  titleSnapshot: string;
  routineRevision: number;
  scheduleGeneration: number;
  status: string;
  schedule: RoutineScheduleViewModel;
  occurredAt: string;
  occurrenceId: string | null;
  runId: string | null;
  executionId: string | null;
  attemptId: string | null;
  generation: number | null;
  resultId: string | null;
  resultInsertion: "pending" | "inserted" | null;
  text: string | null;
  references: RoutineChatReferenceViewModel[];
  delayed: boolean | null;
  approvalId: string | null;
  approvalRequestId: string | null;
  approvalStatus: string | null;
  approvalDecision: "approve" | "reject" | null;
  actionDigest: string | null;
  actionAttemptId: string | null;
  approvalExpiresAt: string | null;
}

export interface MessageAcceptanceViewModel {
  conversationId: string;
  message: MessageViewModel;
  execution: Record<string, unknown> | null;
  replayed: boolean;
}

export interface ActivityViewModel {
  id: string;
  messageId: string;
  sequence: number;
  conversationTurnOrdinal: number;
  kind: ActivityKind;
  text: string;
  state: ActivityState;
  createdAt: string;
  activityAttemptId?: string | null;
  activityId?: string | null;
  activityKind?: string | null;
  outcome?: "completed" | "failed" | "stopped" | null;
  durationMs?: number | null;
  approval?: ActivityApproval | null;
}

export interface ActivitySnapshotViewModel {
  conversationId: string;
  activeMessageId?: string | null;
  activities: ActivityViewModel[];
  state: ActivityState;
  lastContiguousSequence: number;
  lastContiguousActivitySequence?: number;
  resumeCursor?: string | null;
  nextCursor?: string | null;
  oldestSequence?: number | null;
  latestSequence?: number | null;
  retentionGap?: boolean;
  assistantReply?: AssistantReplyViewModel | null;
}

export function toAllyViewModel(input: unknown): AllyViewModel {
  const ally = allyResponseSchema.parse(input);
  return {
    id: ally.id,
    bindingId: ally.binding_id,
    operationId: ally.operation_id,
    name: ally.name,
    job: ally.job,
    personality: ally.personality,
    appearance: {
      catalogVersion: ally.appearance.catalog_version,
      key: ally.appearance.key,
    },
    provisioningState: ally.provisioning_state,
    retryable: ally.retryable,
    label: ally.label,
    showLabel: ally.show_label,
    settingsRevision: ally.settings_revision,
  };
}

export function toAllyListViewModel(input: unknown): AllyViewModel[] {
  return allyListResponseSchema.parse(input).allies.map(toAllyViewModel);
}

export function toOnboardingAttemptViewModel(input: unknown): OnboardingAttemptViewModel {
  const attempt = onboardingAttemptResponseSchema.parse(input);
  return { attemptToken: attempt.attempt_token, greeting: attempt.greeting };
}

export function toMessageViewModel(input: unknown): MessageViewModel {
  const message = messageResponseSchema.parse(input);
  return {
    id: message.id,
    sender: message.sender,
    content: message.content,
    sequence: message.sequence,
    status: message.status,
    createdAt: message.created_at,
    retryable: message.retryable,
    queueState: message.queue_state,
    deletedAt: message.deleted_at,
    ...(message.preparation === undefined ? {} : { preparation: message.preparation }),
    ...(message.revision === undefined ? {} : { revision: message.revision }),
    ...(message.files === undefined ? {} : { files: message.files }),
  };
}

function toAssistantReplyViewModel(input: unknown): AssistantReplyViewModel {
  const reply = assistantReplyResponseSchema.parse(input);
  return {
    ...(reply.publications === undefined ? {} : { publications: reply.publications }),
    id: reply.id,
    sourceMessageId: reply.source_message_id,
    conversationTurnOrdinal: reply.conversation_turn_ordinal,
    content: reply.content,
    status: reply.status,
    hasFullPrefix: reply.has_full_prefix,
    isTruncated: reply.is_truncated,
    createdAt: reply.created_at,
    updatedAt: reply.updated_at,
  };
}

export function toRoutineChatItemViewModel(input: unknown, expectedConversationId?: string): RoutineChatItemViewModel {
  const item = routineChatItemResponseSchema.parse(input);
  if (expectedConversationId !== undefined && item.conversation_id !== expectedConversationId) {
    throw new Error("routine chat item belongs to a different conversation");
  }
  return {
    id: item.id,
    kind: item.kind,
    routineId: item.routine_id,
    conversationId: item.conversation_id,
    sourceMessageId: item.source_message_id ?? null,
    titleSnapshot: item.title_snapshot,
    routineRevision: item.routine_revision,
    scheduleGeneration: item.schedule_generation,
    status: item.status,
    schedule: toRoutineSchedule(item.schedule),
    occurredAt: item.occurred_at,
    occurrenceId: item.occurrence_id ?? null,
    runId: item.run_id ?? null,
    executionId: item.execution_id ?? null,
    attemptId: item.attempt_id ?? null,
    generation: item.generation ?? null,
    resultId: item.result_id ?? null,
    resultInsertion: item.result_insertion ?? null,
    text: item.text ?? null,
    references: item.references.map((reference) => ({ label: reference.label, url: reference.url })),
    delayed: item.delayed ?? null,
    approvalId: item.approval_id ?? null,
    approvalRequestId: item.approval_request_id ?? null,
    approvalStatus: item.approval_status ?? null,
    approvalDecision: item.approval_decision ?? null,
    actionDigest: item.action_digest ?? null,
    actionAttemptId: item.action_attempt_id ?? null,
    approvalExpiresAt: item.approval_expires_at ?? null,
  };
}

export function toConversationViewModel(input: unknown, expectedAllyId?: string): ConversationViewModel {
  const conversation = conversationResponseSchema.parse(input);
  if (expectedAllyId !== undefined && conversation.ally_id !== expectedAllyId) {
    throw new Error("conversation belongs to a different Ally");
  }
  return {
    id: conversation.id,
    allyId: conversation.ally_id,
    messages: conversation.messages.map(toMessageViewModel),
    queue: conversation.queue?.map(toMessageViewModel),
    assistantReplies: conversation.assistant_replies.map(toAssistantReplyViewModel),
    routineItems: conversation.routine_items.map((item) => toRoutineChatItemViewModel(item, conversation.id)),
    nextCursor: conversation.next_cursor ?? null,
  };
}

export function toMessageAcceptanceViewModel(input: unknown): MessageAcceptanceViewModel {
  const acceptance = messageAcceptanceResponseSchema.parse(input);
  return {
    conversationId: acceptance.conversation_id,
    message: toMessageViewModel(acceptance.message),
    execution: acceptance.execution ?? null,
    replayed: acceptance.replayed,
  };
}

function toActivityViewModel(input: unknown): ActivityViewModel {
  const activity = activityResponseSchema.parse(input);
  return {
    id: activity.id,
    messageId: activity.message_id,
    sequence: activity.sequence,
    conversationTurnOrdinal: activity.conversation_turn_ordinal,
    kind: activity.kind,
    text: activity.text,
    state: activity.state,
    createdAt: activity.created_at,
    activityAttemptId: activity.activity_attempt_id,
    activityId: activity.activity_id,
    activityKind: activity.activity_kind,
    outcome: activity.outcome,
    durationMs: activity.duration_ms,
    approval: activity.approval ? toActivityApproval(activity.approval) : activity.approval,
  };
}

export function toActivitySnapshotViewModel(input: unknown): ActivitySnapshotViewModel {
  const snapshot = activitySnapshotResponseSchema.parse(input);
  return {
    conversationId: snapshot.conversation_id,
    activeMessageId: snapshot.active_message_id,
    activities: snapshot.activities.map(toActivityViewModel),
    state: snapshot.state,
    lastContiguousSequence: snapshot.last_contiguous_sequence,
    lastContiguousActivitySequence:
      snapshot.last_contiguous_activity_sequence ?? snapshot.last_contiguous_sequence,
    resumeCursor: snapshot.resume_cursor ?? null,
    nextCursor: snapshot.next_cursor ?? null,
    oldestSequence: snapshot.oldest_sequence ?? null,
    latestSequence: snapshot.latest_sequence ?? null,
    retentionGap: snapshot.retention_gap ?? false,
    assistantReply: snapshot.assistant_reply
      ? toAssistantReplyViewModel(snapshot.assistant_reply)
      : null,
  };
}

export function toAllySeedRequest(input: AllySeedInput) {
  const seed = allySeedInputSchema.parse(input);
  return {
    name: seed.name,
    job: seed.job,
    personality: seed.personality,
    appearance: {
      catalog_version: seed.appearanceCatalogVersion,
      key: seed.appearanceKey,
    },
  };
}

export function toCreateAllyRequest(input: CreateAllyInput) {
  const ally = createAllyInputSchema.parse(input);
  return {
    name: ally.name,
    job: ally.job,
    personality: ally.personality,
    appearance: {
      catalog_version: ally.appearanceCatalogVersion,
      key: ally.appearanceKey,
    },
    onboarding_attempt: ally.onboardingAttempt,
    reply: ally.reply,
  };
}
