import { z } from "zod";

import { canonicalRoutineUuidSchema, routineScheduleSchema, toRoutineSchedule, type RoutineScheduleViewModel } from "./routines";

const timestampSchema = z.iso.datetime({ offset: true });
const routineStateSchema = z.enum(["active", "paused", "deleted", "exhausted"]);
const discoverableRoutineStateSchema = z.enum(["active", "paused"]);
const titleSchema = z.string().min(1).max(120).refine((value) => !value.includes("\u0000"));
const executionPromptSchema = z.string().min(1).refine(
  (value) => !value.includes("\u0000") && new TextEncoder().encode(value).byteLength <= 16 * 1024,
);

const routineDiscoverySummarySchema = z.object({
  id: canonicalRoutineUuidSchema,
  responsible_ally_id: canonicalRoutineUuidSchema,
  title: titleSchema,
  schedule: routineScheduleSchema,
  revision: z.number().int().min(1),
  schedule_generation: z.number().int().min(1),
  schedule_state: routineStateSchema,
  next_run_at: timestampSchema.nullable(),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strict();

const routineDiscoveryPageSchema = z.object({
  items: z.array(routineDiscoverySummarySchema).max(100),
  next_cursor: z.string().min(1).max(512).nullable(),
}).strict().superRefine((page, context) => {
  page.items.forEach((item, index) => {
    if (!discoverableRoutineStateSchema.safeParse(item.schedule_state).success) {
      context.addIssue({
        code: "custom",
        path: ["items", index, "schedule_state"],
        message: "routine discovery only includes active or paused routines",
      });
    }
  });
});

const routineDiscoveryDetailSchema = routineDiscoverySummarySchema.extend({
  workspace_id: canonicalRoutineUuidSchema,
  owner_user_id: canonicalRoutineUuidSchema,
  binding_id: canonicalRoutineUuidSchema,
  main_conversation_id: canonicalRoutineUuidSchema,
  execution_prompt: executionPromptSchema,
}).strict();

const routineDiscoveryPageEnvelopeSchema = z.object({
  status: z.literal("success"),
  message: z.string(),
  data: routineDiscoveryPageSchema,
}).strict();

const routineDiscoveryDetailEnvelopeSchema = z.object({
  status: z.literal("success"),
  message: z.string(),
  data: routineDiscoveryDetailSchema,
}).strict();

export type RoutineDiscoveryState = z.infer<typeof routineStateSchema>;

export interface RoutineDiscoverySummary {
  routineId: string;
  responsibleAllyId: string;
  title: string;
  schedule: RoutineScheduleViewModel;
  revision: number;
  scheduleGeneration: number;
  scheduleState: RoutineDiscoveryState;
  nextRunAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface RoutineDiscoveryPage {
  items: RoutineDiscoverySummary[];
  nextCursor: string | null;
}

export interface RoutineDiscoveryDetail extends RoutineDiscoverySummary {
  workspaceId: string;
  ownerUserId: string;
  bindingId: string;
  mainConversationId: string;
  executionPrompt: string;
}

type RoutineDiscoverySummaryResponse = z.infer<typeof routineDiscoverySummarySchema>;

function toRoutineDiscoverySummaryValue(summary: RoutineDiscoverySummaryResponse): RoutineDiscoverySummary {
  return {
    routineId: summary.id,
    responsibleAllyId: summary.responsible_ally_id,
    title: summary.title,
    schedule: toRoutineSchedule(summary.schedule),
    revision: summary.revision,
    scheduleGeneration: summary.schedule_generation,
    scheduleState: summary.schedule_state,
    nextRunAt: summary.next_run_at,
    createdAt: summary.created_at,
    updatedAt: summary.updated_at,
  };
}

function toRoutineDiscoveryPage(input: unknown): RoutineDiscoveryPage {
  const page = routineDiscoveryPageSchema.parse(input);
  return {
    items: page.items.map(toRoutineDiscoverySummaryValue),
    nextCursor: page.next_cursor,
  };
}

function toRoutineDiscoveryDetail(input: unknown): RoutineDiscoveryDetail {
  const detail = routineDiscoveryDetailSchema.parse(input);
  return {
    ...toRoutineDiscoverySummaryValue(detail),
    workspaceId: detail.workspace_id,
    ownerUserId: detail.owner_user_id,
    bindingId: detail.binding_id,
    mainConversationId: detail.main_conversation_id,
    executionPrompt: detail.execution_prompt,
  };
}

export function parseRoutineDiscoveryPageEnvelope(input: unknown): RoutineDiscoveryPage {
  return toRoutineDiscoveryPage(routineDiscoveryPageEnvelopeSchema.parse(input).data);
}

export function parseRoutineDiscoveryDetailEnvelope(input: unknown): RoutineDiscoveryDetail {
  return toRoutineDiscoveryDetail(routineDiscoveryDetailEnvelopeSchema.parse(input).data);
}
