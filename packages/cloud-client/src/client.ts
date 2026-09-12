import createOpenApiClient from "openapi-fetch";
import { z } from "zod";

import type { paths, components } from "./generated/openapi";
import { isCloudError, normalizeCloudError, type CloudError } from "./errors";
import { parsePublicCloudUrl } from "./environment";
import { toAccountViewModel, type AccountViewModel } from "./mappers/account";
import {
  activitySnapshotResponseSchema,
  allyLabelSchema,
  allyListResponseSchema,
  allySeedInputSchema,
  allyResponseSchema,
  allySettingsInputSchema,
  allyDeletionInputSchema,
  allyDeletionResponseSchema,
  toAllyDeletionViewModel,
  conversationResponseSchema,
  createAllyInputSchema,
  messageAcceptanceResponseSchema,
  messageResponseSchema,
  onboardingAttemptResponseSchema,
  toActivitySnapshotViewModel,
  toAllyListViewModel,
  toAllySeedRequest,
  toAllyViewModel,
  toConversationViewModel,
  toCreateAllyRequest,
  toMessageAcceptanceViewModel,
  toMessageViewModel,
  toOnboardingAttemptViewModel,
  type ActivitySnapshotViewModel,
  type AllySeedInput,
  type AllyViewModel,
  type AllySettingsInput,
  type AllyDeletionInput,
  type AllyDeletionViewModel,
  type ConversationViewModel,
  type CreateAllyInput,
  type MessageAcceptanceViewModel,
  type MessageViewModel,
  type OnboardingAttemptViewModel,
} from "./mappers/allies";
import { csrfTokenSchema, externalHttpsUrlSchema, type CloudCsrfToken } from "./schemas";
import { createControlledFetch } from "./transport";
import { createFileClient } from "./files";
import { approvalSummarySchema, approvalDetailSchema, toApprovalSummary, toApprovalDetail, type ApprovalDecision } from "./mappers/approvals";
import { canonicalRoutineUuidSchema } from "./routines";
import {
  parseRoutineDiscoveryDetailEnvelope,
  parseRoutineDiscoveryPageEnvelope,
  type RoutineDiscoveryDetail,
  type RoutineDiscoveryPage,
} from "./routine-discovery";

const CloudRequest = globalThis.Request;
const CHAT_READ_MAX_JSON_BYTES = 48 * 1024 * 1024;

function isChatReadRequest(request: Request): boolean {
  if (request.method !== "GET") return false;
  let pathname: string;
  try {
    pathname = new URL(request.url).pathname;
  } catch {
    return false;
  }
  return [
    /\/api\/v1\/workspaces\/[^/]+\/allies\/[^/]+\/conversation$/u,
    /\/api\/v1\/workspaces\/[^/]+\/conversations\/[^/]+$/u,
    /\/api\/v1\/workspaces\/[^/]+\/conversations\/[^/]+\/activities$/u,
  ].some((pattern) => pattern.test(pathname));
}

const successEnvelope = <T extends z.ZodType>(data: T) =>
  z.object({ status: z.literal("success"), message: z.string(), data }).loose();
const savedAllySettingsSchema = allyResponseSchema.extend({
  label: allyLabelSchema,
  show_label: z.boolean(),
  settings_revision: z.number().int().nonnegative(),
});
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

export type RuntimeIntentStatus = z.infer<typeof runtimeIntentStatusSchema>;

export interface RuntimeIntentViewModel {
  status: RuntimeIntentStatus;
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

export interface RoutineListOptions {
  limit?: number;
  cursor?: string;
  allyId?: string;
  signal?: AbortSignal;
}

interface ApiResult {
  data?: unknown;
  error?: unknown;
  response: Response;
}

interface RoutineReadInit {
  params: {
    path: Record<string, string>;
    query?: Record<string, number | string>;
  };
  signal?: AbortSignal;
}

interface RoutineReadApi {
  GET(path: string, init: RoutineReadInit): Promise<ApiResult>;
}

async function unwrap<T>(
  operation: Promise<ApiResult>,
  map: (data: unknown) => T,
  expectedStatuses?: readonly number[],
): Promise<T> {
  try {
    const result = await operation;
    if (!result.response.ok) throw normalizeCloudError(result.response.status, result.error);
    if (expectedStatuses && !expectedStatuses.includes(result.response.status)) {
      throw { kind: "contract" } satisfies CloudError;
    }
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

const pathSegmentSchema = z
  .string()
  .min(1)
  .max(256)
  .refine((value) => !/[\\/\u0000-\u001f\u007f]/u.test(value));
const idempotencyKeySchema = z
  .string()
  .min(16)
  .max(128)
  .refine((value) => !/[\r\n\u0000]/u.test(value));
const conversationOptionsSchema = z.object({
  limit: z.number().int().min(1).max(100).optional(),
  cursor: z.string().min(1).max(512).optional(),
});
const activityLimitSchema = z.number().int().min(1).max(200);
const activityOptionsSchema = z.object({
  limit: activityLimitSchema.optional(),
  cursor: z.string().min(1).max(512).optional(),
  replay: z.boolean().optional(),
});
const routineListOptionsSchema = z.object({
  limit: z.number().int().min(1).max(100),
  cursor: z.string().min(1).max(512).optional(),
  ally_id: canonicalRoutineUuidSchema.optional(),
}).strict();
const messageContentSchema = z.string().min(1).max(16_000);
const runtimeIntentOccurredAtSchema = z.iso.datetime({ offset: true });
const runtimeIntentIdempotencyKeySchema = z.uuid();
const runtimeIntentStatusSchema = z.enum([
  "disabled",
  "already_ready",
  "waking",
  "ready",
  "first_provision_required",
  "rate_limited",
  "failed",
]);
const runtimeIntentResponseSchema = z.object({ status: runtimeIntentStatusSchema }).strict();

export interface ConversationOptions {
  limit?: number;
  cursor?: string;
  signal?: AbortSignal;
}

export interface ActivityOptions {
  limit?: number;
  cursor?: string;
  replay?: boolean;
  signal?: AbortSignal;
}

function parseInput<T>(schema: z.ZodType<T>, input: unknown): T {
  const result = schema.safeParse(input);
  if (!result.success) throw { kind: "bad-request" } satisfies CloudError;
  return result.data;
}

function parsePathSegment(value: string): string {
  return parseInput(pathSegmentSchema, value);
}

function parseCanonicalUuid(value: string): string {
  return parseInput(canonicalRoutineUuidSchema, value);
}

function parseIdempotencyKey(value: string): string {
  return parseInput(idempotencyKeySchema, value);
}

function parseConversationOptions(options?: ConversationOptions): {
  query?: { limit?: number; cursor?: string };
  signal?: AbortSignal;
} {
  const query = parseInput(conversationOptionsSchema, {
    ...(options?.limit === undefined ? {} : { limit: options.limit }),
    ...(options?.cursor === undefined ? {} : { cursor: options.cursor }),
  });
  return {
    ...(Object.keys(query).length ? { query } : {}),
    ...(options?.signal ? { signal: options.signal } : {}),
  };
}

function parseActivityOptions(
  limitOrOptions?: number | ActivityOptions,
  signal?: AbortSignal,
): {
  query?: { limit?: number; cursor?: string; replay?: boolean };
  signal?: AbortSignal;
} {
  const options = typeof limitOrOptions === "number"
    ? { limit: limitOrOptions, signal }
    : {
        ...(limitOrOptions ?? {}),
        ...(limitOrOptions?.signal || !signal ? {} : { signal }),
      };
  const query = parseInput(activityOptionsSchema, {
    ...(options.limit === undefined ? {} : { limit: options.limit }),
    ...(options.cursor === undefined ? {} : { cursor: options.cursor }),
    ...(options.replay === undefined ? {} : { replay: options.replay }),
  });
  return {
    ...(Object.keys(query).length ? { query } : {}),
    ...(options.signal ? { signal: options.signal } : {}),
  };
}

function parseRoutineListOptions(options?: RoutineListOptions): {
  query: { limit: number; cursor?: string; ally_id?: string };
  signal?: AbortSignal;
} {
  const query = parseInput(routineListOptionsSchema, {
    limit: options?.limit ?? 50,
    ...(options?.cursor === undefined ? {} : { cursor: options.cursor }),
    ...(options?.allyId === undefined ? {} : { ally_id: parseCanonicalUuid(options.allyId) }),
  });
  return { query, signal: options?.signal };
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
    maxJsonBytesForRequest: options.maxJsonBytes === undefined
      ? (request) => isChatReadRequest(request) ? CHAT_READ_MAX_JSON_BYTES : undefined
      : undefined,
  });
  const api = createOpenApiClient<paths>({ baseUrl, fetch: controlledFetch, Request: CloudRequest });
  const routineReadApi = api as unknown as RoutineReadApi;

  return {
    files: createFileClient(options),
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

    async listRoutines(workspaceId: string, options?: RoutineListOptions): Promise<RoutineDiscoveryPage> {
      const parsedOptions = parseRoutineListOptions(options);
      rejectPreAborted(parsedOptions.signal);
      const workspace = parseCanonicalUuid(workspaceId);
      return unwrap(
        routineReadApi.GET("/api/v1/workspaces/{workspace_id}/routines", {
          params: {
            path: { workspace_id: workspace },
            query: parsedOptions.query,
          },
          signal: normalizeRequestSignal(parsedOptions.signal),
        }),
        (data) => {
          const page = parseRoutineDiscoveryPageEnvelope(data);
          if (parsedOptions.query.ally_id !== undefined
            && page.items.some((item) => item.responsibleAllyId !== parsedOptions.query.ally_id)) {
            throw { kind: "contract" } satisfies CloudError;
          }
          return page;
        },
        [200],
      );
    },

    async getRoutine(workspaceId: string, routineId: string, signal?: AbortSignal): Promise<RoutineDiscoveryDetail> {
      rejectPreAborted(signal);
      const workspace = parseCanonicalUuid(workspaceId);
      const routine = parseCanonicalUuid(routineId);
      return unwrap(
        routineReadApi.GET("/api/v1/workspaces/{workspace_id}/routines/{routine_id}", {
          params: { path: { workspace_id: workspace, routine_id: routine } },
          signal: normalizeRequestSignal(signal),
        }),
        (data) => {
          const detail = parseRoutineDiscoveryDetailEnvelope(data);
          if (detail.routineId !== routine || detail.workspaceId !== workspace) {
            throw { kind: "contract" } satisfies CloudError;
          }
          return detail;
        },
        [200],
      );
    },

    async requestRuntimeIntent(
      allyId: string,
      occurredAt: string,
      idempotencyKey: string,
      signal?: AbortSignal,
    ): Promise<RuntimeIntentViewModel> {
      rejectPreAborted(signal);
      const ally = parsePathSegment(allyId);
      const timestamp = parseInput(runtimeIntentOccurredAtSchema, occurredAt);
      const key = parseInput(runtimeIntentIdempotencyKeySchema, idempotencyKey);
      return unwrap(
        api.POST("/api/v1/allies/{ally_id}/runtime-intents", {
          params: {
            path: { ally_id: ally },
            header: { "Idempotency-Key": key },
          },
          body: { intent: "composing_started", occurred_at: timestamp },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => ({
          status: successEnvelope(runtimeIntentResponseSchema).parse(data).data.status,
        }),
        [200, 202],
      );
    },

    async requestWorkspaceRuntimeIntent(
      occurredAt: string,
      idempotencyKey: string,
      signal?: AbortSignal,
    ): Promise<RuntimeIntentViewModel> {
      rejectPreAborted(signal);
      const timestamp = parseInput(runtimeIntentOccurredAtSchema, occurredAt);
      const key = parseInput(runtimeIntentIdempotencyKeySchema, idempotencyKey);
      return unwrap(
        api.POST("/api/v1/onboarding/runtime-intents", {
          params: { header: { "Idempotency-Key": key } },
          body: { version: 1, intent: "ally_creation_started", occurred_at: timestamp },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => ({
          status: successEnvelope(runtimeIntentResponseSchema).parse(data).data.status,
        }),
        [200, 202],
      );
    },

    async beginOnboarding(input: AllySeedInput, signal?: AbortSignal): Promise<OnboardingAttemptViewModel> {
      rejectPreAborted(signal);
      const seed = toAllySeedRequest(parseInput(allySeedInputSchema, input));
      return unwrap(
        api.POST("/api/v1/onboarding/attempts", {
          body: seed,
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) =>
          toOnboardingAttemptViewModel(successEnvelope(onboardingAttemptResponseSchema).parse(data).data),
        [200],
      );
    },

    async listAllies(workspaceId: string, signal?: AbortSignal): Promise<AllyViewModel[]> {
      rejectPreAborted(signal);
      const workspace = parsePathSegment(workspaceId);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/allies", {
          params: { path: { workspace_id: workspace } },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => toAllyListViewModel(successEnvelope(allyListResponseSchema).parse(data).data),
        [200],
      );
    },

    async getAlly(workspaceId: string, allyId: string, signal?: AbortSignal): Promise<AllyViewModel> {
      rejectPreAborted(signal);
      const workspace = parsePathSegment(workspaceId);
      const ally = parsePathSegment(allyId);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/allies/{ally_id}", {
          params: { path: { workspace_id: workspace, ally_id: ally } },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => toAllyViewModel(successEnvelope(allyResponseSchema).parse(data).data),
        [200],
      );
    },

    async updateAllySettings(
      workspaceId: string,
      allyId: string,
      input: AllySettingsInput,
      signal?: AbortSignal,
    ): Promise<AllyViewModel> {
      rejectPreAborted(signal);
      const workspace = parsePathSegment(workspaceId);
      const ally = parsePathSegment(allyId);
      const settings = parseInput(allySettingsInputSchema, input);
      return unwrap(
        api.PATCH("/api/v1/workspaces/{workspace_id}/allies/{ally_id}/settings", {
          params: { path: { workspace_id: workspace, ally_id: ally } },
          body: {
            label: settings.label,
            show_label: settings.showLabel,
            settings_revision: settings.settingsRevision,
          },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => toAllyViewModel(successEnvelope(savedAllySettingsSchema).parse(data).data),
        [200],
      );
    },

    async requestAllyDeletion(
      workspaceId: string, allyId: string, input: AllyDeletionInput, signal?: AbortSignal,
    ): Promise<AllyDeletionViewModel> {
      rejectPreAborted(signal);
      const workspace = parsePathSegment(workspaceId);
      const ally = parsePathSegment(allyId);
      const body = parseInput(allyDeletionInputSchema, input);
      return unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/allies/{ally_id}/deletion", {
          params: { path: { workspace_id: workspace, ally_id: ally } }, body,
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => toAllyDeletionViewModel(successEnvelope(allyDeletionResponseSchema.refine(
          (value) => value.ally_id === ally, "Deletion belongs to a different Ally",
        )).parse(data).data),
        [200, 202],
      );
    },

    async getAllyDeletion(workspaceId: string, allyId: string, signal?: AbortSignal): Promise<AllyDeletionViewModel> {
      rejectPreAborted(signal);
      const workspace = parsePathSegment(workspaceId);
      const ally = parsePathSegment(allyId);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/allies/{ally_id}/deletion", {
          params: { path: { workspace_id: workspace, ally_id: ally } },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => toAllyDeletionViewModel(successEnvelope(allyDeletionResponseSchema.refine(
          (value) => value.ally_id === ally, "Deletion belongs to a different Ally",
        )).parse(data).data),
        [200],
      );
    },

    async createAlly(
      workspaceId: string,
      input: CreateAllyInput,
      idempotencyKey: string,
      signal?: AbortSignal,
    ): Promise<AllyViewModel> {
      rejectPreAborted(signal);
      const workspace = parsePathSegment(workspaceId);
      const body = toCreateAllyRequest(parseInput(createAllyInputSchema, input));
      const key = parseIdempotencyKey(idempotencyKey);
      return unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/allies", {
          params: {
            path: { workspace_id: workspace },
            header: { "Idempotency-Key": key },
          },
          body,
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => toAllyViewModel(successEnvelope(allyResponseSchema).parse(data).data),
        [201, 202],
      );
    },

    async getAllyConversation(
      workspaceId: string,
      allyId: string,
      options?: ConversationOptions,
    ): Promise<ConversationViewModel> {
      const signal = options?.signal;
      rejectPreAborted(signal);
      const workspace = parsePathSegment(workspaceId);
      const ally = parsePathSegment(allyId);
      const { query, signal: requestSignal } = parseConversationOptions(options);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/allies/{ally_id}/conversation", {
          params: {
            path: { workspace_id: workspace, ally_id: ally },
            ...(query ? { query } : {}),
          },
          signal: normalizeRequestSignal(requestSignal),
        }) as Promise<ApiResult>,
        (data) => toConversationViewModel(successEnvelope(conversationResponseSchema).parse(data).data, ally),
        [200],
      );
    },

    async getConversation(
      workspaceId: string,
      conversationId: string,
      options?: ConversationOptions,
    ): Promise<ConversationViewModel> {
      const signal = options?.signal;
      rejectPreAborted(signal);
      const workspace = parsePathSegment(workspaceId);
      const conversation = parsePathSegment(conversationId);
      const { query, signal: requestSignal } = parseConversationOptions(options);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}", {
          params: {
            path: { workspace_id: workspace, conversation_id: conversation },
            ...(query ? { query } : {}),
          },
          signal: normalizeRequestSignal(requestSignal),
        }) as Promise<ApiResult>,
        (data) => toConversationViewModel(successEnvelope(conversationResponseSchema).parse(data).data),
        [200],
      );
    },

    async sendMessage(
      workspaceId: string,
      conversationId: string,
      content: string,
      idempotencyKey: string,
      signal?: AbortSignal,
      timezone?: string,
      routineAction?: components["schemas"]["RoutineMessageAction"],
    ): Promise<MessageAcceptanceViewModel> {
      rejectPreAborted(signal);
      const workspace = parsePathSegment(workspaceId);
      const conversation = parsePathSegment(conversationId);
      const body = parseInput(messageContentSchema, content);
      const key = parseIdempotencyKey(idempotencyKey);
      return unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages", {
          params: {
            path: { workspace_id: workspace, conversation_id: conversation },
            header: { "Idempotency-Key": key },
          },
          body: { content: body, timezone: timezone ?? "", ...(routineAction ? { routine_action: routineAction } : {}) },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => toMessageAcceptanceViewModel(successEnvelope(messageAcceptanceResponseSchema).parse(data).data),
        [200, 201],
      );
    },

    async deleteQueuedMessage(
      workspaceId: string,
      conversationId: string,
      messageId: string,
      signal?: AbortSignal,
    ): Promise<MessageViewModel> {
      rejectPreAborted(signal);
      const workspace = parsePathSegment(workspaceId);
      const conversation = parsePathSegment(conversationId);
      const message = parsePathSegment(messageId);
      return unwrap(
        api.DELETE("/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}", {
          params: {
            path: { workspace_id: workspace, conversation_id: conversation, message_id: message },
          },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => {
          const deleted = toMessageViewModel(successEnvelope(messageResponseSchema).parse(data).data);
          if (deleted.id !== message || !deleted.deletedAt || deleted.content !== ""
            || deleted.status !== "stopped" || deleted.queueState !== null) {
            throw { kind: "contract" } satisfies CloudError;
          }
          return deleted;
        },
        [200],
      );
    },

    async retryMessage(
      workspaceId: string,
      conversationId: string,
      messageId: string,
      idempotencyKey: string,
      signal?: AbortSignal,
    ): Promise<MessageAcceptanceViewModel> {
      rejectPreAborted(signal);
      const workspace = parsePathSegment(workspaceId);
      const conversation = parsePathSegment(conversationId);
      const message = parsePathSegment(messageId);
      const key = parseIdempotencyKey(idempotencyKey);
      return unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}/retry", {
          params: {
            path: { workspace_id: workspace, conversation_id: conversation, message_id: message },
            header: { "Idempotency-Key": key },
          },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => toMessageAcceptanceViewModel(successEnvelope(messageAcceptanceResponseSchema).parse(data).data),
        [200, 201],
      );
    },

    async getActivities(
      workspaceId: string,
      conversationId: string,
      limitOrOptions?: number | ActivityOptions,
      signal?: AbortSignal,
    ): Promise<ActivitySnapshotViewModel> {
      const parsedOptions = parseActivityOptions(limitOrOptions, signal);
      rejectPreAborted(parsedOptions.signal);
      const workspace = parsePathSegment(workspaceId);
      const conversation = parsePathSegment(conversationId);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/activities", {
          params: {
            path: { workspace_id: workspace, conversation_id: conversation },
            ...(parsedOptions.query ? { query: parsedOptions.query } : {}),
          },
          signal: normalizeRequestSignal(parsedOptions.signal),
        }) as Promise<ApiResult>,
        (data) => toActivitySnapshotViewModel(successEnvelope(activitySnapshotResponseSchema).parse(data).data),
        [200],
      );
    },

    async getApprovals(workspaceId: string, conversationId: string, signal?: AbortSignal) {
      rejectPreAborted(signal);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/approvals", {
          params: { path: { workspace_id: parsePathSegment(workspaceId), conversation_id: parsePathSegment(conversationId) } },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => successEnvelope(z.object({ approvals: z.array(approvalSummarySchema).max(50) })).parse(data).data.approvals.map(toApprovalSummary),
        [200],
      );
    },

    async getApproval(workspaceId: string, conversationId: string, approvalId: string, signal?: AbortSignal) {
      rejectPreAborted(signal);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/approvals/{approval_id}", {
          params: { path: { workspace_id: parsePathSegment(workspaceId), conversation_id: parsePathSegment(conversationId), approval_id: parsePathSegment(approvalId) } },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => toApprovalDetail(successEnvelope(approvalDetailSchema.refine((approval) => approval.id === approvalId)).parse(data).data),
        [200],
      );
    },

    async decideApproval(workspaceId: string, conversationId: string, approvalId: string, decision: ApprovalDecision, key: string, signal?: AbortSignal) {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/approvals/{approval_id}/decision", {
          params: {
            path: { workspace_id: parsePathSegment(workspaceId), conversation_id: parsePathSegment(conversationId), approval_id: parsePathSegment(approvalId) },
            header: { "Idempotency-Key": parseIdempotencyKey(key) },
          },
          body: { decision },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => toApprovalDetail(successEnvelope(approvalDetailSchema.refine((approval) => approval.id === approvalId)).parse(data).data),
        [200, 202],
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
