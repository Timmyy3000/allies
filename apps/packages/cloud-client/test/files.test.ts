import { describe, expect, it, vi } from "vitest";
import { createFileClient, validateSelectedFiles } from "../src/files";

const w = "11111111-1111-4111-8111-111111111111",
  a = "22222222-2222-4222-8222-222222222222",
  f = "33333333-3333-4333-8333-333333333333";
const manifest = {
  client_id: f,
  name: "notes.txt",
  size: 3,
  sha256: "a".repeat(64),
};
const success = (data: unknown) => Response.json({ status: "success", data });

describe("private file transport", () => {
  it("enforces decimal limits and rejects unsafe names, empty and unsupported files", () => {
    expect(() =>
      validateSelectedFiles([
        { name: "image.jpg", size: 25_000_000 },
        { name: "book.pdf", size: 25_000_000 },
      ]),
    ).not.toThrow();
    for (const item of [
      { name: "a.jpg", size: 25_000_001 },
      { name: "a.txt", size: 0 },
      { name: "a.txt", size: -1 },
      { name: "a.txt", size: NaN },
      { name: "../a.txt", size: 1 },
      { name: "a.exe", size: 1 },
    ])
      expect(() => validateSelectedFiles([item])).toThrow();
    expect(() =>
      validateSelectedFiles(
        Array.from({ length: 11 }, () => ({ name: "a.txt", size: 1 })),
      ),
    ).toThrow();
    expect(() =>
      validateSelectedFiles(
        Array.from({ length: 3 }, () => ({ name: "a.txt", size: 20_000_000 })),
      ),
    ).toThrow();
  });
  it("reserves with stable intent and uploads raw bytes using session preparation", async () => {
    const requests: Request[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      requests.push(request);
      return request.method === "POST"
        ? success({
            message: {
              id: a,
              sequence: 1,
              status: "queued",
              preparation: "uploading",
              revision: 1,
            },
            files: [{ id: f, state: "pending", generation: 1 }],
            replayed: false,
          })
        : success({ id: f, state: "validating", generation: 1 });
    });
    const client = createFileClient({
      baseUrl: "https://cloud.example",
      fetch,
      prepareRequest: (request) => {
        const headers = new Headers(request.headers);
        headers.set("X-CSRFToken", "test-token");
        return new Request(request, { credentials: "include", headers });
      },
    });
    await client.reserve(w, a, "", [manifest], "files-stable-intent");
    expect(requests[0].url).toBe(
      `https://cloud.example/api/v1/workspaces/${w}/conversations/${a}/file-messages`,
    );
    expect(requests[0].headers.get("Idempotency-Key")).toBe(
      "files-stable-intent",
    );
    expect(await requests[0].json()).toEqual({
      content: "",
      files: [manifest],
    });
    await client.upload(w, a, f, 1, new Blob(["abc"]));
    expect(requests[1].credentials).toBe("include");
    expect(requests[1].headers.get("X-CSRFToken")).toBe("test-token");
    expect(requests[1].headers.get("Content-Type")).toBe(
      "application/octet-stream",
    );
    expect(await requests[1].text()).toBe("abc");
  });
  it("rejects mismatched upload generations and private metadata identities", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        success({ id: f, state: "validating", generation: 2 }),
      )
      .mockResolvedValueOnce(
        success({
          id: a,
          name: "notes.txt",
          size: 3,
          state: "ready",
          type: "text/plain",
          preview_kind: "text",
          open_path: `/files/${a}`,
        }),
      );
    const client = createFileClient({
      baseUrl: "https://cloud.example",
      fetch,
    });
    await expect(
      client.upload(w, a, f, 1, new Blob(["abc"])),
    ).rejects.toMatchObject({ kind: "contract" });
    await expect(client.metadata(w, a, f)).rejects.toMatchObject({
      kind: "contract",
    });
  });
  it("retains revision fences and never follows file paths from response content", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const req = input as Request;
      expect(req.url).toContain(`/messages/${a}/send-files`);
      expect(await req.json()).toEqual({ revision: 7 });
      return success({
        id: a,
        status: "queued",
        preparation: "ready",
        revision: 8,
      });
    });
    await createFileClient({ baseUrl: "https://cloud.example", fetch }).send(
      w,
      a,
      a,
      7,
    );
  });
  it("rejects failed private retrieval and malformed successful envelopes", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ status: "error" }, { status: 403 }),
      )
      .mockResolvedValueOnce(success({}));
    const client = createFileClient({
      baseUrl: "https://cloud.example",
      fetch,
    });
    await expect(client.content(w, a, f, false)).rejects.toMatchObject({
      kind: "forbidden",
    });
    await expect(client.metadata(w, a, f)).rejects.toMatchObject({
      kind: "contract",
    });
  });
});
