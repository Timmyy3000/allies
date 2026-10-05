import type { AvatarViewModel, CloudClient } from '@allies/cloud-client';

export const MAX_AVATAR_BYTES = 10 * 1024 * 1024;

type AvatarCloudClient = Pick<CloudClient, 'prepareAvatarUpload' | 'completeAvatar'>;

export interface AvatarUploadOptions {
  client: AvatarCloudClient;
  contentType: string;
  size?: number | null;
  readBytes: () => Promise<Uint8Array>;
  hash: (bytes: Uint8Array) => Promise<string> | string;
  fetch?: typeof globalThis.fetch;
  signal?: AbortSignal;
}

export async function uploadAvatar(options: AvatarUploadOptions): Promise<AvatarViewModel> {
  const contentType = validateContentType(options.contentType);
  if (options.size != null && options.size > MAX_AVATAR_BYTES) throw new RangeError('Avatar file must not exceed 10 MiB');

  const bytes = await options.readBytes();
  if (!(bytes instanceof Uint8Array)) throw new TypeError('Avatar bytes must be a Uint8Array');
  if (bytes.byteLength === 0) throw new RangeError('Avatar file must not be empty');
  if (bytes.byteLength > MAX_AVATAR_BYTES) throw new RangeError('Avatar file must not exceed 10 MiB');

  const sha256 = validateHash(await options.hash(bytes));
  const prepared = await options.client.prepareAvatarUpload({
    contentType,
    size: bytes.byteLength,
    sha256,
  }, options.signal);
  const response = await (options.fetch ?? globalThis.fetch)(prepared.uploadUrl, {
    method: 'PUT',
    headers: prepared.headers,
    body: bytes as unknown as BodyInit,
    credentials: 'omit',
    signal: options.signal,
  });
  if (!response.ok) throw new Error('Avatar upload failed');
  return options.client.completeAvatar(prepared.assetId, options.signal);
}

function validateContentType(value: string): string {
  const contentType = value.trim();
  if (!/^image\/[a-z0-9][a-z0-9!#$&^_.+-]*$/iu.test(contentType)) {
    throw new TypeError('Avatar content type must be a non-empty image content type');
  }
  return contentType;
}

function validateHash(value: string): string {
  const sha256 = value.toLowerCase();
  if (!/^[a-f0-9]{64}$/u.test(sha256)) throw new TypeError('Avatar hash must be a 64-character hexadecimal SHA-256 value');
  return sha256;
}
