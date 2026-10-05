import { afterEach, describe, expect, it, vi } from "vitest";

import type { AvatarViewModel, CloudClient, PreparedAvatarViewModel } from "@allies/cloud-client";
import type { RunCloudOperation } from "../session/web-session";

import {
  AVATAR_PUT_TIMEOUT_MS,
  MAX_AVATAR_BYTES,
  hashAvatarFile,
  putAvatarFile,
  uploadAvatar,
  validateAvatarFile,
} from "./avatar-upload";

const avatar: AvatarViewModel = {
  assetId: "avt_example",
  url: "https://media.example/avatar",
  expiresAt: "2099-01-01T00:00:00Z",
};

const prepared: PreparedAvatarViewModel = {
  assetId: "avt_example",
  uploadUrl: "https://uploads.example/avatar",
  headers: { "Content-Type": "image/png", "Content-Length": "6" },
  expiresAt: "2099-01-01T00:00:00Z",
};

const runImmediately = vi.fn(async <T>(operation: (signal?: AbortSignal) => Promise<T>) => operation()) as unknown as RunCloudOperation;

function makeClient(overrides: Partial<Pick<CloudClient, "prepareAvatarUpload" | "completeAvatar">> = {}) {
  return {
    prepareAvatarUpload: vi.fn(async () => prepared),
    completeAvatar: vi.fn(async () => avatar),
    ...overrides,
  } as Pick<CloudClient, "prepareAvatarUpload" | "completeAvatar">;
}

function makeFile(type = "image/png", contents = "avatar") {
  return new File([contents], "avatar.png", { type });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("avatar file validation and hashing", () => {
  it("accepts JPEG, PNG, and WebP within the Cloud size limit", () => {
    expect(validateAvatarFile(makeFile("image/jpeg")).contentType).toBe("image/jpeg");
    expect(validateAvatarFile(makeFile("image/png")).contentType).toBe("image/png");
    expect(validateAvatarFile(makeFile("image/webp")).contentType).toBe("image/webp");
    expect(validateAvatarFile(new File([new Uint8Array(MAX_AVATAR_BYTES)], "avatar.png", { type: "image/png" })))
      .toMatchObject({ size: MAX_AVATAR_BYTES });
  });

  it("rejects unsupported types and sizes before any request", () => {
    expect(() => validateAvatarFile(makeFile("image/gif"))).toThrowError(
      expect.objectContaining({ kind: "unsupported-media" }),
    );
    expect(() => validateAvatarFile(new File([], "avatar.png", { type: "image/png" }))).toThrowError(
      expect.objectContaining({ kind: "validation" }),
    );
    expect(() => validateAvatarFile(new File([new Uint8Array(MAX_AVATAR_BYTES + 1)], "avatar.png", { type: "image/png" })))
      .toThrowError(expect.objectContaining({ kind: "too-large" }));
  });

  it("computes a lowercase SHA-256 digest with Web Crypto", async () => {
    await expect(hashAvatarFile(makeFile("image/png", "avatar"))).resolves.toBe(
      "87bbe879c7a5f5784a70384bb49fa9513a6a3fbe4c2d388635e3c87611c03fae",
    );
  });
});

describe("uploadAvatar", () => {
  it("prepares, PUTs with exact headers and omitted credentials, then completes", async () => {
    const client = makeClient();
    const put = vi.fn<typeof fetch>(async (_url, init) => {
      expect(init?.method).toBe("PUT");
      expect(init?.headers).toBe(prepared.headers);
      expect(init?.credentials).toBe("omit");
      return new Response(null, { status: 200 });
    });

    await expect(uploadAvatar(makeFile(), { client, runCloudOperation: runImmediately, fetch: put })).resolves.toEqual(avatar);
    expect(client.prepareAvatarUpload).toHaveBeenCalledWith(
      expect.objectContaining({ contentType: "image/png", size: 6, sha256: expect.any(String) }),
      undefined,
    );
    expect(put).toHaveBeenCalledOnce();
    expect(client.completeAvatar).toHaveBeenCalledWith("avt_example", undefined);
  });

  it("does not complete after a failed object-store PUT", async () => {
    const client = makeClient();
    const put = vi.fn<typeof fetch>(async () => { throw new TypeError("network down"); });

    await expect(uploadAvatar(makeFile(), { client, runCloudOperation: runImmediately, fetch: put })).rejects.toMatchObject({
      kind: "network",
    });
    expect(client.completeAvatar).not.toHaveBeenCalled();
  });

  it("rejects expired preparation without touching object storage", async () => {
    const client = makeClient({
      prepareAvatarUpload: vi.fn(async () => ({ ...prepared, expiresAt: "2000-01-01T00:00:00Z" })),
    });
    const put = vi.fn<typeof fetch>();

    await expect(uploadAvatar(makeFile(), { client, runCloudOperation: runImmediately, fetch: put })).rejects.toMatchObject({
      kind: "conflict",
      code: "avatar_upload_expired",
    });
    expect(put).not.toHaveBeenCalled();
    expect(client.completeAvatar).not.toHaveBeenCalled();
  });

  it("times out a stalled PUT at ten seconds and cleans its timer", async () => {
    vi.useFakeTimers();
    const put = vi.fn<typeof fetch>(() => new Promise<Response>(() => undefined));
    const operation = putAvatarFile(makeFile(), prepared, { fetch: put }).then(
      () => null,
      (error) => error,
    );

    await Promise.resolve();
    expect(put).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(AVATAR_PUT_TIMEOUT_MS - 1);
    expect(put).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1);
    await expect(operation).resolves.toMatchObject({ kind: "timeout" });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("lets caller cancellation win over a later timeout and cleans its listener", async () => {
    vi.useFakeTimers();
    const caller = new AbortController();
    const put = vi.fn<typeof fetch>(() => new Promise<Response>(() => undefined));
    const operation = putAvatarFile(makeFile(), prepared, { fetch: put, signal: caller.signal });

    await Promise.resolve();
    expect(put).toHaveBeenCalledOnce();
    caller.abort();
    await expect(operation).rejects.toMatchObject({ kind: "aborted" });
    await vi.advanceTimersByTimeAsync(AVATAR_PUT_TIMEOUT_MS);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("rejects an already-aborted PUT before creating fetch or timeout work", async () => {
    vi.useFakeTimers();
    const caller = new AbortController();
    const put = vi.fn<typeof fetch>();
    caller.abort();

    await expect(putAvatarFile(makeFile(), prepared, { fetch: put, signal: caller.signal }))
      .rejects.toMatchObject({ kind: "aborted" });

    expect(put).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps timeout as the first abort cause when caller cancellation arrives later", async () => {
    vi.useFakeTimers();
    const caller = new AbortController();
    const put = vi.fn<typeof fetch>(() => new Promise<Response>(() => undefined));
    const operation = putAvatarFile(makeFile(), prepared, { fetch: put, signal: caller.signal }).then(
      () => null,
      (error) => error,
    );

    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(AVATAR_PUT_TIMEOUT_MS);
    caller.abort();
    await expect(operation).resolves.toMatchObject({ kind: "timeout" });
    expect(vi.getTimerCount()).toBe(0);
  });
});
