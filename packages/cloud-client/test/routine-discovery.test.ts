import { describe, expect, it, vi } from "vitest";

import { createCloudClient } from "../src";

const ids = {
  workspace: "00000000-0000-4000-8000-000000000001",
  ally: "00000000-0000-4000-8000-000000000003",
  routine: "00000000-0000-4000-8000-000000000004",
};

const summary = {
  id: ids.routine,
  responsible_ally_id: ids.ally,
  title: "Check availability",
  schedule: {
    kind: "recurring",
    frequency: "daily",
    local_time: "09:00:00",
    timezone: "Europe/Berlin",
  },
  revision: 4,
  schedule_generation: 2,
  schedule_state: "active",
  next_run_at: "2026-09-11T08:00:00Z",
  created_at: "2026-09-10T07:00:00Z",
  updated_at: "2026-09-10T07:00:00Z",
};

const detail = {
  ...summary,
  workspace_id: ids.workspace,
  owner_user_id: "00000000-0000-4000-8000-000000000002",
  binding_id: "00000000-0000-4000-8000-000000000009",
  main_conversation_id: "00000000-0000-4000-8000-000000000007",
  execution_prompt: "Check availability and report the full evidence.",
};

function success(data: unknown) {
  return Response.json({ status: "success", message: "Routine loaded", data });
}

describe("CLD-013 routine discovery adapter", () => {
  it("requests the released list route and maps summaries without a prompt", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const url = new URL(request.url);
      expect(request.method).toBe("GET");
      expect(url.pathname).toBe(`/api/v1/workspaces/${ids.workspace}/routines`);
      expect(url.searchParams.get("limit")).toBe("1");
      expect(url.searchParams.get("cursor")).toBe("opaque.cursor");
      expect(url.searchParams.get("ally_id")).toBe(ids.ally);
      return success({ items: [summary], next_cursor: "opaque.next" });
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.listRoutines(ids.workspace, {
      limit: 1,
      cursor: "opaque.cursor",
      allyId: ids.ally,
    })).resolves.toEqual({
      items: [{
        routineId: ids.routine,
        responsibleAllyId: ids.ally,
        title: "Check availability",
        schedule: {
          kind: "recurring",
          frequency: "daily",
          localTime: "09:00:00",
          timezone: "Europe/Berlin",
        },
        revision: 4,
        scheduleGeneration: 2,
        scheduleState: "active",
        nextRunAt: "2026-09-11T08:00:00Z",
        createdAt: "2026-09-10T07:00:00Z",
        updatedAt: "2026-09-10T07:00:00Z",
      }],
      nextCursor: "opaque.next",
    });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("requests the released detail route and preserves the full prompt and ownership fields", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      expect(new URL(request.url).pathname).toBe(`/api/v1/workspaces/${ids.workspace}/routines/${ids.routine}`);
      return success(detail);
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.getRoutine(ids.workspace, ids.routine)).resolves.toMatchObject({
      routineId: ids.routine,
      workspaceId: ids.workspace,
      ownerUserId: detail.owner_user_id,
      bindingId: detail.binding_id,
      mainConversationId: detail.main_conversation_id,
      executionPrompt: detail.execution_prompt,
      schedule: expect.objectContaining({ kind: "recurring", frequency: "daily" }),
    });
  });

  it("rejects uppercase discovery response identities at the contract boundary", async () => {
    const fetch = vi.fn(async () => success({
      items: [{ ...summary, id: "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA" }],
      next_cursor: null,
    }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.listRoutines(ids.workspace)).rejects.toMatchObject({ kind: "contract" });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("rejects malformed canonical routine identifiers before fetch", async () => {
    const fetch = vi.fn(async () => success({ items: [], next_cursor: null }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.listRoutines("workspace-not-a-uuid")).rejects.toMatchObject({ kind: "bad-request" });
    await expect(client.listRoutines(ids.workspace, { allyId: "ally-not-a-uuid" })).rejects.toMatchObject({ kind: "bad-request" });
    await expect(client.getRoutine(ids.workspace, "routine-not-a-uuid")).rejects.toMatchObject({ kind: "bad-request" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects uppercase and compact UUID serialization before fetch", async () => {
    const fetch = vi.fn(async () => success({ items: [], next_cursor: null }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });
    const uppercaseUuid = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA";
    const compactUuid = "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaaa";

    await expect(client.listRoutines(uppercaseUuid)).rejects.toMatchObject({ kind: "bad-request" });
    await expect(client.listRoutines(ids.workspace, { allyId: uppercaseUuid })).rejects.toMatchObject({ kind: "bad-request" });
    await expect(client.getRoutine(ids.workspace, uppercaseUuid)).rejects.toMatchObject({ kind: "bad-request" });
    await expect(client.getRoutine(ids.workspace, compactUuid)).rejects.toMatchObject({ kind: "bad-request" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects list items outside the requested ally scope", async () => {
    const fetch = vi.fn(async () => success({
      items: [{ ...summary, responsible_ally_id: "00000000-0000-4000-8000-000000000005" }],
      next_cursor: null,
    }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.listRoutines(ids.workspace, { allyId: ids.ally })).rejects.toMatchObject({ kind: "contract" });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("normalizes owner-isolation failures from the released route", async () => {
    const fetch = vi.fn(async () => Response.json({
      status: "error",
      message: "routine unavailable",
      data: { code: "routine_unavailable" },
    }, { status: 404 }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.getRoutine(ids.workspace, ids.routine)).rejects.toMatchObject({
      kind: "not-found",
      status: 404,
      code: "routine_unavailable",
    });
  });

  it("normalizes malformed cursor responses from the released list route", async () => {
    const fetch = vi.fn(async () => Response.json({
      status: "error",
      message: "request validation failed",
      data: { code: "validation_error" },
    }, { status: 422 }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.listRoutines(ids.workspace, { cursor: "tampered.cursor" })).rejects.toMatchObject({
      kind: "validation",
      status: 422,
      code: "validation_error",
    });
  });

  it("rejects invalid routine responses and malformed list options before exposing them", async () => {
    const fetch = vi.fn(async () => success({
      items: [{ ...summary, execution_prompt: "list must omit this" }],
      next_cursor: null,
    }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.listRoutines(ids.workspace)).rejects.toMatchObject({ kind: "contract" });
    await expect(client.listRoutines(ids.workspace, { limit: 101 })).rejects.toMatchObject({ kind: "bad-request" });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("keeps deleted history out of list pages while preserving it in detail", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const path = new URL(request.url).pathname;
      if (path.endsWith("/routines")) {
        return success({ items: [{ ...summary, schedule_state: "deleted" }], next_cursor: null });
      }
      return success({ ...detail, schedule_state: "deleted" });
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.listRoutines(ids.workspace)).rejects.toMatchObject({ kind: "contract" });
    await expect(client.getRoutine(ids.workspace, ids.routine)).resolves.toMatchObject({ scheduleState: "deleted" });
  });
});
