import { describe, expect, it, vi } from "vitest";

import { createCloudClient } from "../src/client";

describe("waitlist Cloud client boundary", () => {
  it("uses only the create and complete entry operations", async () => {
    const requests: Request[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(input);
      requests.push(request.clone());
      const path = new URL(request.url).pathname;
      if (path.endsWith("/entries/complete")) {
        return Response.json({ status: "success", message: "complete", data: { email: "p****n@example.com" } });
      }
      return Response.json({
        status: "success",
        message: "ready",
        data: { attempt_token: "a".repeat(64), greeting: "Hello there." },
      });
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.createWaitlistEntry({
      attemptId: "attempt-0000000000000001",
      name: "Ari",
      appearanceCatalogVersion: "v1",
      appearanceKey: "ghosty:fd304f",
      job: "Planning",
      personality: "Warm",
    })).resolves.toEqual({ attemptToken: "a".repeat(64), greeting: "Hello there." });
    await expect(client.completeWaitlistEntry({
      attemptToken: "a".repeat(64),
      reply: "Help me plan.",
      email: "person@example.com",
      consentVersion: "waitlist-v1",
    })).resolves.toEqual({ email: "p****n@example.com" });

    expect(requests.map((request) => new URL(request.url).pathname)).toEqual([
      "/api/v1/waitlist/entries",
      "/api/v1/waitlist/entries/complete",
    ]);
    expect(JSON.parse(await requests[1]!.text())).toMatchObject({
      reply: "Help me plan.",
      email: "person@example.com",
      consent_version: "waitlist-v1",
    });
  });
});
