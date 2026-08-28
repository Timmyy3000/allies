import { AESEncryptionKey, AESSealedData, aesDecryptAsync, aesEncryptAsync } from 'expo-crypto';
import { File, Paths } from 'expo-file-system';
import * as SecureStore from 'expo-secure-store';
import { z } from 'zod';

const PENDING_COMMAND_KEY = 'allies.pending-command.aes-key';
const PENDING_COMMAND_FILE = 'allies-pending-commands.enc';
const PENDING_COMMAND_TEMP_FILE = `${PENDING_COMMAND_FILE}.tmp`;
const PENDING_COMMAND_VERSION = 1;
const MAX_MESSAGE_LENGTH = 4000;
const idempotencyKeySchema = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
const timestampSchema = z.iso.datetime({ offset: true });
const appearanceSchema = z.object({
  catalogVersion: z.string().min(1),
  key: z.string().regex(/^[a-z][a-z0-9_-]*:[0-9a-f]{6}$/i),
});
const identitySchema = z.string().min(1);

const createCommandSchema = z
  .object({
    kind: z.literal('create'),
    name: z.string().min(1),
    job: z.string().min(1),
    personality: z.string().min(1),
    appearance: appearanceSchema,
    onboardingAttempt: z.string().min(1),
    reply: z.string().min(1).max(MAX_MESSAGE_LENGTH),
    idempotencyKey: idempotencyKeySchema,
    createdAt: timestampSchema,
    expiresAt: timestampSchema,
    boundUserId: identitySchema.optional(),
    boundWorkspaceId: identitySchema.optional(),
  })
  .superRefine((command, context) => {
    if (Boolean(command.boundUserId) !== Boolean(command.boundWorkspaceId)) {
      context.addIssue({ code: 'custom', message: 'create command binding must be complete' });
    }
  });

const messageCommandSchema = z.object({
  kind: z.literal('message'),
  conversationId: identitySchema,
  content: z.string().min(1).max(MAX_MESSAGE_LENGTH),
  idempotencyKey: idempotencyKeySchema,
  createdAt: timestampSchema,
  boundUserId: identitySchema,
  boundWorkspaceId: identitySchema,
});

const pendingStateSchema = z.object({
  version: z.literal(PENDING_COMMAND_VERSION),
  create: createCommandSchema.optional(),
  messages: z.record(z.string(), messageCommandSchema),
});

export interface PendingCreateCommand {
  kind: 'create';
  name: string;
  job: string;
  personality: string;
  appearance: { catalogVersion: string; key: string };
  onboardingAttempt: string;
  reply: string;
  idempotencyKey: string;
  createdAt: string;
  expiresAt: string;
  boundUserId?: string;
  boundWorkspaceId?: string;
}

export interface PendingMessageCommand {
  kind: 'message';
  conversationId: string;
  content: string;
  idempotencyKey: string;
  createdAt: string;
  boundUserId: string;
  boundWorkspaceId: string;
}

export interface PendingCommandCrypto {
  generateKey(): Promise<string>;
  encrypt(plaintext: string, key: string): Promise<Uint8Array>;
  decrypt(encrypted: Uint8Array, key: string): Promise<string>;
}

export interface PendingCommandStoreDependencies {
  crypto?: PendingCommandCrypto;
  now?: () => number;
  readCiphertext?: () => Promise<Uint8Array | null>;
  replaceCiphertext?: (ciphertext: Uint8Array) => Promise<void>;
  deleteCiphertext?: () => Promise<void>;
  readKey?: () => Promise<string | null>;
  writeKey?: (key: string) => Promise<void>;
  deleteKey?: () => Promise<void>;
}

type PendingState = {
  version: typeof PENDING_COMMAND_VERSION;
  create?: PendingCreateCommand;
  messages: Record<string, PendingMessageCommand>;
};

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();

const nativeCrypto: PendingCommandCrypto = {
  async generateKey() {
    const key = await AESEncryptionKey.generate();
    return key.encoded('hex');
  },
  async encrypt(plaintext, encodedKey) {
    const key = (await AESEncryptionKey.import(encodedKey, 'hex')) as AESEncryptionKey;
    const sealed = await aesEncryptAsync(textEncoder.encode(plaintext), key);
    return sealed.combined('bytes');
  },
  async decrypt(encrypted, encodedKey) {
    const key = (await AESEncryptionKey.import(encodedKey, 'hex')) as AESEncryptionKey;
    const sealed = AESSealedData.fromCombined(encrypted);
    const plaintext = await aesDecryptAsync(sealed, key, { output: 'bytes' });
    return textDecoder.decode(plaintext);
  },
};

const nativeFile = new File(Paths.document, PENDING_COMMAND_FILE);
const nativeTempFile = new File(Paths.document, PENDING_COMMAND_TEMP_FILE);

const nativeDependencies: Required<PendingCommandStoreDependencies> = {
  crypto: nativeCrypto,
  now: () => Date.now(),
  readCiphertext: async () => (nativeFile.exists ? nativeFile.bytes() : null),
  replaceCiphertext: async (ciphertext) => {
    nativeTempFile.create({ overwrite: true });
    nativeTempFile.write(ciphertext);
    await nativeTempFile.move(nativeFile, { overwrite: true });
  },
  deleteCiphertext: async () => {
    if (nativeFile.exists) nativeFile.delete();
    if (nativeTempFile.exists) nativeTempFile.delete();
  },
  readKey: () => SecureStore.getItemAsync(PENDING_COMMAND_KEY),
  writeKey: (key) => SecureStore.setItemAsync(PENDING_COMMAND_KEY, key),
  deleteKey: () => SecureStore.deleteItemAsync(PENDING_COMMAND_KEY),
};

function emptyState(): PendingState {
  return { version: PENDING_COMMAND_VERSION, messages: {} };
}

function invalidCommand(message: string): Error {
  return new Error(`Invalid pending command: ${message}`);
}

function assertCreateCommand(command: PendingCreateCommand): PendingCreateCommand {
  const parsed = createCommandSchema.safeParse(command);
  if (!parsed.success) throw invalidCommand('create');
  return parsed.data;
}

function assertMessageCommand(command: PendingMessageCommand): PendingMessageCommand {
  const parsed = messageCommandSchema.safeParse(command);
  if (!parsed.success) throw invalidCommand('message');
  return parsed.data;
}

function isExpired(command: PendingCreateCommand, now: number): boolean {
  return Date.parse(command.expiresAt) <= now;
}

function hasMessages(state: PendingState): boolean {
  return Object.keys(state.messages).length > 0;
}

export function createPendingCommandStore(dependencies: PendingCommandStoreDependencies = {}) {
  const resolved: Required<PendingCommandStoreDependencies> = { ...nativeDependencies, ...dependencies };
  let lock = Promise.resolve();

  function serialized<T>(operation: () => Promise<T>): Promise<T> {
    const next = lock.then(operation);
    lock = next.then(() => undefined, () => undefined);
    return next;
  }

  async function clearCiphertextAndKey(): Promise<void> {
    await resolved.deleteCiphertext();
    await resolved.deleteKey();
  }

  async function readState(): Promise<PendingState> {
    const encrypted = await resolved.readCiphertext();
    if (!encrypted) return emptyState();

    const key = await resolved.readKey();
    if (!key) {
      await resolved.deleteCiphertext();
      return emptyState();
    }

    try {
      const parsed = pendingStateSchema.safeParse(JSON.parse(await resolved.crypto.decrypt(encrypted, key)));
      if (!parsed.success) throw new Error('invalid pending state');
      return parsed.data as PendingState;
    } catch {
      await resolved.deleteCiphertext();
      return emptyState();
    }
  }

  async function writeState(state: PendingState): Promise<void> {
    if (!state.create && !hasMessages(state)) {
      await clearCiphertextAndKey();
      return;
    }

    let key = await resolved.readKey();
    if (!key) {
      key = await resolved.crypto.generateKey();
      await resolved.writeKey(key);
    }

    const encrypted = await resolved.crypto.encrypt(JSON.stringify(state), key);
    await resolved.replaceCiphertext(encrypted);
  }

  async function readCreateUnsafe(userId?: string, workspaceId?: string): Promise<PendingCreateCommand | null> {
    const state = await readState();
    if (!state.create) return null;
    if (isExpired(state.create, resolved.now())) {
      delete state.create;
      await writeState(state);
      return null;
    }

    const isBound = Boolean(state.create.boundUserId && state.create.boundWorkspaceId);
    if (isBound) {
      if (!userId || !workspaceId) return null;
      if (state.create.boundUserId !== userId || state.create.boundWorkspaceId !== workspaceId) {
        delete state.create;
        await writeState(state);
        return null;
      }
    }
    return state.create;
  }

  return {
    readCreate(userId?: string, workspaceId?: string): Promise<PendingCreateCommand | null> {
      return serialized(() => readCreateUnsafe(userId, workspaceId));
    },

    saveCreate(command: PendingCreateCommand): Promise<void> {
      return serialized(async () => {
        const valid = assertCreateCommand(command);
        if (isExpired(valid, resolved.now())) throw invalidCommand('expired create');
        const state = await readState();
        state.create = valid;
        await writeState(state);
      });
    },

    bindCreate(userId: string, workspaceId: string): Promise<PendingCreateCommand | null> {
      return serialized(async () => {
        const state = await readState();
        if (!state.create) return null;
        if (isExpired(state.create, resolved.now())) {
          delete state.create;
          await writeState(state);
          return null;
        }

        if (state.create.boundUserId || state.create.boundWorkspaceId) {
          if (state.create.boundUserId !== userId || state.create.boundWorkspaceId !== workspaceId) {
            delete state.create;
            await writeState(state);
            return null;
          }
          return state.create;
        }

        const bound = { ...state.create, boundUserId: userId, boundWorkspaceId: workspaceId };
        state.create = assertCreateCommand(bound);
        await writeState(state);
        return state.create;
      });
    },

    deleteCreate(): Promise<void> {
      return serialized(async () => {
        const state = await readState();
        delete state.create;
        await writeState(state);
      });
    },

    readMessage(
      conversationId: string,
      userId: string,
      workspaceId: string,
    ): Promise<PendingMessageCommand | null> {
      return serialized(async () => {
        const state = await readState();
        const command = state.messages[conversationId];
        if (!command) return null;
        if (command.boundUserId !== userId || command.boundWorkspaceId !== workspaceId) {
          delete state.messages[conversationId];
          await writeState(state);
          return null;
        }
        return command;
      });
    },

    saveMessage(command: PendingMessageCommand): Promise<void> {
      return serialized(async () => {
        const valid = assertMessageCommand(command);
        const state = await readState();
        const existing = state.messages[valid.conversationId];
        if (existing && JSON.stringify(existing) !== JSON.stringify(valid)) {
          throw invalidCommand('another message is already pending for this conversation');
        }
        state.messages[valid.conversationId] = valid;
        await writeState(state);
      });
    },

    deleteMessage(conversationId: string): Promise<void> {
      return serialized(async () => {
        const state = await readState();
        delete state.messages[conversationId];
        await writeState(state);
      });
    },

    clear(): Promise<void> {
      return serialized(clearCiphertextAndKey);
    },
  };
}

export const pendingCommandStore = createPendingCommandStore();
