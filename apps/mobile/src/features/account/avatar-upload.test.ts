import { describe, expect, it, vi } from 'vitest';

import type { AvatarViewModel, CloudClient, PreparedAvatarViewModel } from '@allies/cloud-client';

import { MAX_AVATAR_BYTES, uploadAvatar } from './avatar-upload';

const preparedUpload: PreparedAvatarViewModel = {
  assetId: 'avt_example',
  uploadUrl: 'https://uploads.example/avatar',
  headers: {
    'Content-Type': 'image/png',
    'x-upload-signature': 'signature-value',
  },
  expiresAt: '2026-08-21T12:00:00Z',
};

const completedAvatar: AvatarViewModel = {
  assetId: 'avt_example',
  url: 'https://media.example/avatar',
  expiresAt: '2026-08-21T12:00:00Z',
};

function createClient(events: string[] = []) {
  return {
    prepareAvatarUpload: vi.fn(async (input: { contentType: string; size: number; sha256: string }) => {
      events.push(`prepare:${input.contentType}:${input.size}:${input.sha256}`);
      return preparedUpload;
    }),
    completeAvatar: vi.fn(async () => {
      events.push('complete');
      return completedAvatar;
    }),
  } satisfies Pick<CloudClient, 'prepareAvatarUpload' | 'completeAvatar'>;
}

describe('uploadAvatar', () => {
  it('hashes the actual bytes, uploads with exact signed headers, and completes afterward', async () => {
    const bytes = new Uint8Array([1, 2, 3]);
    const events: string[] = [];
    const client = createClient(events);
    const fetch = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      events.push('put');
      expect(init?.method).toBe('PUT');
      expect(init?.headers).toBe(preparedUpload.headers);
      expect(init?.credentials).toBe('omit');
      expect(init?.body).toBe(bytes);
      expect((init?.headers as Record<string, string>).authorization).toBeUndefined();
      return new Response(null, { status: 200 });
    });

    await expect(uploadAvatar({
      client,
      contentType: 'image/png',
      readBytes: async () => bytes,
      hash: async () => 'ABCDEF'.repeat(10) + 'ABCD',
      fetch,
    })).resolves.toBe(completedAvatar);

    expect(client.prepareAvatarUpload).toHaveBeenCalledWith({
      contentType: 'image/png',
      size: 3,
      sha256: 'abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd',
    }, undefined);
    expect(fetch).toHaveBeenCalledWith(preparedUpload.uploadUrl, expect.any(Object));
    expect(events).toEqual([
      'prepare:image/png:3:abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd',
      'put',
      'complete',
    ]);
  });

  it.each(['', '   ', 'application/pdf'])('rejects a non-image content type: %s', async (contentType) => {
    const readBytes = vi.fn(async () => new Uint8Array([1]));

    await expect(uploadAvatar({
      client: createClient(),
      contentType,
      readBytes,
      hash: async () => 'a'.repeat(64),
      fetch: vi.fn(),
    })).rejects.toThrow('image content type');
    expect(readBytes).not.toHaveBeenCalled();
  });

  it('rejects bytes over 10 MiB before preparing an upload', async () => {
    const client = createClient();
    const readBytes = vi.fn(async () => new Uint8Array(MAX_AVATAR_BYTES + 1));

    await expect(uploadAvatar({
      client,
      contentType: 'image/jpeg',
      readBytes,
      hash: vi.fn(async () => 'a'.repeat(64)),
      fetch: vi.fn(),
    })).rejects.toThrow('10 MiB');
    expect(client.prepareAvatarUpload).not.toHaveBeenCalled();
  });

  it('rejects an empty file before preparing an upload', async () => {
    const client = createClient();

    await expect(uploadAvatar({
      client,
      contentType: 'image/png',
      readBytes: async () => new Uint8Array(),
      hash: vi.fn(async () => 'a'.repeat(64)),
      fetch: vi.fn(),
    })).rejects.toThrow('empty');
    expect(client.prepareAvatarUpload).not.toHaveBeenCalled();
  });

  it('does not complete an avatar when the direct upload fails', async () => {
    const client = createClient();
    const fetch = vi.fn(async () => new Response(null, { status: 403 }));

    await expect(uploadAvatar({
      client,
      contentType: 'image/webp',
      readBytes: async () => new Uint8Array([1]),
      hash: async () => 'a'.repeat(64),
      fetch,
    })).rejects.toThrow('Avatar upload failed');
    expect(client.completeAvatar).not.toHaveBeenCalled();
  });
});
