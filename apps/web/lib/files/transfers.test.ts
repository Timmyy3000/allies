import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  CloudClient,
  FileReservation,
  MessageViewModel,
} from "@allies/cloud-client";
import {
  FileTransfers,
  fileTransferStorage,
  readSavedTransfers,
  resetFileTransferStorageForTests,
  type FileTransfer,
} from "./transfers";

const w = "11111111-1111-4111-8111-111111111111",
  a = "22222222-2222-4222-8222-222222222222",
  id = "33333333-3333-4333-8333-333333333333",
  remote = "44444444-4444-4444-8444-444444444444";
const scope = `user:${w}:${a}`;
function fixture() {
  const file = new File(["hello"], "notes.txt", { type: "text/plain" });
  const reservation: FileReservation = {
    message: {
      id,
      sequence: 1,
      status: "queued",
      preparation: "uploading",
      revision: 1,
    },
    files: [{ id: remote, generation: 1, state: "pending" }],
    replayed: false,
  };
  let message: MessageViewModel = {
    id,
    sequence: 1,
    sender: "user",
    content: "",
    status: "queued",
    queueState: "unclaimed",
    preparation: "uploading",
    revision: 1,
    createdAt: new Date().toISOString(),
    files: [{ id: remote, name: file.name, size: file.size, state: "pending" }],
  };
  const api = {
    reserve: vi.fn(async () => structuredClone(reservation)),
    upload: vi.fn(async () => {
      message = {
        ...message,
        preparation: "ready",
        files: message.files!.map((f) => ({ ...f, state: "ready" })),
      };
      return { id: remote, generation: 1, state: "validating" };
    }),
    retry: vi.fn(async () => ({ id: remote, generation: 2, state: "pending" })),
    send: vi.fn(async () => ({ ...reservation.message, revision: 2 })),
    cancel: vi.fn(async () => ({
      message: { ...reservation.message, preparation: "cancelled" },
      draft: { id, content: "", files: [] },
    })),
  };
  const client = {
    files: api,
    getConversation: vi.fn(async () => ({
      messages: [structuredClone(message)],
    })),
  } as unknown as CloudClient;
  const saved = new Map<string, FileTransfer>();
  const storage = {
    persist: vi.fn(async (record: FileTransfer) => {
      saved.set(record.id, {
        ...record,
        files: record.files.map((f) => ({ ...f })),
      });
    }),
    load: vi.fn(async () => [...saved.values()]),
    erase: vi.fn(async (key: string) => {
      saved.delete(key);
    }),
    reclaim: vi.fn(async (expected: FileTransfer) => {
      const current = saved.get(expected.id);
      if (
        current?.phase !== "ready" ||
        current.scope !== expected.scope ||
        current.key !== expected.key ||
        current.createdAt !== expected.createdAt ||
        current.reservation?.message.id !== expected.reservation?.message.id
      ) return false;
      saved.delete(expected.id);
      return true;
    }),
  };
  const manager = new FileTransfers(
    client,
    (operation) => operation(),
    storage,
  );
  const prepare = () =>
    manager.prepare(scope, w, a, a, "", [
      { id, file, name: file.name, size: file.size },
    ]);
  return {
    manager,
    api,
    client,
    storage,
    saved,
    prepare,
    setMessage: (next: Partial<MessageViewModel>) => {
      message = { ...message, ...next };
    },
  };
}
describe("file send recovery", () => {
  it("releases removed previews only after the last draft or transfer stops using them", async () => {
    const f = fixture();
    const record = await f.prepare();
    const file = record.files[0];
    file.src = "blob:preview";
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    try {
      f.manager.drafts.set(scope, [file]);
      f.manager.releasePreview(file);
      expect(revoke).not.toHaveBeenCalled();
      f.manager.drafts.set(scope, []);
      f.manager.releasePreview(file);
      expect(revoke).not.toHaveBeenCalled();
      record.phase = "ready";
      await f.manager.discard(record.id);
      expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:preview");
      revoke.mockClear();
      f.manager.releasePreview({ ...file, src: "blob:removed-draft" });
      expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:removed-draft");
    } finally {
      revoke.mockRestore();
    }
  });
  it("persists before reservation and waits for server readiness", async () => {
    const f = fixture(),
      record = await f.prepare();
    expect(f.storage.persist).toHaveBeenCalled();
    expect(f.api.reserve).not.toHaveBeenCalled();
    await f.manager.admit(record.id);
    await f.manager.upload(record.id, false);
    expect(f.api.upload).toHaveBeenCalledOnce();
    expect(record.phase).toBe("ready");
    expect(f.api.send).not.toHaveBeenCalled();
  });
  it("keeps successful bytes and uses a new generation only for failed files", async () => {
    const f = fixture(),
      record = await f.prepare();
    f.setMessage({
      preparation: "failed",
      revision: 2,
      files: [{ id: remote, name: "notes.txt", size: 5, state: "failed" }],
    });
    await f.manager.upload(record.id, true);
    expect(f.api.retry).toHaveBeenCalledOnce();
    expect(f.api.upload).toHaveBeenCalledWith(
      w,
      a,
      remote,
      2,
      expect.any(File),
      undefined,
      expect.any(Function),
    );
    expect(f.api.send).toHaveBeenCalledOnce();
  });
  it("restores interrupted sends without silently uploading", async () => {
    const f = fixture(),
      record = await f.prepare();
    const restored = new FileTransfers(
      f.client,
      (operation) => operation(),
      f.storage,
    );
    await restored.restore(scope);
    await restored.admit(record.id);
    expect(restored.find(record.id)?.phase).toBe("failed");
    expect(f.api.upload).not.toHaveBeenCalled();
    expect(f.api.reserve).toHaveBeenCalledWith(
      w,
      a,
      "",
      expect.any(Array),
      record.key,
      undefined,
    );
  });
  it("preserves files when the backend does not supply its file contract", async () => {
    const f = fixture(),
      record = await f.prepare();
    f.setMessage({ files: undefined });
    await f.manager.upload(record.id, false);
    expect(record.phase).toBe("failed");
    expect(record.files).toHaveLength(1);
    expect(f.api.upload).not.toHaveBeenCalled();
  });
  it("does not restore a draft when server cancellation is rejected", async () => {
    const f = fixture(),
      record = await f.prepare();
    f.api.cancel.mockRejectedValueOnce({ kind: "conflict" });
    await expect(f.manager.cancel(record.id)).rejects.toMatchObject({
      kind: "conflict",
    });
    expect(record.phase).not.toBe("cancelled");
  });
  it("retains a confirmed cancelled draft across refresh", async () => {
    const f = fixture(),
      record = await f.prepare();
    const recovered = await f.manager.cancel(record.id);
    expect(recovered.files[0].file).toBeDefined();
    const restored = new FileTransfers(
      f.client,
      (operation) => operation(),
      f.storage,
    );
    await restored.restore(scope);
    expect(restored.find(record.id)?.phase).toBe("cancelled");
  });
  it("rejects persistence failure before any network admission", async () => {
    const f = fixture();
    f.storage.persist.mockRejectedValueOnce(new Error("disk full"));
    await expect(f.prepare()).rejects.toThrow("disk full");
    expect(f.api.reserve).not.toHaveBeenCalled();
  });
  it("uses the file's actual bytes when creating a manifest", async () => {
    const f = fixture();
    const record = await f.manager.prepare(scope, w, a, a, "", [
      { id, file: new File(["hello"], "notes.txt"), name: "notes.txt", size: 1 },
    ]);
    expect(record.files[0].size).toBe(5);
    expect(record.files[0].manifest.size).toBe(5);
  });
  it("accepts a valid five-file batch using actual bytes instead of stale metadata", async () => {
    const f = fixture();
    const files = Array.from({ length: 5 }, (_, index) => {
      const file = new File([new Uint8Array(500_000)], `notes-${index}.txt`);
      return { id: crypto.randomUUID(), file, name: file.name, size: 30_000_000 };
    });

    const record = await f.manager.prepare(scope, w, a, a, "", files);

    expect(record.files).toHaveLength(5);
    expect(record.files.reduce((total, file) => total + file.size, 0)).toBe(2_500_000);
  });
  it("keeps original selections when another tab cancels the server message", async () => {
    const f = fixture(),
      record = await f.prepare();
    f.setMessage({ preparation: "cancelled", files: [] });
    await f.manager.upload(record.id, true);
    expect(record.phase).toBe("cancelled");
    expect(record.files[0].file).toBeDefined();
    expect(f.api.upload).not.toHaveBeenCalled();
  });
  it("releases local bytes only after the server claims the message", async () => {
    const f = fixture(),
      record = await f.prepare();
    await f.manager.upload(record.id, false);
    const message = {
      id,
      status: "queued",
      queueState: "unclaimed",
    } as MessageViewModel;
    f.manager.observe([message]);
    expect(f.storage.erase).not.toHaveBeenCalled();
    f.manager.observe([{ ...message, queueState: "claimed" }]);
    await vi.waitFor(() => expect(f.manager.find(record.id)).toBeUndefined());
  });
  it.each(["failed", "stopped"] as const)(
    "preserves recoverable local bytes when the Cloud message is %s",
    async (status) => {
      const f = fixture();
      const record = await f.prepare();
      record.phase = "ready";
      await f.storage.persist(record);

      f.manager.observe([{ id, status, queueState: undefined } as MessageViewModel]);
      await Promise.resolve();

      expect(f.manager.find(record.id)).toBe(record);
      expect(f.saved.has(record.id)).toBe(true);
      expect(f.storage.reclaim).not.toHaveBeenCalled();
    },
  );
  it("does not reclaim a ready record changed by another tab after Cloud proof", async () => {
    const f = fixture();
    const record = await f.prepare();
    await f.manager.upload(record.id, false);
    f.saved.set(record.id, { ...f.saved.get(record.id)!, phase: "cancelled" });

    f.manager.observe([{ id, status: "queued", queueState: "claimed" } as MessageViewModel]);
    await vi.waitFor(() => expect(f.storage.reclaim).toHaveBeenCalled());

    expect(f.manager.find(record.id)).toBe(record);
    expect(f.saved.get(record.id)?.phase).toBe("cancelled");
  });
  it("validates saved scope and manifests before restoring private blobs", async () => {
    const f = fixture(),
      record = await f.prepare();
    expect(readSavedTransfers([record], scope)).toHaveLength(1);
    expect(
      readSavedTransfers(
        [
          { ...record, allyId: remote },
          { ...record, files: [{ ...record.files[0], size: 1 }] },
          {},
        ],
        scope,
      ),
    ).toHaveLength(0);
  });
  it("clears one Ally scope and fences late draft preparation", async () => {
    const f = fixture();
    const record = await f.prepare();
    f.manager.drafts.set(scope, [{ ...record.files[0], file: record.files[0].file }]);

    await f.manager.clearScope(scope);

    expect(f.manager.find(record.id)).toBeUndefined();
    expect(f.saved.has(record.id)).toBe(false);
    expect(f.manager.drafts.has(scope)).toBe(false);
    await expect(f.prepare()).rejects.toThrow("unavailable for this Ally");
  });
  it("reports persistent cleanup failure for explicit recovery", async () => {
    const f = fixture();
    const record = await f.prepare();
    f.storage.erase.mockRejectedValueOnce(new Error("disk full"));

    await expect(f.manager.clearScope(scope)).rejects.toThrow("could not be erased");
    expect(f.saved.has(record.id)).toBe(true);
    await f.manager.clearScope(scope);
    expect(f.saved.has(record.id)).toBe(false);
  });
});

type FakeRequest<T = unknown> = {
  result: T;
  error: DOMException | null;
  onsuccess: null | (() => void);
  onerror: null | (() => void);
  onblocked?: null | (() => void);
  onupgradeneeded?: null | (() => void);
};

function fakeRequest<T>(result: T): FakeRequest<T> {
  return { result, error: null, onsuccess: null, onerror: null };
}

function fakeDatabase(
  records: FileTransfer[] = [],
  options: { transactionError?: DOMException; abortAfterRead?: boolean; deleteError?: DOMException } = {},
) {
  const db = {
    objectStoreNames: { contains: () => true },
    close: vi.fn(),
    onversionchange: null as null | (() => void),
    onclose: null as null | (() => void),
    createObjectStore: vi.fn(),
    transaction: vi.fn(() => {
      if (options.transactionError) throw options.transactionError;
      const transaction = {
        error: null as DOMException | null,
        oncomplete: null as null | (() => void),
        onerror: null as null | (() => void),
        onabort: null as null | (() => void),
        abort: vi.fn(),
        objectStore: () => {
          const settle = (request: FakeRequest, result: unknown, failure?: DOMException) => {
            queueMicrotask(() => {
              request.result = result;
              request.error = failure ?? null;
              if (failure) request.onerror?.();
              else request.onsuccess?.();
              queueMicrotask(() => {
                if (options.abortAfterRead) {
                  transaction.error = new DOMException("aborted", "AbortError");
                  transaction.onabort?.();
                } else transaction.oncomplete?.();
              });
            });
          };
          return {
            getAll: () => {
              const request = fakeRequest<unknown[]>([]);
              settle(request, [...records]);
              return request;
            },
            get: (key: string) => {
              const request = fakeRequest<unknown>(undefined);
              settle(request, records.find((record) => record.id === key));
              return request;
            },
            put: (record: FileTransfer) => {
              const request = fakeRequest<unknown>(undefined);
              const index = records.findIndex((current) => current.id === record.id);
              if (index < 0) records.push(record);
              else records[index] = record;
              settle(request, record.id);
              return request;
            },
            delete: (key: string) => {
              const request = fakeRequest<unknown>(undefined);
              if (!options.deleteError) {
                const index = records.findIndex((record) => record.id === key);
                if (index >= 0) records.splice(index, 1);
              }
              settle(request, undefined, options.deleteError);
              return request;
            },
          };
        },
      };
      transaction.abort.mockImplementation(() => queueMicrotask(() => transaction.onabort?.()));
      return transaction;
    }),
  };
  return db;
}

function installOpenHarness() {
  const requests: FakeRequest<IDBDatabase>[] = [];
  const open = vi.fn(() => {
    const request = fakeRequest<IDBDatabase>(undefined as never);
    request.onblocked = null;
    request.onupgradeneeded = null;
    requests.push(request);
    return request as unknown as IDBOpenDBRequest;
  });
  vi.stubGlobal("indexedDB", { open });
  return { open, requests };
}

afterEach(() => {
  resetFileTransferStorageForTests();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("IndexedDB file transfer storage", () => {
  it("classifies blocked opens and closes a late successful connection", async () => {
    const harness = installOpenHarness();
    const pending = fileTransferStorage.load(scope);
    harness.requests[0].onblocked?.();
    await expect(pending).rejects.toMatchObject({ kind: "blocked" });

    const late = fakeDatabase();
    harness.requests[0].result = late as unknown as IDBDatabase;
    harness.requests[0].onsuccess?.();
    expect(late.close).toHaveBeenCalledOnce();
  });

  it("times out an open that never settles", async () => {
    vi.useFakeTimers();
    installOpenHarness();
    const pending = fileTransferStorage.load(scope);
    const rejection = expect(pending).rejects.toMatchObject({ kind: "blocked" });
    await vi.advanceTimersByTimeAsync(5_000);
    await rejection;
  });

  it("classifies unavailable and quota failures", async () => {
    vi.stubGlobal("indexedDB", { open: () => { throw new DOMException("denied", "SecurityError"); } });
    await expect(fileTransferStorage.load(scope)).rejects.toMatchObject({ kind: "unavailable" });
    resetFileTransferStorageForTests();

    const harness = installOpenHarness();
    const record = await fixture().prepare();
    const pending = fileTransferStorage.persist(record);
    harness.requests[0].result = fakeDatabase([], {
      transactionError: new DOMException("full", "QuotaExceededError"),
    }) as unknown as IDBDatabase;
    harness.requests[0].onsuccess?.();
    await expect(pending).rejects.toMatchObject({ kind: "quota" });
  });

  it("rejects a transaction abort after a successful read", async () => {
    const harness = installOpenHarness();
    const pending = fileTransferStorage.load(scope);
    harness.requests[0].result = fakeDatabase([], { abortAfterRead: true }) as unknown as IDBDatabase;
    harness.requests[0].onsuccess?.();
    await expect(pending).rejects.toMatchObject({ kind: "transaction" });
  });

  it("resets a closed connection and reopens on the next operation", async () => {
    const harness = installOpenHarness();
    const firstDb = fakeDatabase();
    const first = fileTransferStorage.load(scope);
    harness.requests[0].result = firstDb as unknown as IDBDatabase;
    harness.requests[0].onsuccess?.();
    await first;
    firstDb.onclose?.();

    const second = fileTransferStorage.load(scope);
    expect(harness.open).toHaveBeenCalledTimes(2);
    harness.requests[1].result = fakeDatabase() as unknown as IDBDatabase;
    harness.requests[1].onsuccess?.();
    await expect(second).resolves.toEqual([]);
  });

  it("keeps capacity admission atomic and reports failed erases", async () => {
    const record = await fixture().prepare();
    const full = Array.from({ length: 64 }, (_, index) => ({
      ...record,
      id: crypto.randomUUID(),
      key: `${record.key}-${index}`,
    }));
    let harness = installOpenHarness();
    let pending = fileTransferStorage.persist(record);
    const capacityDb = fakeDatabase(full);
    harness.requests[0].result = capacityDb as unknown as IDBDatabase;
    harness.requests[0].onsuccess?.();
    await expect(pending).rejects.toMatchObject({ kind: "capacity" });
    expect(capacityDb.transaction).toHaveBeenCalledWith("transfers", "readwrite");

    resetFileTransferStorageForTests();
    harness = installOpenHarness();
    pending = fileTransferStorage.erase(record.id);
    harness.requests[0].result = fakeDatabase([record], {
      deleteError: new DOMException("failed", "UnknownError"),
    }) as unknown as IDBDatabase;
    harness.requests[0].onsuccess?.();
    await expect(pending).rejects.toMatchObject({ kind: "transaction" });
  });
});
