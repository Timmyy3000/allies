import { describe, expect, it, vi } from "vitest";
import { createCloudClient } from "../src/client";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const allyId = "00000000-0000-4000-8000-000000000002";
const operationId = "00000000-0000-4000-8000-000000000003";
const pending = { ally_id: allyId, operation_id: operationId, state: "pending", retryable: true, safe_error_code: "" };
const envelope = (data: unknown, status = 200) => Response.json({ status: "success", message: "", data }, { status });

describe("ally deletion", () => {
  it("preserves the exact confirmation and treats accepted work as pending", async () => {
    const fetch = vi.fn(async (request: Request) => {
      expect(request.method).toBe("POST");
      expect(new URL(request.url).pathname).toBe(`/api/v1/workspaces/${workspaceId}/allies/${allyId}/deletion`);
      expect(await request.json()).toEqual({ confirmation: " Míra - deletes me" });
      return envelope(pending, 202);
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch: fetch as typeof globalThis.fetch });
    await expect(client.requestAllyDeletion(workspaceId, allyId, { confirmation: " Míra - deletes me" }))
      .resolves.toEqual({ allyId, operationId, state: "pending", retryable: true, safeErrorCode: "" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("reads terminal status without requiring retained operation data", async () => {
    const fetch = vi.fn(async (request: Request) => {
      expect(request.method).toBe("GET");
      return envelope({ ally_id: allyId, state: "complete", retryable: false, safe_error_code: "" });
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch: fetch as typeof globalThis.fetch });
    await expect(client.getAllyDeletion(workspaceId, allyId)).resolves.toMatchObject({ state: "complete", retryable: false });
  });

  it.each([
    { ...pending, ally_id: workspaceId },
    { ...pending, operation_id: undefined },
    { ...pending, state: "complete" },
    { ...pending, state: "complete", retryable: false, safe_error_code: "still_running" },
    { ...pending, state: "deleted" },
  ])("rejects malformed or cross-target success data", async (data) => {
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch: vi.fn(async () => envelope(data)) });
    await expect(client.getAllyDeletion(workspaceId, allyId)).rejects.toMatchObject({ kind: "contract" });
  });

  it.each(["", "a".repeat(129), "Mira\n- deletes me", "Mira\u202e - deletes me"])("rejects invalid input before I/O", async (confirmation) => {
    const fetch = vi.fn();
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });
    await expect(client.requestAllyDeletion(workspaceId, allyId, { confirmation })).rejects.toMatchObject({ kind: "bad-request" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([401, 403, 404, 409, 503])("does not retry a failed destructive request (%s)", async (status) => {
    const fetch = vi.fn(async () => Response.json({ status: "error", data: { code: "unavailable" } }, { status }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });
    await expect(client.requestAllyDeletion(workspaceId, allyId, { confirmation: "Mira - deletes me" })).rejects.toMatchObject({ status });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("does not send an already cancelled deletion", async () => {
    const fetch = vi.fn();
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });
    const controller = new AbortController();
    controller.abort();
    await expect(client.requestAllyDeletion(workspaceId, allyId, { confirmation: "Mira - deletes me" }, controller.signal)).rejects.toBeDefined();
    expect(fetch).not.toHaveBeenCalled();
  });
});
