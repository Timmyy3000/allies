import type {
  AvatarViewModel,
  CloudClient,
  CloudError,
  PreparedAvatarViewModel,
} from "@allies/cloud-client";

import type { RunCloudOperation } from "../session/web-session";

export const AVATAR_CONTENT_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;
export const MAX_AVATAR_BYTES = 5 * 1024 * 1024;
export const AVATAR_PUT_TIMEOUT_MS = 10_000;

export type AvatarContentType = (typeof AVATAR_CONTENT_TYPES)[number];

export interface AvatarFileMetadata {
  contentType: AvatarContentType;
  size: number;
}

export interface AvatarUploadDependencies {
  client: Pick<CloudClient, "prepareAvatarUpload" | "completeAvatar">;
  runCloudOperation: RunCloudOperation;
  fetch?: typeof globalThis.fetch;
  signal?: AbortSignal;
}

function cloudError(kind: CloudError["kind"], code?: string): CloudError {
  return { kind, ...(code ? { code } : {}) };
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw cloudError("aborted");
}

export function validateAvatarFile(file: Blob): AvatarFileMetadata {
  const contentType = file.type.trim().toLowerCase();
  if (!AVATAR_CONTENT_TYPES.includes(contentType as AvatarContentType)) {
    throw cloudError("unsupported-media", "avatar_invalid");
  }
  if (file.size < 1) throw cloudError("validation", "avatar_invalid");
  if (file.size > MAX_AVATAR_BYTES) throw cloudError("too-large", "avatar_invalid");
  return { contentType: contentType as AvatarContentType, size: file.size };
}

export async function hashAvatarFile(file: Blob, signal?: AbortSignal): Promise<string> {
  throwIfAborted(signal);
  try {
    const digest = await globalThis.crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    throwIfAborted(signal);
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  } catch (error) {
    if (typeof error === "object" && error !== null && "kind" in error) throw error;
    throw cloudError("contract");
  }
}

export async function putAvatarFile(
  file: Blob,
  prepared: PreparedAvatarViewModel,
  options: { fetch?: typeof globalThis.fetch; signal?: AbortSignal } = {},
): Promise<void> {
  const fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
  const callerSignal = options.signal;
  throwIfAborted(callerSignal);
  const controller = new AbortController();
  let abortCause: "caller" | "timeout" | null = null;
  let rejectAbort: ((error: CloudError) => void) | undefined;
  const abortPromise = new Promise<never>((_resolve, reject) => {
    rejectAbort = reject;
  });

  const abort = (cause: "caller" | "timeout") => {
    if (abortCause !== null) return;
    abortCause = cause;
    controller.abort(cause === "caller" ? callerSignal?.reason : undefined);
    rejectAbort?.(cloudError(cause === "caller" ? "aborted" : "timeout"));
  };
  const onCallerAbort = () => abort("caller");
  if (callerSignal?.aborted) abort("caller");
  else callerSignal?.addEventListener("abort", onCallerAbort, { once: true });
  const timer = setTimeout(() => abort("timeout"), AVATAR_PUT_TIMEOUT_MS);

  try {
    if (abortCause === "caller") throw cloudError("aborted");
    const fetchPromise = Promise.resolve().then(() => {
      if (abortCause === "caller") throw cloudError("aborted");
      return fetchImpl(prepared.uploadUrl, {
        method: "PUT",
        headers: prepared.headers,
        body: file,
        credentials: "omit",
        signal: controller.signal,
      });
    });
    const response = await Promise.race([fetchPromise, abortPromise]);
    if (abortCause === "caller") throw cloudError("aborted");
    if (abortCause === "timeout") throw cloudError("timeout");
    if (!response.ok) throw { ...cloudError("network"), status: response.status } satisfies CloudError;
  } catch (error) {
    if (abortCause === "caller") throw cloudError("aborted");
    if (abortCause === "timeout") throw cloudError("timeout");
    if (typeof error === "object" && error !== null && "kind" in error) throw error;
    throw cloudError("network");
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener("abort", onCallerAbort);
  }
}

export async function uploadAvatar(file: Blob, dependencies: AvatarUploadDependencies): Promise<AvatarViewModel> {
  const metadata = validateAvatarFile(file);
  throwIfAborted(dependencies.signal);
  const sha256 = await hashAvatarFile(file, dependencies.signal);
  throwIfAborted(dependencies.signal);

  const prepared = await dependencies.runCloudOperation(
    (signal) => dependencies.client.prepareAvatarUpload({ ...metadata, sha256 }, signal),
    { csrf: true, signal: dependencies.signal },
  );
  const preparationExpiry = Date.parse(prepared.expiresAt);
  if (!Number.isFinite(preparationExpiry)) throw cloudError("contract");
  if (preparationExpiry <= Date.now()) throw cloudError("conflict", "avatar_upload_expired");

  await putAvatarFile(file, prepared, { fetch: dependencies.fetch, signal: dependencies.signal });
  return dependencies.runCloudOperation(
    (signal) => dependencies.client.completeAvatar(prepared.assetId, signal),
    { csrf: true, signal: dependencies.signal },
  );
}
