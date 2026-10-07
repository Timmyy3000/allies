import { describe, expect, it, vi } from "vitest";

import { createCloudClient } from "../src/client";
import { defineApiFixture } from "./fixtures";

const ids = {
  workspace: "00000000-0000-4000-8000-000000000001",
  ally: "00000000-0000-4000-8000-000000000002",
  binding: "00000000-0000-4000-8000-000000000003",
  operation: "00000000-0000-4000-8000-000000000004",
  conversation: "00000000-0000-4000-8000-000000000005",
  assistantMessage: "00000000-0000-4000-8000-000000000006",
  userMessage: "00000000-0000-4000-8000-000000000007",
  activity: "00000000-0000-4000-8000-000000000008",
} as const;

const ally = {
  id: ids.ally,
  binding_id: ids.binding,
  operation_id: ids.operation,
  name: "Mira",
  job: "Study partner",
  personality: "Calm, curious, and specific.",
  appearance: { catalog_version: "v1", key: "sunrise" },
  provisioning_state: "bound",
  retryable: false,
  label: "",
  show_label: false,
  settings_revision: 0,
  deletion_state: "active",
} as const;

const listResponse = defineApiFixture("/api/v1/workspaces/{workspace_id}/allies", "get", 200, {
  status: "success",
  message: "Allies loaded",
  data: { allies: [ally] },
}).body;

const onboardingResponse = defineApiFixture("/api/v1/onboarding/attempts", "post", 200, {
  status: "success",
  message: "Onboarding started",
  data: { attempt_token: "a".repeat(32), greeting: "Hello! What should we work on first?" },
}).body;

const createResponse = defineApiFixture("/api/v1/workspaces/{workspace_id}/allies", "post", 202, {
  status: "success",
  message: "Ally accepted",
  data: { ...ally, provisioning_state: "pending" },
}).body;

const conversationResponse = defineApiFixture(
  "/api/v1/workspaces/{workspace_id}/allies/{ally_id}/conversation",
  "get",
  200,
  {
    status: "success",
    message: "Conversation loaded",
    data: {
      id: ids.conversation,
      ally_id: ids.ally,
      messages: [
        {
          id: ids.assistantMessage,
          sender: "assistant",
          content: "Hello! What should we work on first?",
          preparation: "none", revision: 0,
          sequence: 1,
          status: "completed",
          retryable: false,
          created_at: "2026-08-20T16:00:00Z",
        },
      ],
      next_cursor: "cursor-next",
    },
  },
).body;

const acceptanceResponse = defineApiFixture(
  "/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
  "post",
  201,
  {
    status: "success",
    message: "Message accepted",
    data: {
      conversation_id: ids.conversation,
      message: {
        id: ids.userMessage,
        sender: "user",
        content: "Help me plan tomorrow.",
        preparation: "none", revision: 0,
        sequence: 2,
        status: "queued",
        retryable: false,
        created_at: "2026-08-20T16:01:00Z",
      },
      execution: null,
      replayed: false,
    },
  },
).body;

const activityResponse = defineApiFixture(
  "/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/activities",
  "get",
  200,
  {
    status: "success",
    message: "Activities loaded",
    data: {
      conversation_id: ids.conversation,
      activities: [
        {
          id: ids.activity,
          message_id: ids.userMessage,
          sequence: 1,
          conversation_turn_ordinal: 2,
          kind: "assistant_delta",
          text: "I can help with that.",
          state: "running",
          created_at: "2026-08-20T16:01:01Z",
        },
      ],
      state: "running",
      last_contiguous_sequence: 1,
      last_contiguous_activity_sequence: 1,
      retention_gap: false,
    },
  },
).body;

const largeAssistantReply = {
  id: ids.activity,
  source_message_id: ids.userMessage,
  conversation_turn_ordinal: 2,
  content: "r".repeat(300 * 1024),
  status: "in_progress",
  has_full_prefix: true,
  created_at: "2026-08-20T16:01:01Z",
  updated_at: "2026-08-20T16:01:02Z",
} as const;

const largeActivityResponse = {
  ...activityResponse,
  data: {
    ...activityResponse.data,
    assistant_reply: largeAssistantReply,
  },
} as const;

describe("Ally and conversation Cloud client boundary", () => {
  it("maps durable queue ownership and authenticated repeated deletion without recreating an intent", async () => {
    const queued = { ...acceptanceResponse.data.message, queue_state: "unclaimed", deleted_at: null };
    const tombstone = { ...queued, content: "", status: "stopped", queue_state: null, deleted_at: "2026-09-06T12:00:00Z" };
    const requests: Request[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      requests.push(request);
      if (request.method === "DELETE") return Response.json({ status: "success", message: "Removed", data: tombstone });
      if (request.url.endsWith("/activities")) return Response.json({
        ...activityResponse, data: { ...activityResponse.data, active_message_id: ids.userMessage },
      });
      return Response.json({
        ...conversationResponse, data: { ...conversationResponse.data, queue: [queued] },
      });
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch, prepareRequest: (request) => {
      request.headers.set("X-CSRFToken", "test-csrf");
      return request;
    } });
    expect((await client.getConversation(ids.workspace, ids.conversation)).queue)
      .toMatchObject([{ id: ids.userMessage, queueState: "unclaimed", deletedAt: null }]);
    expect((await client.getActivities(ids.workspace, ids.conversation)).activeMessageId).toBe(ids.userMessage);
    const deleted = await client.deleteQueuedMessage(ids.workspace, ids.conversation, ids.userMessage);
    expect(deleted).toMatchObject({ id: ids.userMessage, content: "", deletedAt: tombstone.deleted_at, queueState: null });
    expect(await client.deleteQueuedMessage(ids.workspace, ids.conversation, ids.userMessage)).toEqual(deleted);
    const deletes = requests.filter((request) => request.method === "DELETE");
    expect(deletes).toHaveLength(2);
    expect(deletes[0].headers.get("X-CSRFToken")).toBe("test-csrf");
    expect(new URL(deletes[0].url).pathname).toBe(
      `/api/v1/workspaces/${ids.workspace}/conversations/${ids.conversation}/messages/${ids.userMessage}`,
    );
  });

  it("rejects a false deletion receipt and retains conflict/unknown outcomes as errors", async () => {
    const fetch = vi.fn(async () => Response.json({ status: "success", message: "Removed", data: acceptanceResponse.data.message }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });
    await expect(client.deleteQueuedMessage(ids.workspace, ids.conversation, ids.userMessage)).rejects.toMatchObject({ kind: "contract" });
    fetch.mockResolvedValueOnce(Response.json({ status: "error", message: "Cannot remove", data: { code: "message_not_deletable" } }, { status: 409 }));
    await expect(client.deleteQueuedMessage(ids.workspace, ids.conversation, ids.userMessage)).rejects.toMatchObject({ kind: "conflict" });
    const abort = new AbortController();
    abort.abort();
    await expect(client.deleteQueuedMessage(ids.workspace, ids.conversation, ids.userMessage, abort.signal)).rejects.toMatchObject({ kind: "aborted" });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("maps the published Ally, onboarding, conversation, message, and activity operations", async () => {
    const requests: Request[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      requests.push(request.clone());
      const path = new URL(request.url).pathname;

      if (path.endsWith("/onboarding/attempts")) return Response.json(onboardingResponse);
      if (request.method === "POST" && path.endsWith("/messages")) {
        return Response.json(acceptanceResponse, { status: 201 });
      }
      if (request.method === "POST" && path.endsWith("/allies")) {
        return Response.json(createResponse, { status: 202 });
      }
      if (request.method === "GET" && path.endsWith("/activities")) return Response.json(activityResponse);
      if (request.method === "GET" && path.endsWith("/conversation")) return Response.json(conversationResponse);
      if (request.method === "GET" && path.includes("/conversations/")) return Response.json(conversationResponse);
      if (request.method === "GET" && path.endsWith("/allies")) return Response.json(listResponse);
      if (request.method === "GET" && path.includes("/allies/")) return Response.json({ ...listResponse, data: allyResponseData });
      throw new Error(`Unexpected request: ${request.method} ${path}`);
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.beginOnboarding({
      name: "Mira",
      job: "Study partner",
      personality: "Calm, curious, and specific.",
      appearanceCatalogVersion: "v1",
      appearanceKey: "sunrise",
    })).resolves.toEqual({
      attemptToken: "a".repeat(32),
      greeting: "Hello! What should we work on first?",
    });
    await expect(client.listAllies(ids.workspace)).resolves.toEqual([{
      id: ids.ally,
      bindingId: ids.binding,
      operationId: ids.operation,
      name: "Mira",
      job: "Study partner",
      personality: "Calm, curious, and specific.",
      appearance: { catalogVersion: "v1", key: "sunrise" },
      provisioningState: "bound",
      retryable: false,
      label: "",
      showLabel: false,
      settingsRevision: 0,
      deletionState: "active",
    }]);
    await expect(client.getAlly(ids.workspace, ids.ally)).resolves.toMatchObject({ id: ids.ally });
    await expect(client.createAlly(ids.workspace, {
      name: "Mira",
      job: "Study partner",
      personality: "Calm, curious, and specific.",
      appearanceCatalogVersion: "v1",
      appearanceKey: "sunrise",
      onboardingAttempt: "a".repeat(32),
      reply: "Help me plan.",
    }, "create-key-00000001")).resolves.toMatchObject({
      id: ids.ally,
      provisioningState: "pending",
    });
    await expect(client.getAllyConversation(ids.workspace, ids.ally, {
      limit: 50,
      cursor: "older",
    })).resolves.toMatchObject({
      id: ids.conversation,
      allyId: ids.ally,
      nextCursor: "cursor-next",
      messages: [{ sender: "assistant", sequence: 1 }],
    });
    await expect(client.getConversation(ids.workspace, ids.conversation, { limit: 50 })).resolves.toMatchObject({
      id: ids.conversation,
    });
    await expect(client.sendMessage(
      ids.workspace,
      ids.conversation,
      "Help me plan tomorrow.",
      "send-key-00000001",
      undefined,
      "Europe/Berlin",
    )).resolves.toMatchObject({
      conversationId: ids.conversation,
      message: { id: ids.userMessage, status: "queued" },
      replayed: false,
    });
    await expect(client.getActivities(ids.workspace, ids.conversation, 200)).resolves.toMatchObject({
      conversationId: ids.conversation,
      state: "running",
      lastContiguousSequence: 1,
      activities: [{ kind: "assistant_delta", text: "I can help with that." }],
    });
    await expect(client.getActivities(ids.workspace, ids.conversation, {
      limit: 50,
      cursor: "activity-cursor",
      replay: true,
    })).resolves.toMatchObject({ conversationId: ids.conversation });

    const onboardingRequest = requests.find((request) => request.url.endsWith("/onboarding/attempts"));
    expect(await onboardingRequest!.json()).toEqual({
      name: "Mira",
      job: "Study partner",
      personality: "Calm, curious, and specific.",
      appearance: { catalog_version: "v1", key: "sunrise" },
    });
    const createRequest = requests.find((request) => request.method === "POST" && request.url.endsWith("/allies"));
    expect(createRequest!.headers.get("Idempotency-Key")).toBe("create-key-00000001");
    const sendRequest = requests.find((request) => request.url.endsWith("/messages"));
    expect(sendRequest!.headers.get("Idempotency-Key")).toBe("send-key-00000001");
    expect(await sendRequest!.json()).toEqual({ content: "Help me plan tomorrow.", timezone: "Europe/Berlin" });
    const conversationRequest = requests.find((request) => new URL(request.url).pathname.endsWith("/conversation"));
    expect(new URL(conversationRequest!.url).search).toBe("?limit=50&cursor=older");
    const activityRequest = requests.find((request) => new URL(request.url).pathname.endsWith("/activities"));
    expect(new URL(activityRequest!.url).search).toBe("?limit=200");
    const replayActivityRequest = requests.find((request) => new URL(request.url).search.includes("replay=true"));
    expect(new URL(replayActivityRequest!.url).search).toBe("?limit=50&cursor=activity-cursor&replay=true");
  });

  it("rejects invalid mutation input before making a request", async () => {
    const fetch = vi.fn(async () => Response.json(listResponse));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.createAlly(ids.workspace, {
      name: "Mira",
      job: "Study partner",
      personality: "Calm",
      appearanceCatalogVersion: "v1",
      appearanceKey: "sunrise",
      onboardingAttempt: "short",
      reply: "Hello",
    }, "short")).rejects.toMatchObject({ kind: "bad-request" });
    await expect(client.sendMessage(ids.workspace, ids.conversation, "", "send-key-00000001"))
      .rejects.toMatchObject({ kind: "bad-request" });
    await expect(client.getActivities(ids.workspace, ids.conversation, 1001))
      .rejects.toMatchObject({ kind: "bad-request" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("allows a bounded large durable reply on the chat activity read", async () => {
    const fetch = vi.fn(async () => Response.json(largeActivityResponse));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.getActivities(ids.workspace, ids.conversation)).resolves.toMatchObject({
      assistantReply: {
        sourceMessageId: ids.userMessage,
        content: largeAssistantReply.content,
        hasFullPrefix: true,
      },
    });
  });

  it("keeps an explicit JSON limit for chat reads", async () => {
    const fetch = vi.fn(async () => Response.json(largeActivityResponse));
    const client = createCloudClient({
      baseUrl: "https://cloud.example.com",
      fetch,
      maxJsonBytes: 256 * 1024,
    });

    await expect(client.getActivities(ids.workspace, ids.conversation))
      .rejects.toMatchObject({ kind: "contract" });
  });

  it("preserves a replayed send as an accepted prior intent", async () => {
    const fetch = vi.fn(async () => Response.json({
      ...acceptanceResponse,
      data: { ...acceptanceResponse.data, replayed: true },
    }, { status: 200 }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.sendMessage(
      ids.workspace,
      ids.conversation,
      "Help me plan tomorrow.",
      "send-key-00000001",
    )).resolves.toMatchObject({ replayed: true, message: { id: ids.userMessage } });
  });

  it("turns malformed Ally and activity successes into contract errors", async () => {
    const malformedAlly = { ...listResponse, data: { allies: [{ ...ally, id: "not-a-uuid" }] } };
    const malformedActivity = {
      ...activityResponse,
      data: { ...activityResponse.data, activities: [{ ...activityResponse.data.activities[0], state: "unknown" }] },
    };
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(input instanceof Request ? input.url : input).pathname;
      return Response.json(path.endsWith("/activities") ? malformedActivity : malformedAlly);
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.listAllies(ids.workspace)).rejects.toMatchObject({ kind: "contract" });
    await expect(client.getActivities(ids.workspace, ids.conversation)).rejects.toMatchObject({ kind: "contract" });
  });
});

const allyResponseData = ally;

describe("compacted activity replay", () => {
  it("projects a merged delta row as every sequence it covers", async () => {
    const { projectActivitySnapshot, EMPTY_ACTIVITY_PROJECTION, toActivitySnapshotViewModel } = await import("../src/index");
    const row = (sequence: number, text: string, first?: number) => ({
      id: `9a6f842d-9638-44ae-97b4-fe541a3205b${sequence}`,
      message_id: "663c0652-5b6f-4631-978a-fa9ba31e4fe0",
      sequence,
      conversation_turn_ordinal: 1,
      kind: "assistant_delta",
      text,
      state: "running",
      created_at: "2026-10-05T18:13:55.377016Z",
      ...(first === undefined ? {} : { first_sequence: first }),
    });
    const snapshot = toActivitySnapshotViewModel({
      conversation_id: "529f4af1-ddc6-4cb4-b3c8-a7f4150369e1",
      activities: [row(3, "Hello", 1), row(4, " there")],
      state: "completed",
      last_contiguous_sequence: 0,
    });
    const projected = projectActivitySnapshot(EMPTY_ACTIVITY_PROJECTION, snapshot);
    expect(projected.lastContiguousSequence).toBe(4);
    expect(projected.seenSequences).toEqual([1, 2, 3, 4]);
    expect(projected.turns[0].assistantText).toBe("Hello there");
    expect(projected.pendingActivities).toBeUndefined();
    expect(projectActivitySnapshot(projected, snapshot).turns[0].assistantText).toBe("Hello there");

    const waiting = projectActivitySnapshot(EMPTY_ACTIVITY_PROJECTION, toActivitySnapshotViewModel({
      conversation_id: "529f4af1-ddc6-4cb4-b3c8-a7f4150369e1",
      activities: [row(4, " there", 2)],
      state: "running",
      last_contiguous_sequence: 0,
    }));
    expect(waiting.lastContiguousSequence).toBe(0);
    const drained = projectActivitySnapshot(waiting, toActivitySnapshotViewModel({
      conversation_id: "529f4af1-ddc6-4cb4-b3c8-a7f4150369e1",
      activities: [row(1, "Hi")],
      state: "completed",
      last_contiguous_sequence: 0,
    }));
    expect(drained.lastContiguousSequence).toBe(4);
    expect(drained.turns[0].assistantText).toBe("Hi there");
    expect(drained.pendingActivities).toBeUndefined();
  });
});
