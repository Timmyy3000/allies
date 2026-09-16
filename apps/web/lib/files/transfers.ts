import {
  validateSelectedFiles,
  type CloudClient,
  type FileManifest,
  type FileReservation,
  type MessageViewModel,
} from "@allies/cloud-client";
import type { RunCloudOperation } from "../session/web-session";
import { z } from "zod";

export type SelectedFile = {
  id: string;
  name: string;
  size: number;
  file?: File;
  src?: string;
};
export type TransferFile = SelectedFile & {
  manifest: FileManifest;
  remoteId?: string;
  generation?: number;
  state: string;
  progress: number;
};
export type FileTransfer = {
  id: string;
  scope: string;
  workspaceId: string;
  allyId: string;
  conversationId: string;
  content: string;
  key: string;
  files: TransferFile[];
  reservation?: FileReservation;
  phase:
    | "pending"
    | "uploading"
    | "checking"
    | "failed"
    | "ready"
    | "cancelled";
  manifests?: FileManifest[];
  error?: string;
  createdAt: number;
};

export type FileStorageFailureKind =
  | "capacity"
  | "quota"
  | "unavailable"
  | "blocked"
  | "transaction";

export class FileStorageError extends Error {
  readonly name = "FileStorageError";
  constructor(
    readonly kind: FileStorageFailureKind,
    message: string,
  ) {
    super(message);
  }
}

export function fileStorageFailureKind(
  error: unknown,
): FileStorageFailureKind | undefined {
  return error instanceof FileStorageError
    ? error.kind
    : typeof error === "object" && error !== null && "kind" in error
      ? (["capacity", "quota", "unavailable", "blocked", "transaction"] as const).find(
          (kind) => (error as { kind?: unknown }).kind === kind,
        )
      : undefined;
}

const manifestSchema = z.object({
  client_id: z.uuid(),
  name: z.string().min(1).max(255),
  size: z.number().int().positive().max(25_000_000),
  sha256: z.string().regex(/^[0-9a-f]{64}$/),
});
const savedTransferSchema = z.object({
  id: z.uuid(),
  scope: z.string().max(512),
  workspaceId: z.uuid(),
  allyId: z.uuid(),
  conversationId: z.uuid(),
  content: z.string().max(16_000),
  key: z.string().min(16).max(128),
  createdAt: z.number().finite(),
  phase: z.enum([
    "pending",
    "uploading",
    "checking",
    "failed",
    "ready",
    "cancelled",
  ]),
  error: z.string().optional(),
  files: z
    .array(
      z.object({
        id: z.uuid(),
        name: z.string().max(255),
        size: z.number().int().positive().max(25_000_000),
        file: z.instanceof(File).optional(),
        manifest: manifestSchema,
        remoteId: z.uuid().optional(),
        generation: z.number().int().positive().optional(),
        state: z.string(),
        progress: z.number().min(0).max(100),
      }),
    )
    .max(10),
  manifests: z.array(manifestSchema).min(1).max(10).optional(),
  reservation: z
    .object({
      message: z.object({
        id: z.uuid(),
        sequence: z.number().int().positive(),
        status: z.enum([
          "queued",
          "in_progress",
          "awaiting_action",
          "completed",
          "failed",
          "stopped",
        ]),
        preparation: z.enum([
          "none",
          "uploading",
          "failed",
          "ready",
          "needs_retry",
          "cancelled",
        ]),
        revision: z.number().int().nonnegative(),
      }),
      files: z
        .array(
          z.object({
            id: z.uuid(),
            generation: z.number().int().positive(),
            state: z.enum([
              "pending",
              "receiving",
              "validating",
              "ready",
              "retained",
              "failed",
              "rejected",
              "cleanup_pending",
              "deleted",
            ]),
          }),
        )
        .max(10),
      replayed: z.boolean(),
    })
    .optional(),
});
export function readSavedTransfers(
  values: unknown[],
  scope: string,
): FileTransfer[] {
  return values.flatMap((value) => {
    const parsed = savedTransferSchema.safeParse(value);
    if (!parsed.success || parsed.data.scope !== scope) return [];
    const record = parsed.data;
    if (
      scope.split(":").slice(-2).join(":") !==
        `${record.workspaceId}:${record.allyId}` ||
      record.files.some(
        (f) =>
          f.id !== f.manifest.client_id ||
          f.name !== f.manifest.name ||
          f.size !== f.manifest.size ||
          (f.file && f.file.size !== f.size),
      )
    )
      return [];
    return [record];
  });
}

const DATABASE_NAME = "allies-file-transfers";
const MAX_DATABASE_RECORDS = 64;
const MAX_DATABASE_BYTES = 250_000_000;
const OPEN_TIMEOUT_MS = 5_000;
let database: Promise<IDBDatabase> | undefined;
let connection: IDBDatabase | undefined;

function failureMessage(
  kind: FileStorageFailureKind,
  operation: "save" | "read" | "remove" | "open",
) {
  if (kind === "capacity")
    return "Finish or discard a saved file draft before adding another.";
  if (kind === "quota")
    return "Your file draft could not be saved. Free browser storage and retry.";
  if (kind === "unavailable")
    return "Browser storage is unavailable. Allow storage and retry before sending files.";
  if (kind === "blocked")
    return "Browser storage is busy in another tab. Close other tabs and retry.";
  if (operation === "read") return "Your saved file drafts could not be read. Retry to continue.";
  if (operation === "remove") return "The saved draft could not be removed. Retry to continue.";
  return "Your file draft could not be saved. Retry to continue; your files remain in the composer.";
}

function isNamedError(error: unknown, names: readonly string[]) {
  return typeof error === "object" && error !== null &&
    names.includes((error as { name?: string }).name ?? "");
}

function classifyStorageError(
  error: unknown,
  operation: "save" | "read" | "remove" | "open",
  fallback: FileStorageFailureKind = "transaction",
) {
  const existing = fileStorageFailureKind(error);
  const kind = existing ??
    (isNamedError(error, ["QuotaExceededError"])
      ? "quota"
      : isNamedError(error, ["SecurityError", "NotSupportedError", "InvalidStateError"])
        ? "unavailable"
        : fallback);
  return error instanceof FileStorageError && error.kind === kind
    ? error
    : new FileStorageError(kind, failureMessage(kind, operation));
}

function resetDatabase(target?: IDBDatabase) {
  if (target && connection !== target) return;
  const current = connection;
  connection = undefined;
  database = undefined;
  if (current) {
    current.onversionchange = null;
    current.close();
  }
}

function db() {
  if (database) return database;
  const pending = new Promise<IDBDatabase>((resolve, reject) => {
    let request: IDBOpenDBRequest;
    let settled = false;
    const finish = (error: unknown, fallback: FileStorageFailureKind = "transaction") => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      database = undefined;
      reject(classifyStorageError(error, "open", fallback));
    };
    const timer = setTimeout(() => finish(null, "blocked"), OPEN_TIMEOUT_MS);
    try {
      if (typeof indexedDB === "undefined") throw new Error("IndexedDB is unavailable");
      request = indexedDB.open(DATABASE_NAME, 1);
    } catch (error) {
      finish(error, "unavailable");
      return;
    }
    request.onupgradeneeded = () => {
      try {
        if (!request.result.objectStoreNames.contains("transfers"))
          request.result.createObjectStore("transfers", { keyPath: "id" });
      } catch (error) {
        finish(error);
      }
    };
    request.onblocked = () => finish(null, "blocked");
    request.onerror = () => finish(request.error);
    request.onsuccess = () => {
      const opened = request.result;
      if (settled) {
        opened.close();
        return;
      }
      settled = true;
      clearTimeout(timer);
      connection = opened;
      opened.onversionchange = () => resetDatabase(opened);
      (opened as IDBDatabase & { onclose?: (() => void) | null }).onclose = () =>
        resetDatabase(opened);
      resolve(opened);
    };
  });
  database = pending;
  void pending.catch(() => {
    if (database === pending) database = undefined;
  });
  return pending;
}

async function persist(value: FileTransfer) {
  let active: IDBDatabase | undefined;
  try {
    active = await db();
    await new Promise<void>((resolve, reject) => {
      let settled = false;
      let failure: FileStorageError | undefined;
      const finish = (error?: unknown) => {
        if (settled) return;
        settled = true;
        if (error) reject(error);
        else resolve();
      };
      let transaction: IDBTransaction;
      try {
        transaction = active!.transaction("transfers", "readwrite");
        const store = transaction.objectStore("transfers");
        const request = store.getAll();
        request.onsuccess = () => {
          const others = request.result.filter(
            (record: FileTransfer) => record.id !== value.id,
          );
          const bytes = [...others, value].reduce(
            (total: number, record: FileTransfer) =>
              total + (record.files ?? []).reduce(
                (sum, file) => sum + (file.file?.size ?? 0),
                0,
              ),
            0,
          );
          if (others.length >= MAX_DATABASE_RECORDS || bytes > MAX_DATABASE_BYTES) {
            failure = new FileStorageError("capacity", failureMessage("capacity", "save"));
            try { transaction.abort(); } catch { finish(failure); }
            return;
          }
          try {
            const write = store.put({
              ...value,
              files: value.files.map((file) => ({ ...file, src: undefined })),
            });
            write.onerror = () => {
              failure = classifyStorageError(write.error, "save");
            };
          } catch (error) {
            failure = classifyStorageError(error, "save");
            finish(failure);
          }
        };
        request.onerror = () => {
          failure = classifyStorageError(request.error, "save");
          finish(failure);
        };
        transaction.oncomplete = () => finish();
        transaction.onerror = () => finish(failure ?? classifyStorageError(transaction.error, "save"));
        transaction.onabort = () => finish(failure ?? classifyStorageError(transaction.error, "save"));
      } catch (error) {
        finish(classifyStorageError(error, "save"));
      }
    });
  } catch (error) {
    resetDatabase(active);
    throw classifyStorageError(error, "save");
  }
}

async function load(scope: string): Promise<FileTransfer[]> {
  let active: IDBDatabase | undefined;
  try {
    active = await db();
    return await new Promise((resolve, reject) => {
      let settled = false;
      let result: FileTransfer[] | undefined;
      const finish = (error?: unknown, value?: FileTransfer[]) => {
        if (settled) return;
        settled = true;
        if (error) reject(error);
        else resolve(value ?? []);
      };
      try {
        const transaction = active!.transaction("transfers");
        const request = transaction.objectStore("transfers").getAll();
        request.onsuccess = () => {
          result = readSavedTransfers(request.result, scope);
        };
        request.onerror = () => finish(classifyStorageError(request.error, "read"));
        transaction.oncomplete = () => finish(undefined, result ?? []);
        transaction.onerror = () => finish(classifyStorageError(transaction.error, "read"));
        transaction.onabort = () => finish(classifyStorageError(transaction.error, "read"));
      } catch (error) {
        finish(classifyStorageError(error, "read"));
      }
    });
  } catch (error) {
    resetDatabase(active);
    throw classifyStorageError(error, "read");
  }
}

async function erase(id: string) {
  let active: IDBDatabase | undefined;
  try {
    active = await db();
    await new Promise<void>((resolve, reject) => {
      let settled = false;
      const finish = (error?: unknown) => {
        if (settled) return;
        settled = true;
        if (error) reject(error);
        else resolve();
      };
      try {
        const transaction = active!.transaction("transfers", "readwrite");
        const request = transaction.objectStore("transfers").delete(id);
        request.onerror = () => finish(classifyStorageError(request.error, "remove"));
        transaction.oncomplete = () => finish();
        transaction.onerror = () => finish(classifyStorageError(transaction.error, "remove"));
        transaction.onabort = () => finish(classifyStorageError(transaction.error, "remove"));
      } catch (error) {
        finish(classifyStorageError(error, "remove"));
      }
    });
  } catch (error) {
    resetDatabase(active);
    throw classifyStorageError(error, "remove");
  }
}

async function reclaim(expected: FileTransfer): Promise<boolean> {
  let active: IDBDatabase | undefined;
  try {
    active = await db();
    return await new Promise<boolean>((resolve, reject) => {
      let settled = false;
      let removed = false;
      const finish = (error?: unknown) => {
        if (settled) return;
        settled = true;
        if (error) reject(error);
        else resolve(removed);
      };
      try {
        const transaction = active!.transaction("transfers", "readwrite");
        const store = transaction.objectStore("transfers");
        const request = store.get(expected.id);
        request.onsuccess = () => {
          const current = request.result as FileTransfer | undefined;
          if (
            current?.phase !== "ready" ||
            current.scope !== expected.scope ||
            current.key !== expected.key ||
            current.createdAt !== expected.createdAt ||
            current.reservation?.message.id !== expected.reservation?.message.id
          ) return;
          const deletion = store.delete(expected.id);
          deletion.onsuccess = () => { removed = true; };
          deletion.onerror = () => finish(classifyStorageError(deletion.error, "remove"));
        };
        request.onerror = () => finish(classifyStorageError(request.error, "remove"));
        transaction.oncomplete = () => finish();
        transaction.onerror = () => finish(classifyStorageError(transaction.error, "remove"));
        transaction.onabort = () => finish(classifyStorageError(transaction.error, "remove"));
      } catch (error) {
        finish(classifyStorageError(error, "remove"));
      }
    });
  } catch (error) {
    resetDatabase(active);
    throw classifyStorageError(error, "remove");
  }
}

export const fileTransferStorage = { persist, load, erase, reclaim };
export function resetFileTransferStorageForTests() {
  resetDatabase();
}
export function selectedFile(file: File): SelectedFile {
  return {
    id: crypto.randomUUID(),
    name: file.name,
    size: file.size,
    file,
    ...(file.type.startsWith("image/")
      ? { src: URL.createObjectURL(file) }
      : {}),
  };
}
export async function hashFile(file: Blob): Promise<string> {
  if (!crypto.subtle)
    throw new Error(
      "File sending needs a secure connection. Open Allies using HTTPS.",
    );
  return [
    ...new Uint8Array(
      await crypto.subtle.digest("SHA-256", await file.arrayBuffer()),
    ),
  ]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export class FileTransfers {
  private records: FileTransfer[] = [];
  private listeners = new Set<() => void>();
  private operations = new Map<string, AbortController>();
  private running = new Map<string, Promise<void>>();
  private loaded = new Map<string, Promise<void>>();
  private reconciling = new Map<string, Promise<void>>();
  private clearing = new Set<string>();
  private clearedScopes = new Set<string>();
  readonly drafts = new Map<string, SelectedFile[]>();
  constructor(
    private client: CloudClient,
    private run: RunCloudOperation,
    private storage: {
      persist: typeof persist;
      load: typeof load;
      erase: typeof erase;
      reclaim?: typeof reclaim;
    } = fileTransferStorage,
  ) {}
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  snapshot = () => this.records;
  private emit() {
    this.records = [...this.records];
    this.listeners.forEach((listener) => listener());
  }
  private async save(record: FileTransfer) {
    if (this.clearedScopes.has(record.scope)) {
      this.records = this.records.filter((current) => current.id !== record.id);
      this.emit();
      return;
    }
    try {
      await this.storage.persist(record);
    } catch (error) {
      const failure = fileStorageFailureKind(error);
      if (!failure || !["capacity", "quota", "transaction"].includes(failure)) throw error;
      if (failure === "capacity" || failure === "quota") await this.reconcile(record.scope);
      await this.storage.persist(record);
    }
    const index = this.records.findIndex((r) => r.id === record.id);
    if (index < 0) this.records.push(record);
    else this.records[index] = record;
    this.emit();
  }
  async restore(scope: string) {
    if (this.clearedScopes.has(scope)) return;
    if (!this.loaded.has(scope))
      this.loaded.set(
        scope,
        this.storage
          .load(scope)
          .then((records) => {
            this.records.push(
              ...records
                .filter(
                  (r) => !this.records.some((current) => current.id === r.id),
                )
                .map((record) => ({
                  ...record,
                  phase:
                    record.phase === "ready" || record.phase === "cancelled"
                      ? record.phase
                      : ("failed" as const),
                  error:
                    record.phase === "ready" || record.phase === "cancelled"
                      ? undefined
                      : "Sending was interrupted. Retry to continue.",
                  files: record.files.map((file) => ({
                    ...file,
                    src: file.file?.type.startsWith("image/")
                      ? URL.createObjectURL(file.file)
                      : undefined,
                  })),
                })),
            );
            this.emit();
          })
          .catch((error) => {
            this.loaded.delete(scope);
            throw error;
          }),
      );
    await this.loaded.get(scope);
  }
  async clearScope(scope: string) {
    const alreadyCleared = this.clearedScopes.has(scope);
    let loadError: unknown;
    let persistedRecords: FileTransfer[] = [];
    try {
      if (alreadyCleared) persistedRecords = await this.storage.load(scope);
      else await this.restore(scope);
    } catch (error) {
      loadError = error;
    }
    this.clearedScopes.add(scope);
    this.drafts.delete(scope);
    const targetRecords = [
      ...this.records.filter((record) => record.scope === scope),
      ...persistedRecords.filter((record) => (
        record.scope === scope && !this.records.some((current) => current.id === record.id)
      )),
    ];
    targetRecords.forEach((record) => {
      this.operations.get(record.id)?.abort();
      record.files.forEach((file) => this.releasePreview(file));
    });
    this.records = this.records.filter((record) => record.scope !== scope);
    const eraseResults = await Promise.allSettled(targetRecords.map((record) => this.storage.erase(record.id)));
    this.emit();
    const eraseFailure = eraseResults.find(
      (result): result is PromiseRejectedResult => result.status === "rejected",
    )?.reason;
    if (loadError || eraseFailure) {
      const kind = fileStorageFailureKind(loadError ?? eraseFailure);
      throw kind
        ? new FileStorageError(
            kind,
            "Some saved Ally file drafts could not be erased from this browser. Retry to continue.",
          )
        : new Error("Some saved Ally file drafts could not be erased from this browser.");
    }
  }

  private async reconcile(scope: string) {
    const existing = this.reconciling.get(scope);
    if (existing) return existing;
    const task = this.reconcileScope(scope).finally(() => {
      if (this.reconciling.get(scope) === task) this.reconciling.delete(scope);
    });
    this.reconciling.set(scope, task);
    return task;
  }

  private async reconcileScope(scope: string) {
    const scopeParts = scope.split(":");
    const workspaceId = scopeParts.at(-2);
    const allyId = scopeParts.at(-1);
    if (!workspaceId || !allyId) return;
    const candidates = this.records.filter(
      (record) =>
        record.scope === scope &&
        record.workspaceId === workspaceId &&
        record.allyId === allyId &&
        record.phase === "ready" &&
        Boolean(record.reservation?.message.id),
    );
    const conversations = new Map<string, Promise<readonly MessageViewModel[]>>();
    const messagesFor = (record: FileTransfer) => {
      const key = `${record.workspaceId}:${record.conversationId}`;
      let result = conversations.get(key);
      if (!result) {
        result = this.run<readonly MessageViewModel[]>(
          (signal) =>
            this.client.getConversation(record.workspaceId, record.conversationId, {
              limit: 100,
              signal,
            }).then((conversation) => [
              ...conversation.messages,
              ...(conversation.queue ?? []),
            ]),
          { retryTransient: false },
        ).catch(() => []);
        conversations.set(key, result);
      }
      return result;
    };
    for (const record of candidates) {
      const messages = await messagesFor(record);
      const message = messages.find((item) => item.id === record.reservation?.message.id);
      if (message && this.isDisposableReadyMessage(message))
        await this.reclaimReady(record).catch(() => undefined);
    }
  }

  private isDisposableReadyMessage(message: MessageViewModel) {
    return message.queueState === "claimed" ||
      ["in_progress", "awaiting_action", "completed"].includes(message.status);
  }
  async prepare(
    scope: string,
    workspaceId: string,
    allyId: string,
    conversationId: string,
    content: string,
    files: SelectedFile[],
  ): Promise<FileTransfer> {
    if (!files.length || files.some((f) => !f.file))
      throw new Error("Choose the files again before sending.");
    const actualFiles = files.map((item) => ({ ...item, size: item.file!.size }));
    validateSelectedFiles(actualFiles);
    await this.restore(scope);
    if (this.clearedScopes.has(scope)) {
      throw new Error("File drafts are unavailable for this Ally.");
    }
    if (this.records.filter((r) => r.scope === scope).length >= 10) {
      await this.reconcile(scope);
    }
    if (this.records.filter((r) => r.scope === scope).length >= 10)
      throw new Error(
        "Finish or discard a saved file draft before adding another.",
      );
    const entries: TransferFile[] = [];
    for (const item of actualFiles)
      entries.push({
        ...item,
        state: "pending",
        progress: 0,
        manifest: {
          client_id: item.id,
          name: item.name,
          size: item.size,
          sha256: await hashFile(item.file!),
        },
      });
    const record: FileTransfer = {
      id: crypto.randomUUID(),
      scope,
      workspaceId,
      allyId,
      conversationId,
      content,
      key: `files-${crypto.randomUUID()}`,
      files: entries,
      manifests: entries.map((f) => f.manifest),
      phase: "pending",
      createdAt: Date.now(),
    };
    await this.save(record);
    return record;
  }
  find(id: string) {
    return this.records.find((record) => record.id === id);
  }
  setDraft(scope: string, files: SelectedFile[]) {
    if (files.length) this.drafts.set(scope, files);
    else this.drafts.delete(scope);
    this.emit();
  }
  observe(messages: readonly MessageViewModel[]) {
    for (const record of this.records) {
      const message = messages.find(
        (m) => m.id === record.reservation?.message.id,
      );
      if (
        record.phase !== "ready" ||
        !message ||
        !this.isDisposableReadyMessage(message) ||
        this.clearing.has(record.id)
      )
        continue;
      this.clearing.add(record.id);
      void this.reclaimReady(record)
        .catch(() => undefined)
        .finally(() => this.clearing.delete(record.id));
    }
  }
  private async reclaimReady(record: FileTransfer) {
    if (!this.storage.reclaim || !await this.storage.reclaim(record)) return;
    if (this.find(record.id) !== record || record.phase !== "ready") return;
    this.records = this.records.filter((current) => current !== record);
    const draft = this.drafts.get(record.scope);
    if (draft) {
      const consumed = new Set(record.files.map((file) => file.id));
      const remaining = draft.filter((file) => !consumed.has(file.id));
      if (remaining.length) this.drafts.set(record.scope, remaining);
      else this.drafts.delete(record.scope);
    }
    record.files.forEach((file) => this.releasePreview(file));
    this.emit();
  }
  async discard(id: string) {
    const record = this.find(id);
    if (!record || !["ready", "cancelled"].includes(record.phase))
      throw new Error(
        "Cancel the file message before discarding its saved draft.",
      );
    await this.storage.erase(id);
    this.records = this.records.filter((r) => r.id !== id);
    record.files.forEach((file) => this.releasePreview(file));
    this.emit();
  }
  releasePreview(file: SelectedFile) {
    if (!file.src) return;
    const retained = (entry: SelectedFile) => entry.src === file.src;
    if (
      this.records.some((record) => record.files.some(retained)) ||
      [...this.drafts.values()].some((draft) => draft.some(retained))
    )
      return;
    URL.revokeObjectURL(file.src);
  }
  private async reserve(record: FileTransfer, signal?: AbortSignal) {
    const manifests = record.manifests ?? record.files.map((f) => f.manifest);
    const result = await this.run(
      (s) =>
        this.client.files.reserve(
          record.workspaceId,
          record.conversationId,
          record.content,
          manifests,
          record.key,
          s,
        ),
      { csrf: true, signal },
    );
    if (result.files.length !== manifests.length)
      throw new Error("File reservation could not be verified.");
    record.reservation = result;
    record.files = record.files.map((f) => {
      const remote =
        result.files[
          manifests.findIndex((m) => m.client_id === f.manifest.client_id)
        ];
      return {
        ...f,
        remoteId: remote.id,
        generation: remote.generation,
        state: remote.state,
      };
    });
    await this.save(record);
    return result;
  }
  async admit(id: string): Promise<MessageViewModel> {
    const record = this.find(id);
    if (!record)
      throw new Error("Your file draft needs to be recovered before sending.");
    const result = await this.reserve(record);
    if (result.message.preparation === "cancelled")
      throw new Error("This file message was cancelled.");
    if (record.phase !== "failed") void this.upload(id, false);
    return {
      id: result.message.id,
      sender: "user",
      content: record.content,
      sequence: result.message.sequence,
      status: result.message.status,
      createdAt: new Date(record.createdAt).toISOString(),
      queueState: result.message.status === "queued" ? "unclaimed" : undefined,
      preparation: result.message.preparation,
      revision: result.message.revision,
      files: record.files.map((f) => ({
        id: f.remoteId!,
        name: f.name,
        size: f.size,
        state: f.state as "pending",
      })),
    };
  }
  async refresh(
    record: FileTransfer,
    signal?: AbortSignal,
  ): Promise<MessageViewModel> {
    const conversation = await this.run(
      (s) =>
        this.client.getConversation(record.workspaceId, record.conversationId, {
          limit: 100,
          signal: s,
        }),
      { signal },
    );
    const message = [
      ...conversation.messages,
      ...(conversation.queue ?? []),
    ].find((m) => m.id === record.reservation?.message.id);
    if (!message)
      throw new Error("We couldn’t find the latest file message. Try again.");
    if (
      !message.files ||
      message.revision === undefined ||
      message.preparation === undefined
    )
      throw new Error("File sending is unavailable on this Cloud version.");
    if (record.reservation)
      record.reservation.message = {
        ...record.reservation.message,
        status: message.status,
        preparation: message.preparation ?? "none",
        revision: message.revision ?? 0,
      };
    if (message.preparation !== "cancelled") {
      const previous = record.files;
      record.files = record.files
        .filter((f) =>
          message.files?.some((remote) => remote.id === f.remoteId),
        )
        .map((f) => ({
          ...f,
          state: message.files!.find((remote) => remote.id === f.remoteId)!
            .state,
        }));
      previous.forEach((file) => this.releasePreview(file));
    }
    await this.save(record);
    return message;
  }
  upload(id: string, retry: boolean): Promise<void> {
    const existing = this.running.get(id);
    if (existing) return existing;
    const task = Promise.resolve(
      typeof navigator !== "undefined" && navigator.locks
        ? navigator.locks.request(`allies-file-transfer:${id}`, () =>
            this.uploadFiles(id, retry),
          )
        : this.uploadFiles(id, retry),
    );
    this.running.set(id, task);
    void task
      .finally(() => {
        if (this.running.get(id) === task) this.running.delete(id);
      })
      .catch(() => undefined);
    return task;
  }
  private async uploadFiles(id: string, retry: boolean) {
    const record = this.find(id);
    if (!record || this.operations.has(id) || record.phase === "cancelled")
      return;
    const controller = new AbortController();
    this.operations.set(id, controller);
    try {
      record.phase = "uploading";
      record.error = undefined;
      await this.save(record);
      await this.reserve(record, controller.signal);
      let message = await this.refresh(record, controller.signal);
      if (message.preparation === "cancelled" || message.deletedAt) {
        record.phase = "cancelled";
        await this.save(record);
        return;
      }
      if (
        (message.preparation === "ready" && message.queueState === "claimed") ||
        message.status !== "queued"
      ) {
        record.phase = "ready";
        record.files.forEach((f) => {
          f.file = undefined;
        });
        await this.save(record);
        return;
      }
      for (const f of record.files) {
        if (controller.signal.aborted) return;
        if (["ready", "validating", "receiving"].includes(f.state)) continue;
        if (!f.file) throw new Error(`Choose ${f.name} again to continue.`);
        if (["failed", "rejected", "cleanup_pending"].includes(f.state)) {
          if (!retry)
            throw new Error("An upload failed. Retry the file or remove it.");
          const result = await this.run(
            (s) =>
              this.client.files.retry(
                record.workspaceId,
                record.allyId,
                f.remoteId!,
                f.generation!,
                s,
              ),
            { csrf: true, signal: controller.signal },
          );
          f.generation = result.generation;
          f.state = result.state;
          await this.save(record);
        }
        const result = await this.run(
          (s) =>
            this.client.files.upload(
              record.workspaceId,
              record.allyId,
              f.remoteId!,
              f.generation!,
              f.file!,
              s,
              (progress) => {
                f.progress = progress;
                this.emit();
              },
            ),
          { csrf: true, signal: controller.signal, retryTransient: false },
        );
        f.state = result.state;
        await this.save(record);
      }
      record.phase = "checking";
      await this.save(record);
      for (let attempt = 0; attempt < 60; attempt++) {
        message = await this.refresh(record, controller.signal);
        if (message.preparation === "cancelled" || message.deletedAt) {
          record.phase = "cancelled";
          await this.save(record);
          return;
        }
        if (
          record.files.some((f) =>
            ["failed", "rejected", "cleanup_pending", "deleted"].includes(
              f.state,
            ),
          )
        )
          throw new Error("A file could not be accepted. Retry or remove it.");
        if (
          record.files.length &&
          record.files.every((f) => f.state === "ready")
        ) {
          if (
            retry ||
            message.preparation === "needs_retry" ||
            (message.revision ?? 0) > 1
          )
            await this.run(
              (s) =>
                this.client.files.send(
                  record.workspaceId,
                  record.conversationId,
                  message.id,
                  message.revision!,
                  s,
                ),
              { csrf: true, signal: controller.signal },
            );
          record.phase = "ready";
          record.error = undefined;
          await this.save(record);
          return;
        }
        await new Promise<void>((resolve, reject) => {
          const abort = () => {
            clearTimeout(timer);
            reject({ kind: "aborted" });
          };
          const timer = setTimeout(() => {
            controller.signal.removeEventListener("abort", abort);
            resolve();
          }, 2000);
          controller.signal.addEventListener("abort", abort, { once: true });
          if (controller.signal.aborted) abort();
        });
      }
      throw new Error(
        "Files are still being checked. Retry to check their status.",
      );
    } catch (error) {
      if (!controller.signal.aborted) {
        record.phase = "failed";
        record.error =
          error instanceof Error
            ? error.message
            : "File sending needs attention. Retry to continue; accepted uploads are kept.";
        await this.save(record).catch(() => this.emit());
      }
    } finally {
      if (this.operations.get(id) === controller) this.operations.delete(id);
    }
  }
  async reselect(id: string, fileId: string, file: File) {
    const record = this.find(id),
      target = record?.files.find((f) => f.id === fileId);
    if (!record || !target) return;
    if (
      file.size !== target.size ||
      (await hashFile(file)) !== target.manifest.sha256
    )
      throw new Error(
        "Choose the original file so the message stays unchanged.",
      );
    target.file = file;
    await this.save(record);
  }
  async remove(id: string, fileId: string) {
    const record = this.find(id);
    if (!record || this.operations.has(id)) return;
    const message = await this.refresh(record),
      target = record.files.find((f) => f.id === fileId);
    if (!target) return;
    await this.run(
      (s) =>
        this.client.files.remove(
          record.workspaceId,
          record.conversationId,
          message.id,
          target.remoteId!,
          message.revision!,
          s,
        ),
      { csrf: true },
    );
    await this.refresh(record);
    record.phase = "failed";
    record.error = record.files.length
      ? "File removed. Retry sending when you’re ready."
      : "No files left. Cancel to restore your text.";
    await this.save(record);
  }
  async cancel(
    id: string,
  ): Promise<{ content: string; files: SelectedFile[] }> {
    const record = this.find(id);
    if (!record) throw new Error("File draft unavailable.");
    this.operations.get(id)?.abort();
    await this.running.get(id);
    if (!record.reservation) await this.reserve(record);
    const message = await this.refresh(record);
    await this.run(
      (s) =>
        this.client.files.cancel(
          record.workspaceId,
          record.conversationId,
          message.id,
          message.revision!,
          s,
        ),
      { csrf: true },
    );
    record.phase = "cancelled";
    record.error = undefined;
    await this.save(record);
    return {
      content: record.content,
      files: record.files.map((f) => ({ ...f, id: crypto.randomUUID() })),
    };
  }
}

const managers = new WeakMap<CloudClient, FileTransfers>();
export function fileTransfers(client: CloudClient, run: RunCloudOperation) {
  let manager = managers.get(client);
  if (!manager) {
    manager = new FileTransfers(client, run);
    managers.set(client, manager);
  }
  return manager;
}
