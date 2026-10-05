import { describe, expect, it } from "vitest";
import { approvalDetailSchema, approvalSummarySchema, toApprovalDetail, toApprovalSummary } from "../src/mappers/approvals";
import { createCloudClient } from "../src/client";

const summary = {
  id: "e9cfec70-9140-4e08-8ba7-42c6edce5142", message_id: "75ce0467-b673-46cb-bcf9-dd02b1d5c16d",
  status: "pending", expires_at: "2026-09-08T10:00:00Z", decided_at: null, acknowledgement_deadline_at: null,
};

const detail = { ...summary, action_label: "Run code", action_preview: "print('hello')" };
const presentation = {
  contract_version: "approval.v1",
  approval_request_id: "5c7e4ead-81cc-4677-8b2f-4855f126509b",
  preview_digest: `sha256:${"a".repeat(64)}`,
  explanation: {
    version: "approval-explanation.v1",
    approval_request_id: "5c7e4ead-81cc-4677-8b2f-4855f126509b",
    preview_digest: `sha256:${"a".repeat(64)}`,
    source: "model", action: "Display a greeting", target: "The current workspace",
    consequence: "A greeting will appear", reason: "Your Ally needs permission to continue",
  },
  technical_details: { action_kind: "execute_code", action_label: detail.action_label, action_preview: detail.action_preview },
};

describe("approval boundary", () => {
  it.each(["model", "fallback"])("maps bound %s copy without exposing private bindings", (source) => {
    const mapped = toApprovalDetail(approvalDetailSchema.parse({ ...detail, ...presentation, explanation: { ...presentation.explanation, source } }));
    expect(mapped).toMatchObject({ actionKind: "execute_code", explanation: { source, action: "Display a greeting" } });
    expect(mapped.explanation).not.toHaveProperty("approval_request_id");
    expect(mapped.explanation).not.toHaveProperty("preview_digest");
  });
  it.each([
    { approval_request_id: undefined },
    { preview_digest: "not-a-digest" },
    { contract_version: "approval.v2" },
    { explanation: { ...presentation.explanation, approval_request_id: summary.id } },
    { explanation: { ...presentation.explanation, preview_digest: `sha256:${"b".repeat(64)}` } },
    { explanation: { ...presentation.explanation, version: "approval-explanation.v2" } },
    { explanation: { ...presentation.explanation, source: "unverified" } },
    { explanation: { ...presentation.explanation, action: "" } },
    { explanation: { ...presentation.explanation, action: "\nsecret" } },
    { explanation: { ...presentation.explanation, action: "Hidden\u0085control" } },
    { explanation: { ...presentation.explanation, reason: undefined } },
    { explanation: { ...presentation.explanation, consequence: "😀".repeat(241) } },
  ])("ignores invalid optional presentation without rejecting the receipt: %j", (extension) => {
    const mapped = toApprovalDetail(approvalDetailSchema.parse({ ...detail, ...presentation, ...extension }));
    expect(mapped.explanation).toBeUndefined();
    expect(mapped.actionPreview).toBe(detail.action_preview);
  });
  it("accepts the server's Unicode explanation bound", () => {
    const mapped = toApprovalDetail(approvalDetailSchema.parse({ ...detail, ...presentation, explanation: { ...presentation.explanation, action: "😀".repeat(240) } }));
    expect(mapped.explanation?.action).toBe("😀".repeat(240));
  });
  it.each([
    { ...presentation.technical_details, action_kind: "unknown" },
    { ...presentation.technical_details, action_preview: "different invocation" },
    { ...presentation.technical_details, action_label: "different label" },
  ])("discards inconsistent technical metadata and preserves exact safe preview", (technical_details) => {
    const mapped = toApprovalDetail(approvalDetailSchema.parse({ ...detail, ...presentation, technical_details }));
    expect(mapped.actionKind).toBeUndefined();
    expect(mapped.actionPreview).toBe(detail.action_preview);
  });
  it.each([{}, presentation, { ...presentation, approval_request_id: null }, { ...presentation, explanation: { ...presentation.explanation, action: "Hidden\u0085control" } }])("keeps GET and 200/202 decisions usable across presentation versions: %j", async (extension) => {
    for (const status of [200, 202]) {
      const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch: async (_input, init) => Response.json({ status: "success", message: "ok", data: { ...detail, ...extension } }, { status: init?.method === "POST" ? status : 200 }) });
      await expect(client.getApproval("workspace", "conversation", summary.id)).resolves.toMatchObject({ id: summary.id, actionPreview: detail.action_preview });
      await expect(client.decideApproval("workspace", "conversation", summary.id, "approve", crypto.randomUUID())).resolves.toMatchObject({ id: summary.id, actionPreview: detail.action_preview });
    }
  });
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
