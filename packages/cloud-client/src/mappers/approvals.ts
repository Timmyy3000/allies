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

export const approvalDetailSchema = approvalSummarySchema.extend({
  action_label: z.string().min(1).refine((value) => !value.includes("\u0000") && [...value].length <= 120),
  action_preview: z.string().min(1).refine((value) => !value.includes("\u0000") && new TextEncoder().encode(value).length <= 16 * 1024),
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
  return { ...toApprovalSummary(value), actionLabel: value.action_label, actionPreview: value.action_preview };
}

export type ApprovalSummary = ReturnType<typeof toApprovalSummary>;
export type ApprovalDetail = ReturnType<typeof toApprovalDetail>;
export type ApprovalDecision = "approve" | "reject";
