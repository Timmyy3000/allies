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

let database: Promise<IDBDatabase> | undefined;
function db() {
  return (database ??= new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("allies-file-transfers", 1);
    request.onupgradeneeded = () =>
      request.result.createObjectStore("transfers", { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      database = undefined;
      reject(new Error("Allow browser storage before sending files."));
    };
  }));
}
async function persist(value: FileTransfer) {
  const connection = await db();
  await new Promise<void>((resolve, reject) => {
    const transaction = connection.transaction("transfers", "readwrite");
    const store = transaction.objectStore("transfers");
    const request = store.getAll();
    request.onsuccess = () => {
      const others = request.result.filter(
        (record: FileTransfer) => record.id !== value.id,
      );
      const bytes = [...others, value].reduce(
        (total: number, record: FileTransfer) =>
          total +
          (record.files ?? []).reduce(
            (sum, file) => sum + (file.file?.size ?? 0),
            0,
          ),
        0,
      );
      if (others.length >= 64 || bytes > 250_000_000) {
        transaction.abort();
        return;
      }
      store.put({
        ...value,
        files: value.files.map((file) => ({ ...file, src: undefined })),
      });
    };
    transaction.oncomplete = () => resolve();
    transaction.onerror = transaction.onabort = () =>
      reject(
        new Error(
          "Your file draft could not be saved. Finish or discard saved drafts, or free up browser storage and retry.",
        ),
      );
  });
}
async function load(scope: string): Promise<FileTransfer[]> {
  const connection = await db();
  return new Promise((resolve, reject) => {
    const request = connection
      .transaction("transfers")
      .objectStore("transfers")
      .getAll();
    request.onsuccess = () =>
      resolve(readSavedTransfers(request.result, scope));
    request.onerror = () =>
      reject(new Error("Your saved file drafts could not be read."));
  });
}
async function erase(id: string) {
  const connection = await db();
  await new Promise<void>((resolve, reject) => {
    const transaction = connection.transaction("transfers", "readwrite");
    transaction.objectStore("transfers").delete(id);
    transaction.oncomplete = () => resolve();
    transaction.onerror = transaction.onabort = () =>
      reject(new Error("The saved draft could not be removed."));
  });
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
  private clearing = new Set<string>();
  private clearedScopes = new Set<string>();
  readonly drafts = new Map<string, SelectedFile[]>();
  constructor(
    private client: CloudClient,
    private run: RunCloudOperation,
    private storage = { persist, load, erase },
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
    await this.storage.persist(record);
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
    let loadFailed = false;
    let persistedRecords: FileTransfer[] = [];
    try {
      if (alreadyCleared) persistedRecords = await this.storage.load(scope);
      else await this.restore(scope);
    } catch {
      loadFailed = true;
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
    if (loadFailed || eraseResults.some((result) => result.status === "rejected")) {
      throw new Error("Some saved Ally file drafts could not be erased from this browser.");
    }
  }
  async prepare(
    scope: string,
    workspaceId: string,
    allyId: string,
    conversationId: string,
    content: string,
    files: SelectedFile[],
  ): Promise<FileTransfer> {
    await this.restore(scope);
    if (this.clearedScopes.has(scope)) {
      throw new Error("File drafts are unavailable for this Ally.");
    }
    validateSelectedFiles(files);
    if (this.records.filter((r) => r.scope === scope).length >= 10)
      throw new Error(
        "Finish or discard a saved file draft before adding another.",
      );
    if (!files.length || files.some((f) => !f.file))
      throw new Error("Choose the files again before sending.");
    const entries: TransferFile[] = [];
    for (const item of files)
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
  observe(messages: readonly MessageViewModel[]) {
    for (const record of this.records) {
      const message = messages.find(
        (m) => m.id === record.reservation?.message.id,
      );
      if (
        record.phase !== "ready" ||
        !message ||
        (message.status === "queued" && message.queueState !== "claimed") ||
        this.clearing.has(record.id)
      )
        continue;
      this.clearing.add(record.id);
      void this.discard(record.id)
        .catch(() => undefined)
        .finally(() => this.clearing.delete(record.id));
    }
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
