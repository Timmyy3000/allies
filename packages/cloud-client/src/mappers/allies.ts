import { z } from "zod";

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
  })
  .loose();

export const allyListResponseSchema = z.object({ allies: z.array(allyResponseSchema) }).loose();

export const onboardingAttemptResponseSchema = z
  .object({
    attempt_token: z.string().min(32).max(256),
    greeting: z.string().min(1),
  })
  .loose();

const messageResponseSchema = z
  .object({
    id: uuidSchema,
    sender: senderSchema,
    content: z.string(),
    sequence: z.number().int().positive(),
    status: messageStatusSchema,
    created_at: timestampSchema,
    retryable: z.boolean().default(false),
  })
  .loose();

export const conversationResponseSchema = z
  .object({
    id: uuidSchema,
    ally_id: uuidSchema,
    messages: z.array(messageResponseSchema),
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
  })
  .loose();

export const activitySnapshotResponseSchema = z
  .object({
    conversation_id: uuidSchema,
    activities: z.array(activityResponseSchema).max(200),
    state: activityStateSchema,
    last_contiguous_sequence: z.number().int().nonnegative(),
    last_contiguous_activity_sequence: z.number().int().nonnegative().optional(),
    resume_cursor: z.string().min(1).max(512).nullable().optional(),
    next_cursor: z.string().min(1).max(512).nullable().optional(),
    oldest_sequence: z.number().int().nonnegative().nullable().optional(),
    latest_sequence: z.number().int().nonnegative().nullable().optional(),
    retention_gap: z.boolean().optional(),
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
  id: string;
  sender: MessageSender;
  content: string;
  sequence: number;
  status: MessageStatus;
  createdAt: string;
  retryable?: boolean;
}

export interface ConversationViewModel {
  id: string;
  allyId: string;
  messages: MessageViewModel[];
  nextCursor: string | null;
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
}

export interface ActivitySnapshotViewModel {
  conversationId: string;
  activities: ActivityViewModel[];
  state: ActivityState;
  lastContiguousSequence: number;
  lastContiguousActivitySequence?: number;
  resumeCursor?: string | null;
  nextCursor?: string | null;
  oldestSequence?: number | null;
  latestSequence?: number | null;
  retentionGap?: boolean;
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
  };
}

export function toAllyListViewModel(input: unknown): AllyViewModel[] {
  return allyListResponseSchema.parse(input).allies.map(toAllyViewModel);
}

export function toOnboardingAttemptViewModel(input: unknown): OnboardingAttemptViewModel {
  const attempt = onboardingAttemptResponseSchema.parse(input);
  return { attemptToken: attempt.attempt_token, greeting: attempt.greeting };
}

function toMessageViewModel(input: unknown): MessageViewModel {
  const message = messageResponseSchema.parse(input);
  return {
    id: message.id,
    sender: message.sender,
    content: message.content,
    sequence: message.sequence,
    status: message.status,
    createdAt: message.created_at,
    retryable: message.retryable,
  };
}

export function toConversationViewModel(input: unknown): ConversationViewModel {
  const conversation = conversationResponseSchema.parse(input);
  return {
    id: conversation.id,
    allyId: conversation.ally_id,
    messages: conversation.messages.map(toMessageViewModel),
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
  };
}

export function toActivitySnapshotViewModel(input: unknown): ActivitySnapshotViewModel {
  const snapshot = activitySnapshotResponseSchema.parse(input);
  return {
    conversationId: snapshot.conversation_id,
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
