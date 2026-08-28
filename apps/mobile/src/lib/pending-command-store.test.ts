import { describe, expect, it, vi } from 'vitest';

import {
  createPendingCommandStore,
  type PendingCommandCrypto,
  type PendingCreateCommand,
  type PendingMessageCommand,
} from './pending-command-store';

vi.mock('expo-crypto', () => ({
  AESEncryptionKey: { generate: vi.fn(), import: vi.fn() },
  AESSealedData: { fromCombined: vi.fn() },
  aesDecryptAsync: vi.fn(),
  aesEncryptAsync: vi.fn(),
}));

vi.mock('expo-file-system', () => ({
  File: class {
    exists = false;
    create() {}
    write() {}
    async move() {}
    delete() {}
    async bytes() {
      return new Uint8Array();
    }
  },
  Paths: { document: 'file:///documents' },
}));

vi.mock('expo-secure-store', () => ({
  getItemAsync: vi.fn(async () => null),
  setItemAsync: vi.fn(async () => undefined),
  deleteItemAsync: vi.fn(async () => undefined),
}));

function createMemoryDependencies() {
  let ciphertext: Uint8Array | null = null;
  let storedKey: string | null = null;
  let now = Date.parse('2026-08-28T00:00:00.000Z');
  let replacements = 0;
  let deletes = 0;

  const crypto: PendingCommandCrypto = {
    async generateKey() {
      return 'test-key';
    },
    async encrypt(plaintext, key) {
      return new TextEncoder().encode(`${key}:${plaintext}`);
    },
    async decrypt(encrypted, key) {
      const value = new TextDecoder().decode(encrypted);
      const prefix = `${key}:`;
      if (!value.startsWith(prefix)) throw new Error('invalid ciphertext');
      return value.slice(prefix.length);
    },
  };

  return {
    crypto,
    dependencies: {
      crypto,
      now: () => now,
      readCiphertext: async () => ciphertext,
      replaceCiphertext: async (next: Uint8Array) => {
        replacements += 1;
        ciphertext = next;
      },
      deleteCiphertext: async () => {
        deletes += 1;
        ciphertext = null;
      },
      readKey: async () => storedKey,
      writeKey: async (next: string) => {
        storedKey = next;
      },
      deleteKey: async () => {
        storedKey = null;
      },
    },
    setNow(value: number) {
      now = value;
    },
    getCiphertext() {
      return ciphertext;
    },
    getStoredKey() {
      return storedKey;
    },
    getReplacements() {
      return replacements;
    },
    getDeletes() {
      return deletes;
    },
  };
}

const createCommand: PendingCreateCommand = {
  kind: 'create',
  name: 'Maya',
  job: 'Partner',
  personality: 'Warm',
  appearance: { catalogVersion: 'v1', key: 'ghosty:fd304f' },
  onboardingAttempt: 'attempt-1',
  reply: 'Hello, Maya.',
  idempotencyKey: '00000000-0000-4000-8000-000000000001',
  createdAt: '2026-08-28T00:00:00.000Z',
  expiresAt: '2026-09-04T00:00:00.000Z',
};

const messageCommand: PendingMessageCommand = {
  kind: 'message',
  conversationId: 'conv-1',
  content: 'Keep this exact message.',
  idempotencyKey: '00000000-0000-4000-8000-000000000002',
  createdAt: '2026-08-28T00:00:00.000Z',
  boundUserId: 'user-1',
  boundWorkspaceId: 'workspace-1',
};

describe('pending command store', () => {
  it('keeps a create command exact, binds once, and removes it on a mismatch', async () => {
    const memory = createMemoryDependencies();
    const store = createPendingCommandStore(memory.dependencies);

    await store.saveCreate(createCommand);
    expect(await store.readCreate()).toEqual(createCommand);
    expect(memory.getCiphertext()).not.toEqual(new TextEncoder().encode(JSON.stringify(createCommand)));

    expect(await store.bindCreate('user-1', 'workspace-1')).toEqual({
      ...createCommand,
      boundUserId: 'user-1',
      boundWorkspaceId: 'workspace-1',
    });
    expect(await store.bindCreate('user-2', 'workspace-2')).toBeNull();
    expect(await store.readCreate()).toBeNull();
  });

  it('expires an unsubmitted create command after seven days', async () => {
    const memory = createMemoryDependencies();
    const store = createPendingCommandStore(memory.dependencies);

    await store.saveCreate(createCommand);
    memory.setNow(Date.parse('2026-09-04T00:00:00.001Z'));

    expect(await store.readCreate()).toBeNull();
    expect(memory.getCiphertext()).toBeNull();
  });

  it('preserves the current 4,000-character reply limit', async () => {
    const memory = createMemoryDependencies();
    const store = createPendingCommandStore(memory.dependencies);
    const maximum = { ...createCommand, reply: 'x'.repeat(4000) };

    await store.saveCreate(maximum);
    expect((await store.readCreate())?.reply).toHaveLength(4000);
    await expect(store.saveCreate({ ...maximum, reply: 'x'.repeat(4001) })).rejects.toThrow('Invalid pending command');
  });

  it('keeps one bound message per conversation and prevents cross-account reads', async () => {
    const memory = createMemoryDependencies();
    const store = createPendingCommandStore(memory.dependencies);

    await store.saveMessage(messageCommand);
    expect(await store.readMessage('conv-1', 'user-1', 'workspace-1')).toEqual(messageCommand);

    const replacement = { ...messageCommand, content: 'A later exact retry.' };
    await expect(store.saveMessage(replacement)).rejects.toThrow('another message is already pending');
    expect(await store.readMessage('conv-1', 'user-1', 'workspace-1')).toEqual(messageCommand);

    expect(await store.readMessage('conv-1', 'user-2', 'workspace-1')).toBeNull();
    expect(await store.readMessage('conv-1', 'user-1', 'workspace-1')).toBeNull();

    await store.clear();
    expect(await store.readMessage('conv-1', 'user-1', 'workspace-1')).toBeNull();
    expect(memory.getStoredKey()).toBeNull();
  });

  it('clears malformed decrypted data before returning it', async () => {
    const memory = createMemoryDependencies();
    const store = createPendingCommandStore(memory.dependencies);

    memory.dependencies.writeKey('test-key');
    memory.dependencies.replaceCiphertext(new TextEncoder().encode('test-key:{"version":1,"create":{"kind":"create"}}'));

    expect(await store.readCreate()).toBeNull();
    expect(memory.getCiphertext()).toBeNull();
    expect(memory.getDeletes()).toBeGreaterThan(0);
  });

  it('deletes ciphertext when its SecureStore key is missing', async () => {
    const memory = createMemoryDependencies();
    const store = createPendingCommandStore(memory.dependencies);
    await memory.dependencies.replaceCiphertext(new TextEncoder().encode('orphaned'));

    expect(await store.readCreate()).toBeNull();
    expect(memory.getCiphertext()).toBeNull();
  });
});
