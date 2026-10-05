import { z } from "zod";
import type { CloudClientOptions } from "./client";
import { normalizeCloudError } from "./errors";
import { parsePublicCloudUrl } from "./environment";
import { createControlledFetch } from "./transport";

export const MAX_FILE_BYTES = 25_000_000;
export const MAX_MESSAGE_FILE_BYTES = 50_000_000;
export const FILE_EXTENSIONS =
  "jpg jpeg png gif webp heic heif pdf doc docx xls xlsx csv ppt pptx txt md markdown json html htm css xml yaml yml toml js jsx ts tsx py rb go rs java c h cpp hpp cs sh sql".split(
    " ",
  );
export const fileStateSchema = z.enum([
  "pending",
  "receiving",
  "validating",
  "ready",
  "retained",
  "failed",
  "rejected",
  "cleanup_pending",
  "deleted",
]);
export const preparationSchema = z.enum([
  "none",
  "uploading",
  "failed",
  "ready",
  "needs_retry",
  "cancelled",
]);
export const messageFileSchema = z.object({
  id: z.uuid(),
  name: z.string().min(1).max(255),
  size: z.number().int().min(1).max(MAX_FILE_BYTES),
  state: fileStateSchema,
});
export const publicationSchema = z.object({
  publication_id: z.uuid(),
  revision: z.number().int().positive(),
  state: z.enum([
    "uploading",
    "validating",
    "ready",
    "failed",
    "retry_pending",
    "cancelled",
  ]),
  files: z
    .array(
      messageFileSchema.extend({
        type: z.string().optional(),
        open_path: z.string().optional(),
      }),
    )
    .max(10),
  retryable: z.boolean(),
});
const fileManifestSchema = z.object({
  client_id: z.uuid(),
  name: z
    .string()
    .min(1)
    .max(255)
    .regex(/^[^\\/\x00-\x1f\x7f]+$/),
  size: z.number().int().min(1).max(MAX_FILE_BYTES),
  sha256: z.string().regex(/^[0-9a-f]{64}$/),
});
const fileMessageSchema = z.object({
  id: z.uuid(),
  status: z.enum([
    "queued",
    "in_progress",
    "awaiting_action",
    "completed",
    "failed",
    "stopped",
  ]),
  preparation: preparationSchema,
  revision: z.number().int().nonnegative(),
});
const uploadSchema = z.object({
  id: z.uuid(),
  state: fileStateSchema,
  generation: z.number().int().positive(),
});
const reservationSchema = z.object({
  message: fileMessageSchema.extend({ sequence: z.number().int().positive() }),
  files: z.array(uploadSchema).min(1).max(10),
  replayed: z.boolean(),
});
const draftSchema = z.object({
  id: z.uuid(),
  content: z.string(),
  files: z
    .array(z.object({ id: z.uuid(), name: z.string(), state: fileStateSchema }))
    .max(10),
});
const metadataSchema = messageFileSchema.extend({
  type: z.string(),
  preview_kind: z.enum(["image", "pdf", "text", "none"]),
  open_path: z.string(),
});
export type FileManifest = z.infer<typeof fileManifestSchema>;
export type MessageFile = z.infer<typeof messageFileSchema>;
export type FilePublication = z.infer<typeof publicationSchema>;
export type FileReservation = z.infer<typeof reservationSchema>;
export type FileMetadata = z.infer<typeof metadataSchema>;

export function validateSelectedFiles(
  files: readonly { name: string; size: number }[],
): void {
  if (
    files.length > 10 ||
    files.reduce((sum, file) => sum + file.size, 0) > MAX_MESSAGE_FILE_BYTES
  )
    throw new Error("Choose up to 10 files and 50 MB altogether.");
  for (const file of files) {
    if (
      !Number.isSafeInteger(file.size) ||
      file.size < 1 ||
      file.size > MAX_FILE_BYTES
    )
      throw new Error(
        "Each file must contain data and be no larger than 25 MB.",
      );
    if (
      file.name.length > 255 ||
      /[\\/\x00-\x1f\x7f]/.test(file.name) ||
      !FILE_EXTENSIONS.includes(
        file.name.split(".").at(-1)?.toLowerCase() ?? "",
      )
    )
      throw new Error(
        "That file type or name isn’t supported. Choose a photo, document, or text file.",
      );
  }
}

export function createFileClient(options: CloudClientOptions) {
  const base = parsePublicCloudUrl(options.baseUrl);
  const fetcher = createControlledFetch({
    fetch: options.fetch ?? globalThis.fetch.bind(globalThis),
    prepareRequest: options.prepareRequest,
    timeoutMs: 120_000,
  });
  const download = createControlledFetch({
    fetch: options.fetch ?? globalThis.fetch.bind(globalThis),
    prepareRequest: options.prepareRequest,
    timeoutMs: 120_000,
    maxJsonBytes: MAX_FILE_BYTES,
  });
  const segment = (id: string) => encodeURIComponent(z.uuid().parse(id));
  const workspace = (w: string) => `/api/v1/workspaces/${segment(w)}`;
  const conversation = (w: string, c: string) =>
    `${workspace(w)}/conversations/${segment(c)}`;
  const file = (w: string, a: string, f: string) =>
    `${workspace(w)}/allies/${segment(a)}/files/${segment(f)}`;
  async function request<T>(
    path: string,
    schema: z.ZodType<T>,
    method = "GET",
    body?: unknown,
    signal?: AbortSignal,
    key?: string,
  ): Promise<T> {
    const response = await fetcher(
      new Request(`${base}${path}`, {
        method,
        signal,
        headers: {
          "Content-Type": "application/json",
          ...(key
            ? {
                "Idempotency-Key": z
                  .string()
                  .min(16)
                  .max(128)
                  .regex(/^[^\r\n\x00]+$/)
                  .parse(key),
              }
            : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    );
    let json: unknown;
    try {
      json = await response.json();
    } catch {
      throw { kind: "contract" };
    }
    if (!response.ok) throw normalizeCloudError(response.status, json);
    const parsed = z
      .object({ status: z.literal("success"), data: schema })
      .safeParse(json);
    if (!parsed.success) throw { kind: "contract" };
    return parsed.data.data;
  }
  return {
    reserve(
      w: string,
      c: string,
      content: string,
      files: FileManifest[],
      key: string,
      signal?: AbortSignal,
    ) {
      validateSelectedFiles(files);
      const body = z
        .object({
          content: z.string().max(16_000),
          files: z.array(fileManifestSchema).min(1).max(10),
        })
        .parse({ content, files });
      return request(
        `${conversation(w, c)}/file-messages`,
        reservationSchema,
        "POST",
        body,
        signal,
        key,
      );
    },
    async upload(
      w: string,
      a: string,
      f: string,
      generation: number,
      blob: Blob,
      signal?: AbortSignal,
      onProgress?: (percent: number) => void,
    ) {
      if (blob.size < 1 || blob.size > MAX_FILE_BYTES)
        throw { kind: "bad-request" };
      const url = `${base}${file(w, a, f)}/content?generation=${z.number().int().positive().parse(generation)}`;
      const uploadFetch: typeof fetch =
        typeof XMLHttpRequest === "undefined" || options.fetch
          ? (options.fetch ?? globalThis.fetch.bind(globalThis))
          : async (input, init) => {
              const req = new Request(input, init);
              return new Promise<Response>((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                const abort = () => {
                  xhr.abort();
                  reject({ kind: "aborted" });
                };
                if (req.signal.aborted) {
                  reject({ kind: "aborted" });
                  return;
                }
                xhr.open("PUT", req.url);
                xhr.withCredentials = req.credentials === "include";
                xhr.timeout = 120_000;
                req.headers.forEach((value, name) =>
                  xhr.setRequestHeader(name, value),
                );
                xhr.upload.onprogress = (e) => {
                  if (e.lengthComputable)
                    onProgress?.(
                      Math.min(99, Math.round((e.loaded / e.total) * 100)),
                    );
                };
                xhr.onload = () => {
                  req.signal.removeEventListener("abort", abort);
                  resolve(
                    new Response(xhr.responseText, {
                      status: xhr.status,
                      headers: { "Content-Type": "application/json" },
                    }),
                  );
                };
                xhr.onerror = xhr.ontimeout = () => {
                  req.signal.removeEventListener("abort", abort);
                  reject({ kind: "network" });
                };
                req.signal.addEventListener("abort", abort, { once: true });
                xhr.send(blob);
              });
            };
      const send = createControlledFetch({
        fetch: uploadFetch,
        prepareRequest: options.prepareRequest,
        timeoutMs: 125_000,
      });
      const response = await send(
        new Request(url, {
          method: "PUT",
          signal,
          headers: { "Content-Type": "application/octet-stream" },
          body: blob,
        }),
      );
      const data = await response.json();
      if (!response.ok) throw normalizeCloudError(response.status, data);
      const parsed = z
        .object({ status: z.literal("success"), data: uploadSchema })
        .safeParse(data);
      if (
        !parsed.success ||
        parsed.data.data.id !== f ||
        parsed.data.data.generation !== generation
      )
        throw { kind: "contract" };
      onProgress?.(100);
      return parsed.data.data;
    },
    async retry(
      w: string,
      a: string,
      f: string,
      generation: number,
      signal?: AbortSignal,
    ) {
      const result = await request(
        `${file(w, a, f)}/retry`,
        uploadSchema,
        "POST",
        { generation: z.number().int().positive().parse(generation) },
        signal,
      );
      if (result.id !== f || result.generation !== generation + 1)
        throw { kind: "contract" };
      return result;
    },
    remove(
      w: string,
      c: string,
      m: string,
      f: string,
      revision: number,
      signal?: AbortSignal,
    ) {
      return request(
        `${conversation(w, c)}/messages/${segment(m)}/files/${segment(f)}?revision=${z.number().int().nonnegative().parse(revision)}`,
        fileMessageSchema,
        "DELETE",
        undefined,
        signal,
      );
    },
    send(
      w: string,
      c: string,
      m: string,
      revision: number,
      signal?: AbortSignal,
    ) {
      return request(
        `${conversation(w, c)}/messages/${segment(m)}/send-files`,
        fileMessageSchema,
        "POST",
        { revision },
        signal,
      );
    },
    cancel(
      w: string,
      c: string,
      m: string,
      revision: number,
      signal?: AbortSignal,
    ) {
      return request(
        `${conversation(w, c)}/messages/${segment(m)}/cancel-files`,
        z.object({ message: fileMessageSchema, draft: draftSchema }),
        "POST",
        { revision },
        signal,
      );
    },
    async metadata(w: string, a: string, f: string, signal?: AbortSignal) {
      const result = await request(
        file(w, a, f),
        metadataSchema,
        "GET",
        undefined,
        signal,
      );
      if (result.id !== f || result.open_path !== `/files/${f}`)
        throw { kind: "contract" };
      return result;
    },
    async content(
      w: string,
      a: string,
      f: string,
      preview: boolean,
      signal?: AbortSignal,
    ) {
      const response = await download(
        new Request(
          `${base}${file(w, a, f)}/${preview ? "preview" : "download"}`,
          { signal },
        ),
      );
      if (!response.ok)
        throw normalizeCloudError(
          response.status,
          await response.json().catch(() => null),
        );
      return response.blob();
    },
    retryPublication(
      w: string,
      a: string,
      m: string,
      p: string,
      revision: number,
      signal?: AbortSignal,
    ) {
      return request(
        `${workspace(w)}/allies/${segment(a)}/messages/${segment(m)}/publications/${segment(p)}/retry`,
        publicationSchema,
        "POST",
        { revision },
        signal,
      );
    },
  };
}
