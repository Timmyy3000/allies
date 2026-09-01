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

describe("Ally and conversation Cloud client boundary", () => {
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
    await expect(client.getActivities(ids.workspace, ids.conversation, 201))
      .rejects.toMatchObject({ kind: "bad-request" });
    expect(fetch).not.toHaveBeenCalled();
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
