import { describe, expect, it, vi } from 'vitest';

import type { AvatarViewModel, CloudClient, PreparedAvatarViewModel } from '@allies/cloud-client';

import { MAX_AVATAR_BYTES, uploadAvatar } from './avatar-upload';

const preparedUpload: PreparedAvatarViewModel = {
  assetId: 'avt_example',
  uploadUrl: 'https://uploads.example/avatar',
  headers: { 'Content-Type': 'image/png', 'x-upload-signature': 'signature-value' },
  expiresAt: '2026-08-21T12:00:00Z',
};
const completedAvatar: AvatarViewModel = {
  assetId: 'avt_example',
  url: 'https://media.example/avatar',
  expiresAt: '2026-08-21T12:00:00Z',
};

function createClient() {
  return {
    prepareAvatarUpload: vi.fn(async () => preparedUpload),
    completeAvatar: vi.fn(async () => completedAvatar),
  } satisfies Pick<CloudClient, 'prepareAvatarUpload' | 'completeAvatar'>;
}

describe('uploadAvatar', () => {
  it('hashes bytes, uploads with signed headers, and completes', async () => {
    const bytes = new Uint8Array([1, 2, 3]);
    const client = createClient();
    const fetch = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe('PUT');
      expect(init?.headers).toBe(preparedUpload.headers);
      expect(init?.credentials).toBe('omit');
      expect(init?.body).toBe(bytes);
      return new Response(null, { status: 200 });
    });

    await expect(uploadAvatar({
      client,
      contentType: 'image/png',
      readBytes: async () => bytes,
      hash: async () => 'abcdef'.repeat(10) + 'abcd',
      fetch,
    })).resolves.toBe(completedAvatar);
    expect(client.prepareAvatarUpload).toHaveBeenCalledWith({
      contentType: 'image/png',
      size: 3,
      sha256: 'abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd',
    }, undefined);
  });

  it('rejects invalid content types before reading the file', async () => {
    const readBytes = vi.fn(async () => new Uint8Array([1]));
    await expect(uploadAvatar({
      client: createClient(),
      contentType: 'application/pdf',
      readBytes,
      hash: async () => 'a'.repeat(64),
      fetch: vi.fn(),
    })).rejects.toThrow('image content type');
    expect(readBytes).not.toHaveBeenCalled();
  });

  it('rejects oversized files before preparing an upload', async () => {
    const client = createClient();
    await expect(uploadAvatar({
      client,
      contentType: 'image/jpeg',
      size: MAX_AVATAR_BYTES + 1,
      readBytes: vi.fn(),
      hash: vi.fn(),
      fetch: vi.fn(),
    })).rejects.toThrow('10 MiB');
    expect(client.prepareAvatarUpload).not.toHaveBeenCalled();
  });
});
