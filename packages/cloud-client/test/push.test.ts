import { describe, expect, it, vi } from "vitest";
import { createPushClient } from "../src/push";
const workspace = "11111111-1111-4111-8111-111111111111";
const binding = "22222222-2222-4222-8222-222222222222";
const input = { browser_id: workspace, binding_id: binding, replaces_binding_id: null, endpoint: "https://fcm.googleapis.com/push/test", keys: { p256dh: "B".repeat(87), auth: "A".repeat(22) } };
describe("push Cloud adapter", () => {
  it("uses browser credentials and prepared CSRF request, preserves binding replay bytes", async () => {
    const fetch = vi.fn(async (request: Request) => {
      expect(request.credentials).toBe("include"); expect(request.headers.get("X-CSRFToken")).toBe("test"); expect(await request.json()).toEqual(input);
      return Response.json({ status: "success", message: "Push enabled", data: { subscription_id: workspace, browser_id: workspace, binding_id: binding, workspace_id: workspace, session_id: binding, state: "active" } });
    });
    const push = createPushClient({ baseUrl: "https://cloud.example", fetch: fetch as typeof globalThis.fetch, prepareRequest: request => { request.headers.set("X-CSRFToken", "test"); return request; } });
    await push.register(workspace, input); await push.register(workspace, input);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("rejects unknown request fields and malformed responses, handles bodyless revoke", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 204 }));
    const push = createPushClient({ baseUrl: "https://cloud.example", fetch });
    expect(() => push.register(workspace, { ...input, owner_user_id: workspace } as typeof input)).toThrow();
    await expect(push.revoke(workspace, workspace, binding)).resolves.toBeUndefined();
    await expect(push.config(workspace)).rejects.toMatchObject({ kind: "contract" });
  });
  it("keeps unavailable and conflict errors private", async () => {
    const push = createPushClient({ baseUrl: "https://cloud.example", fetch: async () => Response.json({ status: "error", data: { code: "push_binding_conflict" } }, { status: 409 }) });
    await expect(push.register(workspace, input)).rejects.toMatchObject({ kind: "conflict", code: "push_binding_conflict" });
  });
});
