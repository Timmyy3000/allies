import type { ActivityViewModel, ApprovalSummary } from "@allies/cloud-client";

interface ProjectedApproval {
  sequence: number;
  summary: ApprovalSummary;
}

export interface ActivityApprovalProjection {
  conversationId: string | null;
  byId: Record<string, ProjectedApproval>;
}

export const EMPTY_ACTIVITY_APPROVAL_PROJECTION: ActivityApprovalProjection = {
  conversationId: null,
  byId: {},
};

export function mergeActivityApprovals(
  current: ActivityApprovalProjection,
  conversationId: string,
  activities: readonly ActivityViewModel[],
): ActivityApprovalProjection {
  const byId = current.conversationId === conversationId ? { ...current.byId } : {};

  for (const activity of activities) {
    const approval = activity.approval;
    if (!approval || activity.sequence <= (byId[approval.id]?.sequence ?? 0)) continue;
    byId[approval.id] = {
      sequence: activity.sequence,
      summary: {
        id: approval.id,
        messageId: activity.messageId,
        status: approval.status,
        expiresAt: approval.expiresAt,
        decidedAt: approval.decidedAt ?? null,
        acknowledgementDeadlineAt: null,
      },
    };
  }

  return { conversationId, byId };
}

export function selectActivityApprovals(projection: ActivityApprovalProjection): ApprovalSummary[] {
  return Object.values(projection.byId)
    .sort((left, right) => left.sequence - right.sequence || left.summary.id.localeCompare(right.summary.id))
    .map((item) => item.summary);
}
