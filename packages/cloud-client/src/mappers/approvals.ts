import { z } from "zod";

export const approvalStatusSchema = z.enum([
  "pending", "decision_recorded", "approved", "rejected", "expired", "cancelled", "outcome_unknown",
]);

export const approvalSummarySchema = z.object({
  id: z.uuid(),
  message_id: z.uuid(),
  status: approvalStatusSchema,
  expires_at: z.iso.datetime({ offset: true }),
  decided_at: z.iso.datetime({ offset: true }).nullable(),
  acknowledgement_deadline_at: z.iso.datetime({ offset: true }).nullable(),
});

export const activityApprovalSchema = approvalSummarySchema.pick({ id: true, status: true, expires_at: true }).extend({ decided_at: z.iso.datetime({ offset: true }).nullish() });

export function toActivityApproval(value: z.infer<typeof activityApprovalSchema>) {
  return { id: value.id, status: value.status, expiresAt: value.expires_at, decidedAt: value.decided_at };
}

export type ActivityApproval = ReturnType<typeof toActivityApproval>;

const actionLabelSchema = z.string().min(1).refine((value) => !value.includes("\u0000") && [...value].length <= 120);
const actionPreviewSchema = z.string().min(1).refine((value) => !value.includes("\u0000") && new TextEncoder().encode(value).length <= 16 * 1024);
const explanationTextSchema = z.string().min(1).refine((value) => value.trim().length > 0 && [...value].length <= 240 && !/\p{Cc}/u.test(value));
const digestSchema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const explanationEnvelopeSchema = z.object({
  contract_version: z.literal("approval.v1"),
  approval_request_id: z.uuid(),
  preview_digest: digestSchema,
  explanation: z.object({
    version: z.literal("approval-explanation.v1"),
    approval_request_id: z.uuid(),
    preview_digest: digestSchema,
    source: z.enum(["model", "fallback"]),
    action: explanationTextSchema,
    target: explanationTextSchema,
    consequence: explanationTextSchema,
    reason: explanationTextSchema,
  }),
}).refine((value) => value.explanation.approval_request_id === value.approval_request_id && value.explanation.preview_digest === value.preview_digest);
const technicalDetailsSchema = z.object({
  action_kind: z.enum(["terminal", "execute_code", "plugin_tool"]),
  action_label: actionLabelSchema,
  action_preview: actionPreviewSchema,
});

export const approvalDetailSchema = approvalSummarySchema.extend({
  action_label: actionLabelSchema,
  action_preview: actionPreviewSchema,
  contract_version: z.unknown().optional(),
  approval_request_id: z.unknown().optional(),
  preview_digest: z.unknown().optional(),
  explanation: z.unknown().optional(),
  technical_details: z.unknown().optional(),
});

export function toApprovalSummary(value: z.infer<typeof approvalSummarySchema>) {
  return {
    id: value.id,
    messageId: value.message_id,
    status: value.status,
    expiresAt: value.expires_at,
    decidedAt: value.decided_at,
    acknowledgementDeadlineAt: value.acknowledgement_deadline_at,
  };
}

export function toApprovalDetail(value: z.infer<typeof approvalDetailSchema>) {
  const envelope = explanationEnvelopeSchema.safeParse(value);
  const technical = technicalDetailsSchema.safeParse(value.technical_details);
  const explanation = envelope.success ? envelope.data.explanation : undefined;
  const actionKind = technical.success && technical.data.action_preview === value.action_preview && technical.data.action_label === value.action_label
    ? technical.data.action_kind : undefined;
  return {
    ...toApprovalSummary(value), actionLabel: value.action_label, actionPreview: value.action_preview,
    ...(actionKind ? { actionKind } : {}),
    ...(explanation ? { explanation: {
      source: explanation.source, action: explanation.action, target: explanation.target,
      consequence: explanation.consequence, reason: explanation.reason,
    } } : {}),
  };
}

export type ApprovalSummary = ReturnType<typeof toApprovalSummary>;
export type ApprovalDetail = ReturnType<typeof toApprovalDetail>;
export type ApprovalDecision = "approve" | "reject";
