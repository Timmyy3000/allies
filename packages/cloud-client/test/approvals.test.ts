import { describe, expect, it } from "vitest";
import { approvalDetailSchema, approvalSummarySchema, toApprovalSummary } from "../src/mappers/approvals";
import { createCloudClient } from "../src/client";

const summary = {
  id: "e9cfec70-9140-4e08-8ba7-42c6edce5142", message_id: "75ce0467-b673-46cb-bcf9-dd02b1d5c16d",
  status: "pending", expires_at: "2026-09-08T10:00:00Z", decided_at: null, acknowledgement_deadline_at: null,
};

describe("approval boundary", () => {
  it("rejects a detail or decision receipt for another approval", async () => {
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch: async () => Response.json({ status: "success", message: "ok", data: { ...summary, action_label: "Action", action_preview: "Exact action" } }) });
    const differentId = "e9cfec70-9140-4e08-8ba7-42c6edce5143";
    await expect(client.getApproval("workspace", "conversation", differentId)).rejects.toBeDefined();
    await expect(client.decideApproval("workspace", "conversation", differentId, "approve", differentId)).rejects.toBeDefined();
  });
  it.each([200, 202])("maps a %s decision receipt without claiming runtime completion", async (status) => {
    const key = crypto.randomUUID();
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch: async (input, init) => {
      const request = input instanceof Request ? input : new Request(input, init);
      expect(new URL(request.url).pathname).toBe(`/api/v1/workspaces/workspace/conversations/conversation/approvals/${summary.id}/decision`);
      expect(request.headers.get("Idempotency-Key")).toBe(key);
      expect(await request.json()).toEqual({ decision: "reject" });
      return Response.json({ status: "success", message: "Recorded", data: { ...summary, status: "decision_recorded", decided_at: "2026-09-08T09:59:00Z", acknowledgement_deadline_at: "2026-09-08T09:59:30Z", action_label: "Action", action_preview: "Exact action" } }, { status });
    } });
    await expect(client.decideApproval("workspace", "conversation", summary.id, "reject", key)).resolves.toMatchObject({ status: "decision_recorded", actionPreview: "Exact action" });
  });
  it("exposes only public status fields from summaries", () => {
    const parsed = toApprovalSummary(approvalSummarySchema.parse({ ...summary, action_preview: "private", attempt_id: "internal" }));
    expect(parsed).toEqual({ id: summary.id, messageId: summary.message_id, status: "pending", expiresAt: summary.expires_at, decidedAt: null, acknowledgementDeadlineAt: null });
    expect(JSON.stringify(parsed)).not.toMatch(/private|internal/);
  });
  it.each(["", "text\u0000value", "😀".repeat(4097)])("rejects unusable or oversized previews", (action_preview) => {
    expect(approvalDetailSchema.safeParse({ ...summary, action_label: "Action", action_preview }).success).toBe(false);
  });
  it("rejects unknown states and timezone-free expiry", () => {
    expect(approvalSummarySchema.safeParse({ ...summary, status: "resumed" }).success).toBe(false);
    expect(approvalSummarySchema.safeParse({ ...summary, expires_at: "2026-09-08T10:00:00" }).success).toBe(false);
  });
  it("uses the server's Unicode character bound for labels", () => {
    expect(approvalDetailSchema.safeParse({ ...summary, action_label: "😀".repeat(120), action_preview: "Action" }).success).toBe(true);
    expect(approvalDetailSchema.safeParse({ ...summary, action_label: "😀".repeat(121), action_preview: "Action" }).success).toBe(false);
  });
});
