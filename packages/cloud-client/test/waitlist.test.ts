import { describe, expect, it, vi } from "vitest";

import { createCloudClient } from "../src/client";

const acknowledgement = (operation: string, revision: number) => ({
  status: "success",
  message: "Waitlist updated",
  data: {
    operation,
    result_lifecycle: "ready_for_greeting",
    result_revision: revision,
  },
});

const snapshot = {
  status: "success",
  message: "Waitlist draft restored",
  data: {
    id: "wld_example",
    lifecycle: "ready_for_greeting",
    revision: 2,
    configuration: {
      name: "Ari",
      appearance_catalog_version: "v1",
      appearance_key: "calm-blue",
      job: "Planning",
      personality: "Warm and concise",
      ignored: "not exposed",
    },
    greeting: {
      text: "Hello Ari",
      policy_version: "greeting-v1",
      generated_at: "2026-08-15T12:00:00Z",
      ignored: "not exposed",
    },
    reply: {
      text: "I like concise plans.",
      status: "pending",
      recorded_at: "2026-08-15T12:01:00Z",
      ignored: "not exposed",
    },
    join: {
      email: "a***@example.com",
      joined_at: "2026-08-15T12:02:00Z",
      ignored: "not exposed",
    },
    timestamps: {
      created_at: "2026-08-15T11:00:00Z",
      expires_at: "2026-08-22T11:00:00Z",
      generated_at: "2026-08-15T12:00:00Z",
      joined_at: "2026-08-15T12:02:00Z",
      replied_at: "2026-08-15T12:01:00Z",
      updated_at: "2026-08-15T12:02:00Z",
      ignored: "not exposed",
    },
    ignored: "not exposed",
  },
};

function jsonResponse(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

describe("waitlist Cloud client boundary", () => {
  it("runs the typed waitlist operations and preserves mutation inputs", async () => {
    const requests: Array<{ request: Request; body: string }> = [];
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(input);
      const body = await request.text();
      requests.push({ request, body });
      const path = new URL(request.url).pathname;

      if (path.endsWith("/waitlist/session")) return new Response(null, { status: 204 });
      if (request.method === "POST" && path.endsWith("/waitlist/draft")) {
        return jsonResponse(acknowledgement("create", 1));
      }
      if (request.method === "GET" && path.endsWith("/waitlist/draft")) return jsonResponse(snapshot);
      if (path.endsWith("/configuration")) return jsonResponse(acknowledgement("configure", 2));
      if (path.endsWith("/greeting")) return jsonResponse(acknowledgement("greeting", 3));
      if (path.endsWith("/reply")) return jsonResponse(acknowledgement("reply", 4));
      if (path.endsWith("/join")) {
        return jsonResponse({
          status: "success",
          message: "Waitlist joined",
          data: {
            email: "a***@example.com",
            operation: "join",
            result_lifecycle: "pending_claim",
            result_revision: 5,
            raw_email: "ari@example.com",
          },
        });
      }
      throw new Error(`Unexpected request: ${request.method} ${path}`);
    });
    const client = createCloudClient({
      baseUrl: "https://cloud.example.com",
      fetch,
      prepareRequest: (request) => {
        const headers = new Headers(request.headers);
        headers.set("X-CSRFToken", "csrf-value");
        return new Request(request, { credentials: "include", headers });
      },
    });

    await expect(client.getWaitlistSession()).resolves.toBeUndefined();
    await expect(client.createWaitlistDraft("idem-create")).resolves.toEqual({
      operation: "create",
      resultLifecycle: "ready_for_greeting",
      resultRevision: 1,
    });
    await expect(client.getWaitlistDraft()).resolves.toEqual({
      id: "wld_example",
      lifecycle: "ready_for_greeting",
      revision: 2,
      configuration: {
        name: "Ari",
        appearanceCatalogVersion: "v1",
        appearanceKey: "calm-blue",
        job: "Planning",
        personality: "Warm and concise",
      },
      greeting: {
        text: "Hello Ari",
        policyVersion: "greeting-v1",
        generatedAt: "2026-08-15T12:00:00Z",
      },
      reply: {
        text: "I like concise plans.",
        status: "pending",
        recordedAt: "2026-08-15T12:01:00Z",
      },
      join: { email: "a***@example.com", joinedAt: "2026-08-15T12:02:00Z" },
      timestamps: {
        createdAt: "2026-08-15T11:00:00Z",
        expiresAt: "2026-08-22T11:00:00Z",
        generatedAt: "2026-08-15T12:00:00Z",
        joinedAt: "2026-08-15T12:02:00Z",
        repliedAt: "2026-08-15T12:01:00Z",
        updatedAt: "2026-08-15T12:02:00Z",
      },
    });
    await expect(client.updateWaitlistConfiguration({
      revision: 2,
      idempotencyKey: "idem-config",
      name: "Ari",
      appearanceCatalogVersion: "v1",
      appearanceKey: "calm-blue",
      job: "Planning",
      personality: "Warm and concise",
    })).resolves.toMatchObject({ resultRevision: 2 });
    await expect(client.generateWaitlistGreeting({ revision: 2, idempotencyKey: "idem-greeting" }))
      .resolves.toMatchObject({ resultRevision: 3 });
    await expect(client.recordWaitlistReply({
      revision: 3,
      idempotencyKey: "idem-reply",
      text: "I like concise plans.",
    })).resolves.toMatchObject({ resultRevision: 4 });
    await expect(client.joinWaitlist({
      revision: 4,
      idempotencyKey: "idem-join",
      email: "ari@example.com",
      consentVersion: "2026-08-01",
    })).resolves.toEqual({
      email: "a***@example.com",
      operation: "join",
      resultLifecycle: "pending_claim",
      resultRevision: 5,
    });

    const createRequest = requests.find(({ request }) =>
      request.method === "POST" && new URL(request.url).pathname.endsWith("/waitlist/draft"));
    expect(createRequest?.body).toBe("");
    expect(createRequest?.request.headers.get("Idempotency-Key")).toBe("idem-create");
    expect(createRequest?.request.headers.get("X-CSRFToken")).toBe("csrf-value");

    const configurationRequest = requests.find(({ request }) =>
      new URL(request.url).pathname.endsWith("/configuration"));
    expect(configurationRequest?.request.headers.get("Idempotency-Key")).toBe("idem-config");
    expect(JSON.parse(configurationRequest?.body ?? "{}")).toMatchObject({ revision: 2, job: "Planning" });

    const greetingRequest = requests.find(({ request }) => new URL(request.url).pathname.endsWith("/greeting"));
    expect(greetingRequest?.request.headers.get("Idempotency-Key")).toBe("idem-greeting");
    expect(JSON.parse(greetingRequest?.body ?? "{}")).toEqual({ revision: 2 });

    const replyRequest = requests.find(({ request }) => new URL(request.url).pathname.endsWith("/reply"));
    expect(replyRequest?.request.headers.get("Idempotency-Key")).toBe("idem-reply");
    expect(JSON.parse(replyRequest?.body ?? "{}")).toEqual({ revision: 3, text: "I like concise plans." });

    const joinRequest = requests.find(({ request }) => new URL(request.url).pathname.endsWith("/join"));
    expect(JSON.parse(joinRequest?.body ?? "{}")).toEqual({
      revision: 4,
      email: "ari@example.com",
      consent_version: "2026-08-01",
    });
    expect(joinRequest?.request.headers.get("Idempotency-Key")).toBe("idem-join");
  });

  it("rejects a raw email where the Cloud contract promises a masked email", async () => {
    const client = createCloudClient({
      baseUrl: "https://cloud.example.com",
      fetch: async () => jsonResponse({
        status: "success",
        message: "Waitlist joined",
        data: {
          email: "ari@example.com",
          operation: "join",
          result_lifecycle: "pending_claim",
          result_revision: 5,
        },
      }),
    });

    await expect(client.joinWaitlist({
      revision: 4,
      idempotencyKey: "idem-join",
      email: "ari@example.com",
      consentVersion: "2026-08-01",
    })).rejects.toMatchObject({ kind: "contract" });
  });

  it("hides malformed open-ended snapshot sections without rejecting the draft", async () => {
    const client = createCloudClient({
      baseUrl: "https://cloud.example.com",
      fetch: async () => jsonResponse({
        ...snapshot,
        data: {
          ...snapshot.data,
          greeting: { text: "Hello Ari" },
          reply: { text: "Not ready", status: "sent" },
          join: { email: "ari@example.com", joined_at: "2026-08-15T12:02:00Z" },
        },
      }),
    });

    await expect(client.getWaitlistDraft()).resolves.toMatchObject({
      id: "wld_example",
      greeting: null,
      reply: null,
      join: null,
    });
  });
});
