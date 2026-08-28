import { describe, expect, it, vi } from "vitest";

import { createCloudClient } from "../src/client";
import { defineApiFixture } from "./fixtures";

const appearance = { catalog_version: "v1", key: "ghosty:fd304f" };
const ally = {
  appearance,
  binding_id: "binding_example",
  id: "ally_example",
  job: "Plan my work",
  name: "Sally",
  operation_id: "operation_example",
  personality: "I want you to be concise",
  provisioning_state: "ready",
  retryable: false,
};
const message = {
  content: "Help me plan today.",
  created_at: "2026-08-28T09:00:00Z",
  id: "message_example",
  sender: "user",
  sequence: 4,
  status: "accepted",
};

const onboardingResponse = defineApiFixture("/api/v1/onboarding/attempts", "post", 200, {
  status: "success",
  message: "Onboarding attempt started",
  data: { attempt_token: "attempt_example", greeting: "Hello, Sally." },
}).body;
const createResponse = defineApiFixture("/api/v1/workspaces/{workspace_id}/allies", "post", 202, {
  status: "success",
  message: "Ally accepted",
  data: ally,
}).body;
const getAllyResponse = defineApiFixture("/api/v1/workspaces/{workspace_id}/allies/{ally_id}", "get", 200, {
  status: "success",
  message: "Ally loaded",
  data: ally,
}).body;
const conversationResponse = defineApiFixture(
  "/api/v1/workspaces/{workspace_id}/allies/{ally_id}/conversation",
  "get",
  200,
  {
    status: "success",
    message: "Conversation loaded",
    data: { id: "conversation_example", ally_id: "ally_example", messages: [message], next_cursor: "older" },
  },
).body;
const messageResponse = defineApiFixture(
  "/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
  "post",
  201,
  {
    status: "success",
    message: "Message accepted",
    data: {
      conversation_id: "conversation_example",
      message,
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
      conversation_id: "conversation_example",
      activities: [{
        conversation_turn_ordinal: 1,
        created_at: "2026-08-28T09:00:01Z",
        id: "activity_example",
        kind: "assistant_delta",
        message_id: "message_example",
        sequence: 1,
        state: "running",
        text: "Working on it.",
      }],
      last_contiguous_sequence: 1,
      state: "running",
    },
  },
).body;

const createInput = {
  name: "Sally",
  job: "Plan my work",
  personality: "I want you to be concise",
  appearance: { catalogVersion: "v1", key: "ghosty:fd304f" },
  onboardingAttempt: "attempt_example",
  reply: "Help me plan today.",
};

describe("Allies Cloud client boundary", () => {
  it("maps the M2 operations and preserves request identity", async () => {
    const requests: Request[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      requests.push(request.clone());
      const path = new URL(request.url).pathname;
      if (path === "/api/v1/onboarding/attempts") return Response.json(onboardingResponse);
      if (path.endsWith("/allies") && request.method === "POST") return Response.json(createResponse, { status: 202 });
      if (path.endsWith("/conversation")) return Response.json(conversationResponse);
      if (path.endsWith("/messages")) return Response.json(messageResponse, { status: 201 });
      if (path.endsWith("/activities")) return Response.json(activityResponse);
      return Response.json(getAllyResponse);
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.beginOnboardingAttempt({
      name: "Sally",
      job: "Plan my work",
      personality: "I want you to be concise",
      appearance: { catalogVersion: "v1", key: "ghosty:fd304f" },
    })).resolves.toEqual({ attemptToken: "attempt_example", greeting: "Hello, Sally." });
    await expect(client.createAlly("workspace_example", createInput, "00000000-0000-4000-8000-000000000001"))
      .resolves.toMatchObject({ id: "ally_example", appearance: { key: "ghosty:fd304f" } });
    await expect(client.getAlly("workspace_example", "ally_example")).resolves.toMatchObject({ id: "ally_example" });
    await expect(client.getConversationByAlly("workspace_example", "ally_example", {
      limit: 12,
      cursor: "older",
    })).resolves.toMatchObject({ id: "conversation_example", nextCursor: "older" });
    await expect(client.sendMessage(
      "workspace_example",
      "conversation_example",
      "Help me plan today.",
      "00000000-0000-4000-8000-000000000002",
    )).resolves.toMatchObject({ conversationId: "conversation_example", message: { id: "message_example" } });
    await expect(client.getActivitySnapshot("workspace_example", "conversation_example", 10))
      .resolves.toMatchObject({ conversationId: "conversation_example", state: "running" });

    expect(requests.map((request) => `${request.method} ${new URL(request.url).pathname}`)).toEqual([
      "POST /api/v1/onboarding/attempts",
      "POST /api/v1/workspaces/workspace_example/allies",
      "GET /api/v1/workspaces/workspace_example/allies/ally_example",
      "GET /api/v1/workspaces/workspace_example/allies/ally_example/conversation",
      "POST /api/v1/workspaces/workspace_example/conversations/conversation_example/messages",
      "GET /api/v1/workspaces/workspace_example/conversations/conversation_example/activities",
    ]);
    expect(JSON.parse(await requests[1]!.clone().text())).toEqual({
      name: "Sally",
      job: "Plan my work",
      personality: "I want you to be concise",
      appearance,
      onboarding_attempt: "attempt_example",
      reply: "Help me plan today.",
    });
    expect(requests[1]!.headers.get("Idempotency-Key")).toBe("00000000-0000-4000-8000-000000000001");
    expect(new URL(requests[3]!.url).search).toBe("?limit=12&cursor=older");
    expect(JSON.parse(await requests[4]!.clone().text())).toEqual({ content: "Help me plan today." });
    expect(requests[4]!.headers.get("Idempotency-Key")).toBe("00000000-0000-4000-8000-000000000002");
    expect(new URL(requests[5]!.url).search).toBe("?limit=10");
  });

  it("rejects malformed responses and invalid mutation input before transport", async () => {
    const fetch = vi.fn(async () => Response.json({
      status: "success",
      message: "Ally loaded",
      data: { ...ally, appearance: { catalog_version: "v1", key: "not-an-appearance" } },
    }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.getAlly("workspace_example", "ally_example")).rejects.toMatchObject({ kind: "contract" });
    await expect(client.sendMessage(
      "workspace_example",
      "conversation_example",
      "   ",
      "00000000-0000-4000-8000-000000000002",
    )).rejects.toMatchObject({ kind: "bad-request" });
    await expect(client.createAlly("", createInput, "bad-key")).rejects.toMatchObject({ kind: "bad-request" });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("rejects a malformed conversation sequence and pre-aborted operation", async () => {
    const fetch = vi.fn(async () => Response.json({
      ...conversationResponse,
      data: { ...conversationResponse.data, messages: [{ ...message, sequence: -1 }] },
    }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.getConversationByAlly("workspace_example", "ally_example"))
      .rejects.toMatchObject({ kind: "contract" });
    const controller = new AbortController();
    controller.abort();
    await expect(client.getActivitySnapshot("workspace_example", "conversation_example", undefined, controller.signal))
      .rejects.toMatchObject({ kind: "aborted" });
    expect(fetch).toHaveBeenCalledOnce();
  });
});
