import createOpenApiClient from "openapi-fetch";
import { z } from "zod";

import type { paths } from "./generated/openapi";
import { isCloudError, normalizeCloudError, type CloudError } from "./errors";
import { parsePublicCloudUrl } from "./environment";
import { toAccountViewModel, type AccountViewModel } from "./mappers/account";
import { csrfTokenSchema, externalHttpsUrlSchema, type CloudCsrfToken } from "./schemas";
import { createControlledFetch } from "./transport";

const CloudRequest = globalThis.Request;

const successEnvelope = <T extends z.ZodType>(data: T) =>
  z.object({ status: z.literal("success"), message: z.string(), data }).loose();
const profileSchema = z
  .object({ display_name: z.string(), avatar_url: externalHttpsUrlSchema.nullable().optional() })
  .loose();
const avatarSchema = z
  .object({
    asset_id: z.string().min(1),
    url: externalHttpsUrlSchema.nullable().optional(),
    expires_at: z.iso.datetime({ offset: true }).nullable().optional(),
  })
  .loose();
const preparedAvatarSchema = z
  .object({
    asset_id: z.string().min(1),
    upload_url: externalHttpsUrlSchema,
    headers: z.record(z.string(), z.string()),
    expires_at: z.iso.datetime({ offset: true }),
  })
  .loose();
const workspaceSchema = z
  .object({
    id: z.string().min(1),
    name: z.string().min(1),
    role: z.string().min(1),
    capabilities: z.array(z.string()),
  })
  .loose();
const maskedEmailSchema = z
  .string()
  .regex(/^[^@\s]+@[^@\s]+$/)
  .refine((value) => value.slice(0, value.indexOf("@")).includes("*"));
const waitlistEntrySchema = z.object({
  attempt_token: z.string().min(32),
  greeting: z.string().min(1),
});
const waitlistCompletionSchema = z.object({ email: maskedEmailSchema });
const dateTimeSchema = z.iso.datetime({ offset: true });
const appearanceSchema = z
  .object({
    catalog_version: z.string().min(1),
    key: z.string().regex(/^[a-z][a-z0-9_-]*:[0-9a-f]{6}$/i),
  })
  .loose();
const onboardingAttemptSchema = z
  .object({
    attempt_token: z.string().min(1),
    greeting: z.string().min(1),
  })
  .loose();
const allySchema = z
  .object({
    appearance: appearanceSchema,
    binding_id: z.string().min(1),
    id: z.string().min(1),
    job: z.string().min(1),
    name: z.string().min(1),
    operation_id: z.string().min(1),
    personality: z.string().min(1),
    provisioning_state: z.string().min(1),
    retryable: z.boolean(),
  })
  .loose();
const messageSchema = z
  .object({
    content: z.string().min(1),
    created_at: dateTimeSchema,
    id: z.string().min(1),
    sender: z.string().min(1),
    sequence: z.number().int().nonnegative(),
    status: z.string().min(1),
  })
  .loose();
const conversationSchema = z
  .object({
    ally_id: z.string().min(1),
    id: z.string().min(1),
    messages: z.array(messageSchema),
    next_cursor: z.string().nullable().optional(),
  })
  .loose();
const activitySchema = z
  .object({
    conversation_turn_ordinal: z.number().int().nonnegative(),
    created_at: dateTimeSchema,
    id: z.string().min(1),
    kind: z.string().min(1),
    message_id: z.string().min(1),
    sequence: z.number().int().nonnegative(),
    state: z.string().min(1),
    text: z.string().min(1),
  })
  .loose();
const activitySnapshotSchema = z
  .object({
    activities: z.array(activitySchema),
    conversation_id: z.string().min(1),
    last_contiguous_sequence: z.number().int().nonnegative(),
    state: z.string().min(1),
  })
  .loose();
const messageAcceptanceSchema = z
  .object({
    conversation_id: z.string().min(1),
    execution: z.record(z.string(), z.unknown()).nullable().optional(),
    message: messageSchema,
    replayed: z.boolean(),
  })
  .loose();
const appearanceInputSchema = z
  .object({
    catalogVersion: z.string().min(1),
    key: z.string().regex(/^[a-z][a-z0-9_-]*:[0-9a-f]{6}$/i),
  })
  .loose();
const onboardingAttemptInputSchema = z
  .object({
    appearance: appearanceInputSchema,
    job: z.string().min(1),
    name: z.string().min(1),
    personality: z.string().min(1),
  })
  .loose();
const createAllyInputSchema = onboardingAttemptInputSchema
  .extend({
    onboardingAttempt: z.string().min(1),
    reply: z.string().min(1).max(4000),
  })
  .loose();
const messageContentSchema = z.string().min(1).max(4000).refine((value) => value.trim().length > 0);
const pathIdSchema = z.string().trim().min(1);
const idempotencyKeySchema = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
const pageLimitSchema = z.number().int().min(1).max(100);
const DEFAULT_CONVERSATION_PAGE_LIMIT = 50;
const DEFAULT_ACTIVITY_LIMIT = 50;

function normalizeRequestSignal(signal?: AbortSignal): AbortSignal | undefined {
  if (!signal) return undefined;
  try {
    new CloudRequest("https://cloud.example.com", { signal });
    return signal;
  } catch {
    return undefined;
  }
}

export interface ProfileViewModel {
  displayName: string;
  avatarUrl: string | null;
}

export interface AvatarViewModel {
  assetId: string;
  url: string | null;
  expiresAt: string | null;
}

export interface PreparedAvatarViewModel {
  assetId: string;
  uploadUrl: string;
  headers: Record<string, string>;
  expiresAt: string;
}

export interface WorkspaceViewModel {
  id: string;
  name: string;
  role: string;
  capabilities: string[];
}

export interface AppearanceViewModel {
  catalogVersion: string;
  key: string;
}

export interface OnboardingAttemptInput {
  name: string;
  job: string;
  personality: string;
  appearance: AppearanceViewModel;
}

export interface OnboardingAttemptViewModel {
  attemptToken: string;
  greeting: string;
}

export interface CreateAllyInput extends OnboardingAttemptInput {
  onboardingAttempt: string;
  reply: string;
}

export interface AllyViewModel {
  id: string;
  name: string;
  job: string;
  personality: string;
  appearance: AppearanceViewModel;
  provisioningState: string;
  retryable: boolean;
}

export interface MessageViewModel {
  id: string;
  sender: string;
  content: string;
  sequence: number;
  status: string;
  createdAt: string;
}

export interface ConversationPageViewModel {
  id: string;
  allyId: string;
  messages: MessageViewModel[];
  nextCursor: string | null;
}

export interface MessageAcceptanceViewModel {
  conversationId: string;
  message: MessageViewModel;
}

export interface ActivityViewModel {
  id: string;
  text: string;
  sequence: number;
  state: string;
  createdAt: string;
}

export interface ActivitySnapshotViewModel {
  conversationId: string;
  activities: ActivityViewModel[];
  state: string;
  lastContiguousSequence: number;
}

export interface ConversationPageInput {
  limit?: number;
  cursor?: string | null;
}

export interface WaitlistEntryInput {
  attemptId: string;
  name: string;
  appearanceCatalogVersion: string;
  appearanceKey: string;
  job: string;
  personality: string;
}

export interface WaitlistEntryViewModel {
  attemptToken: string;
  greeting: string;
}

export interface WaitlistCompletionInput {
  attemptToken: string;
  reply: string;
  email: string;
  consentVersion: string;
}

export interface WaitlistCompletionViewModel {
  email: string;
}

export interface CloudClientOptions {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
  prepareRequest?: (request: Request) => Request | Promise<Request>;
  timeoutMs?: number;
  maxJsonBytes?: number;
}

interface ApiResult {
  data?: unknown;
  error?: unknown;
  response: Response;
}

async function unwrap<T>(operation: Promise<ApiResult>, map: (data: unknown) => T): Promise<T> {
  try {
    const result = await operation;
    if (!result.response.ok) throw normalizeCloudError(result.response.status, result.error);
    try {
      return map(result.data);
    } catch (error) {
      if (isCloudError(error)) throw error;
      throw { kind: "contract" } satisfies CloudError;
    }
  } catch (error) {
    if (isCloudError(error)) throw error;
    throw { kind: "contract" } satisfies CloudError;
  }
}

async function noContent(operation: Promise<ApiResult>): Promise<void> {
  await unwrap(operation, () => undefined);
}

function rejectPreAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw { kind: "aborted" } satisfies CloudError;
}

function parseRequest<T>(schema: z.ZodType<T>, input: unknown): T {
  try {
    return schema.parse(input);
  } catch {
    throw { kind: "bad-request" } satisfies CloudError;
  }
}

function mapMessage(message: z.infer<typeof messageSchema>): MessageViewModel {
  return {
    id: message.id,
    sender: message.sender,
    content: message.content,
    sequence: message.sequence,
    status: message.status,
    createdAt: message.created_at,
  };
}

function mapAlly(data: unknown): AllyViewModel {
  const ally = successEnvelope(allySchema).parse(data).data;
  return {
    id: ally.id,
    name: ally.name,
    job: ally.job,
    personality: ally.personality,
    appearance: {
      catalogVersion: ally.appearance.catalog_version,
      key: ally.appearance.key,
    },
    provisioningState: ally.provisioning_state,
    retryable: ally.retryable,
  };
}

function mapConversation(data: unknown): ConversationPageViewModel {
  const conversation = successEnvelope(conversationSchema).parse(data).data;
  return {
    id: conversation.id,
    allyId: conversation.ally_id,
    messages: conversation.messages.map(mapMessage),
    nextCursor: conversation.next_cursor ?? null,
  };
}

function mapActivitySnapshot(data: unknown): ActivitySnapshotViewModel {
  const snapshot = successEnvelope(activitySnapshotSchema).parse(data).data;
  return {
    conversationId: snapshot.conversation_id,
    activities: snapshot.activities.map((activity) => ({
      id: activity.id,
      text: activity.text,
      sequence: activity.sequence,
      state: activity.state,
      createdAt: activity.created_at,
    })),
    state: snapshot.state,
    lastContiguousSequence: snapshot.last_contiguous_sequence,
  };
}

function hasControlCharacter(value: string): boolean {
  return /[\u0000-\u001f\u007f]/u.test(value);
}

function isSafeDecodedReturnPath(value: string): boolean {
  return value.startsWith("/") && !value.startsWith("//") && !value.includes("\\") && !hasControlCharacter(value);
}

export function parseSafeReturnPath(value: unknown): string | null {
  if (typeof value !== "string" || value.length < 1 || value.length > 500) return null;

  let decoded = value;
  for (let pass = 0; pass < 8; pass += 1) {
    if (!isSafeDecodedReturnPath(decoded)) return null;
    if (!decoded.includes("%")) return value;

    try {
      const next = decodeURIComponent(decoded);
      if (next === decoded) return value;
      decoded = next;
    } catch {
      return null;
    }
  }

  return null;
}

function parseReturnPath(value: string): string {
  const parsed = parseSafeReturnPath(value);
  if (parsed === null) throw { kind: "bad-request" } satisfies CloudError;
  return parsed;
}

export function createCloudClient(options: CloudClientOptions) {
  const baseUrl = parsePublicCloudUrl(options.baseUrl);
  const controlledFetch = createControlledFetch({
    fetch: options.fetch ?? globalThis.fetch.bind(globalThis),
    prepareRequest: options.prepareRequest,
    timeoutMs: options.timeoutMs,
    maxJsonBytes: options.maxJsonBytes,
  });
  const api = createOpenApiClient<paths>({ baseUrl, fetch: controlledFetch, Request: CloudRequest });

  return {
    async getCsrf(signal?: AbortSignal): Promise<CloudCsrfToken> {
      rejectPreAborted(signal);
      try {
        const result = await (api.GET("/api/v1/auths/csrf", {
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>);
        if (!result.response.ok) throw normalizeCloudError(result.response.status, result.error);
        if (result.response.status !== 204) throw { kind: "contract" } satisfies CloudError;
        const token = csrfTokenSchema.safeParse(result.response.headers.get("X-CSRFToken"));
        if (!token.success) throw { kind: "contract" } satisfies CloudError;
        return token.data;
      } catch (error) {
        if (isCloudError(error)) throw error;
        throw { kind: "contract" } satisfies CloudError;
      }
    },

    async beginSignIn(redirectTo: string, signal?: AbortSignal) {
      rejectPreAborted(signal);
      const safeRedirectTo = parseReturnPath(redirectTo);
      return unwrap(
        api.POST("/api/v1/auths/sign-in/{provider}", {
          params: { path: { provider: "google" } },
          body: { redirect_to: safeRedirectTo },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) =>
          successEnvelope(z.object({ redirect_url: externalHttpsUrlSchema }).loose()).parse(data).data.redirect_url,
      );
    },

    async refreshSession(signal?: AbortSignal) {
      rejectPreAborted(signal);
      await noContent(api.POST("/api/v1/auths/refresh", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>);
    },

    async logout(signal?: AbortSignal) {
      rejectPreAborted(signal);
      await noContent(api.POST("/api/v1/auths/logout", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>);
    },

    async getCurrentAccount(signal?: AbortSignal): Promise<AccountViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.GET("/api/v1/auths/me", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>,
        (data) => toAccountViewModel(successEnvelope(z.unknown()).parse(data).data),
      );
    },

    async updateProfile(displayName: string, signal?: AbortSignal): Promise<ProfileViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.PATCH("/api/v1/auths/me/profile", {
          body: { display_name: displayName },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => {
          const profile = successEnvelope(profileSchema).parse(data).data;
          return { displayName: profile.display_name, avatarUrl: profile.avatar_url ?? null };
        },
      );
    },

    async prepareAvatarUpload(
      input: { contentType: string; size: number; sha256: string },
      signal?: AbortSignal,
    ): Promise<PreparedAvatarViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/auths/me/avatar/uploads", {
          body: { content_type: input.contentType, size: input.size, sha256: input.sha256 },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => {
          const avatar = successEnvelope(preparedAvatarSchema).parse(data).data;
          return {
            assetId: avatar.asset_id,
            uploadUrl: avatar.upload_url,
            headers: avatar.headers,
            expiresAt: avatar.expires_at,
          };
        },
      );
    },

    async completeAvatar(assetId: string, signal?: AbortSignal): Promise<AvatarViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/auths/me/avatar/{asset_id}/complete", {
          params: { path: { asset_id: assetId } },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        mapAvatar,
      );
    },

    async getAvatarRead(signal?: AbortSignal): Promise<AvatarViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.GET("/api/v1/auths/me/avatar/read", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>,
        mapAvatar,
      );
    },

    async deleteAvatar(signal?: AbortSignal) {
      rejectPreAborted(signal);
      await noContent(api.DELETE("/api/v1/auths/me/avatar", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>);
    },

    async getWorkspace(workspaceId: string, signal?: AbortSignal): Promise<WorkspaceViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}", {
          params: { path: { workspace_id: workspaceId } },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => successEnvelope(workspaceSchema).parse(data).data,
      );
    },

    async beginOnboardingAttempt(
      input: OnboardingAttemptInput,
      signal?: AbortSignal,
    ): Promise<OnboardingAttemptViewModel> {
      rejectPreAborted(signal);
      const values = parseRequest(onboardingAttemptInputSchema, input);
      return unwrap(
        api.POST("/api/v1/onboarding/attempts", {
          body: {
            name: values.name,
            job: values.job,
            personality: values.personality,
            appearance: {
              catalog_version: values.appearance.catalogVersion,
              key: values.appearance.key,
            },
          },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => {
          const attempt = successEnvelope(onboardingAttemptSchema).parse(data).data;
          return { attemptToken: attempt.attempt_token, greeting: attempt.greeting };
        },
      );
    },

    async createAlly(
      workspaceId: string,
      input: CreateAllyInput,
      idempotencyKey: string,
      signal?: AbortSignal,
    ): Promise<AllyViewModel> {
      rejectPreAborted(signal);
      const values = parseRequest(createAllyInputSchema, input);
      const path = parseRequest(pathIdSchema, workspaceId);
      const key = parseRequest(idempotencyKeySchema, idempotencyKey);
      return unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/allies", {
          params: { path: { workspace_id: path }, header: { "Idempotency-Key": key } },
          body: {
            name: values.name,
            job: values.job,
            personality: values.personality,
            appearance: {
              catalog_version: values.appearance.catalogVersion,
              key: values.appearance.key,
            },
            onboarding_attempt: values.onboardingAttempt,
            reply: values.reply,
          },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        mapAlly,
      );
    },

    async getAlly(workspaceId: string, allyId: string, signal?: AbortSignal): Promise<AllyViewModel> {
      rejectPreAborted(signal);
      const workspace = parseRequest(pathIdSchema, workspaceId);
      const ally = parseRequest(pathIdSchema, allyId);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/allies/{ally_id}", {
          params: { path: { workspace_id: workspace, ally_id: ally } },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        mapAlly,
      );
    },

    async getConversationByAlly(
      workspaceId: string,
      allyId: string,
      page?: ConversationPageInput,
      signal?: AbortSignal,
    ): Promise<ConversationPageViewModel> {
      rejectPreAborted(signal);
      const workspace = parseRequest(pathIdSchema, workspaceId);
      const ally = parseRequest(pathIdSchema, allyId);
      const values = page
        ? parseRequest(z.object({ limit: pageLimitSchema.optional(), cursor: z.string().nullable().optional() }).loose(), page)
        : {};
      const limit = values.limit ?? DEFAULT_CONVERSATION_PAGE_LIMIT;
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/allies/{ally_id}/conversation", {
          params: {
            path: { workspace_id: workspace, ally_id: ally },
            query: { limit, ...(values.cursor ? { cursor: values.cursor } : {}) },
          },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        mapConversation,
      );
    },

    async sendMessage(
      workspaceId: string,
      conversationId: string,
      content: string,
      idempotencyKey: string,
      signal?: AbortSignal,
    ): Promise<MessageAcceptanceViewModel> {
      rejectPreAborted(signal);
      const workspace = parseRequest(pathIdSchema, workspaceId);
      const conversation = parseRequest(pathIdSchema, conversationId);
      const body = parseRequest(messageContentSchema, content);
      const key = parseRequest(idempotencyKeySchema, idempotencyKey);
      return unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages", {
          params: {
            path: { workspace_id: workspace, conversation_id: conversation },
            header: { "Idempotency-Key": key },
          },
          body: { content: body },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => {
          const acceptance = successEnvelope(messageAcceptanceSchema).parse(data).data;
          return {
            conversationId: acceptance.conversation_id,
            message: mapMessage(acceptance.message),
          };
        },
      );
    },

    async getActivitySnapshot(
      workspaceId: string,
      conversationId: string,
      limit?: number,
      signal?: AbortSignal,
    ): Promise<ActivitySnapshotViewModel> {
      rejectPreAborted(signal);
      const workspace = parseRequest(pathIdSchema, workspaceId);
      const conversation = parseRequest(pathIdSchema, conversationId);
      const boundedLimit = parseRequest(pageLimitSchema, limit ?? DEFAULT_ACTIVITY_LIMIT);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/activities", {
          params: {
            path: { workspace_id: workspace, conversation_id: conversation },
            query: { limit: boundedLimit },
          },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        mapActivitySnapshot,
      );
    },

    async createWaitlistEntry(
      input: WaitlistEntryInput,
      signal?: AbortSignal,
    ): Promise<WaitlistEntryViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/waitlist/entries", {
          body: {
            attempt_id: input.attemptId,
            name: input.name,
            appearance_catalog_version: input.appearanceCatalogVersion,
            appearance_key: input.appearanceKey,
            job: input.job,
            personality: input.personality,
          },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => {
          const entry = successEnvelope(waitlistEntrySchema).parse(data).data;
          return { attemptToken: entry.attempt_token, greeting: entry.greeting };
        },
      );
    },

    async completeWaitlistEntry(
      input: WaitlistCompletionInput,
      signal?: AbortSignal,
    ): Promise<WaitlistCompletionViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/waitlist/entries/complete", {
          body: {
            attempt_token: input.attemptToken,
            reply: input.reply,
            email: input.email,
            consent_version: input.consentVersion,
          },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => successEnvelope(waitlistCompletionSchema).parse(data).data,
      );
    },
  };
}

function mapAvatar(data: unknown): AvatarViewModel {
  const avatar = successEnvelope(avatarSchema).parse(data).data;
  return {
    assetId: avatar.asset_id,
    url: avatar.url ?? null,
    expiresAt: avatar.expires_at ?? null,
  };
}

export type CloudClient = ReturnType<typeof createCloudClient>;
