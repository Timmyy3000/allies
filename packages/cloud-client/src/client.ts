import createOpenApiClient from "openapi-fetch";
import { z } from "zod";

import type { operations, paths } from "./generated/openapi";
import { isCloudError, normalizeCloudError, type CloudError } from "./errors";
import { parsePublicCloudUrl } from "./environment";
import { toAccountViewModel, type AccountViewModel } from "./mappers/account";
import { externalHttpsUrlSchema } from "./schemas";
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
const returnPathSchema = z
  .string()
  .min(1)
  .refine((value) => {
    let decoded = value;
    for (let pass = 0; pass < 8; pass += 1) {
      if (!decoded.startsWith("/") || decoded.startsWith("//") || decoded.includes("\\")) return false;
      try {
        const next = decodeURIComponent(decoded);
        if (next === decoded) return true;
        decoded = next;
      } catch {
        return false;
      }
    }
    return false;
  });

const waitlistAcknowledgementSchema = z.object({
  operation: z.string(),
  result_lifecycle: z.string(),
  result_revision: z.number(),
});
const maskedEmailSchema = z
  .string()
  .regex(/^[^@\s]+@[^@\s]+$/)
  .refine((value) => value.slice(0, value.indexOf("@")).includes("*"));
const waitlistConfigurationSchema = z.object({
  name: z.string().nullable().optional(),
  appearance_catalog_version: z.string().nullable().optional(),
  appearance_key: z.string().nullable().optional(),
  job: z.string().nullable().optional(),
  personality: z.string().nullable().optional(),
});
const waitlistGreetingSchema = z.object({
  text: z.string(),
  policy_version: z.string(),
  generated_at: z.string(),
});
const waitlistReplySchema = z.object({
  text: z.string(),
  status: z.literal("pending"),
  recorded_at: z.string(),
});
const waitlistJoinSnapshotSchema = z.object({
  email: maskedEmailSchema,
  joined_at: z.string(),
});
const waitlistTimestampsSchema = z.object({
  created_at: z.string().nullable().optional(),
  expires_at: z.string().nullable().optional(),
  generated_at: z.string().nullable().optional(),
  joined_at: z.string().nullable().optional(),
  replied_at: z.string().nullable().optional(),
  updated_at: z.string().nullable().optional(),
});
const waitlistSnapshotSchema = z.object({
  configuration: waitlistConfigurationSchema,
  greeting: z.unknown().nullable().optional(),
  id: z.string().min(1),
  join: z.unknown().nullable().optional(),
  lifecycle: z.string(),
  reply: z.unknown().nullable().optional(),
  revision: z.number(),
  timestamps: waitlistTimestampsSchema,
});
const waitlistJoinConfirmationSchema = z.object({
  email: maskedEmailSchema.nullable().optional(),
  operation: z.string(),
  result_lifecycle: z.string(),
  result_revision: z.number(),
});

type WaitlistCreateOperation = operations["waitlist_create_273618b3"];
type WaitlistMutationHeaders = NonNullable<WaitlistCreateOperation["parameters"]["header"]>;

function waitlistMutationInit(idempotencyKey: string, signal?: AbortSignal) {
  const headers: WaitlistMutationHeaders = {
    "Idempotency-Key": idempotencyKey,
    // The app-owned request preparer replaces this with the readable csrftoken cookie.
    "X-CSRFToken": "",
  };
  return { params: { header: headers }, signal: normalizeRequestSignal(signal) };
}

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

export interface WaitlistConfigurationViewModel {
  name: string | null;
  appearanceCatalogVersion: string | null;
  appearanceKey: string | null;
  job: string | null;
  personality: string | null;
}

export interface WaitlistGreetingViewModel {
  text: string;
  policyVersion: string;
  generatedAt: string;
}

export interface WaitlistReplyViewModel {
  text: string;
  status: "pending";
  recordedAt: string;
}

export interface WaitlistJoinSnapshotViewModel {
  email: string;
  joinedAt: string;
}

export interface WaitlistTimestampsViewModel {
  createdAt: string | null;
  expiresAt: string | null;
  generatedAt: string | null;
  joinedAt: string | null;
  repliedAt: string | null;
  updatedAt: string | null;
}

export interface WaitlistSnapshotViewModel {
  id: string;
  lifecycle: string;
  revision: number;
  configuration: WaitlistConfigurationViewModel;
  greeting: WaitlistGreetingViewModel | null;
  reply: WaitlistReplyViewModel | null;
  join: WaitlistJoinSnapshotViewModel | null;
  timestamps: WaitlistTimestampsViewModel;
}

export interface WaitlistAcknowledgementViewModel {
  operation: string;
  resultLifecycle: string;
  resultRevision: number;
}

export interface WaitlistJoinConfirmationViewModel extends WaitlistAcknowledgementViewModel {
  email: string | null;
}

export interface WaitlistConfigurationInput {
  revision: number;
  idempotencyKey: string;
  name?: string | null;
  appearanceCatalogVersion?: string | null;
  appearanceKey?: string | null;
  job?: string | null;
  personality?: string | null;
}

export interface WaitlistGreetingInput {
  revision: number;
  idempotencyKey: string;
}

export interface WaitlistReplyInput {
  revision: number;
  idempotencyKey: string;
  text: string;
}

export interface WaitlistJoinInput {
  revision: number;
  idempotencyKey: string;
  email: string;
  consentVersion: string;
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

function parseReturnPath(value: string): string {
  const parsed = returnPathSchema.safeParse(value);
  if (!parsed.success) throw { kind: "bad-request" } satisfies CloudError;
  return parsed.data;
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
    async getCsrf(signal?: AbortSignal) {
      rejectPreAborted(signal);
      await noContent(api.GET("/api/v1/auths/csrf", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>);
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

    async getWaitlistSession(signal?: AbortSignal): Promise<void> {
      rejectPreAborted(signal);
      await noContent(api.GET("/api/v1/waitlist/session", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>);
    },

    async createWaitlistDraft(
      idempotencyKey: string,
      signal?: AbortSignal,
    ): Promise<WaitlistAcknowledgementViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/waitlist/draft", waitlistMutationInit(idempotencyKey, signal)) as Promise<ApiResult>,
        mapWaitlistAcknowledgement,
      );
    },

    async getWaitlistDraft(signal?: AbortSignal): Promise<WaitlistSnapshotViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.GET("/api/v1/waitlist/draft", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>,
        mapWaitlistSnapshot,
      );
    },

    async updateWaitlistConfiguration(
      input: WaitlistConfigurationInput,
      signal?: AbortSignal,
    ): Promise<WaitlistAcknowledgementViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.PATCH("/api/v1/waitlist/draft/configuration", {
          ...waitlistMutationInit(input.idempotencyKey, signal),
          body: {
            revision: input.revision,
            ...(input.name !== undefined ? { name: input.name } : {}),
            ...(input.appearanceCatalogVersion !== undefined
              ? { appearance_catalog_version: input.appearanceCatalogVersion }
              : {}),
            ...(input.appearanceKey !== undefined ? { appearance_key: input.appearanceKey } : {}),
            ...(input.job !== undefined ? { job: input.job } : {}),
            ...(input.personality !== undefined ? { personality: input.personality } : {}),
          },
        }) as Promise<ApiResult>,
        mapWaitlistAcknowledgement,
      );
    },

    async generateWaitlistGreeting(
      input: WaitlistGreetingInput,
      signal?: AbortSignal,
    ): Promise<WaitlistAcknowledgementViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/waitlist/draft/greeting", {
          ...waitlistMutationInit(input.idempotencyKey, signal),
          body: { revision: input.revision },
        }) as Promise<ApiResult>,
        mapWaitlistAcknowledgement,
      );
    },

    async recordWaitlistReply(
      input: WaitlistReplyInput,
      signal?: AbortSignal,
    ): Promise<WaitlistAcknowledgementViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/waitlist/draft/reply", {
          ...waitlistMutationInit(input.idempotencyKey, signal),
          body: { revision: input.revision, text: input.text },
        }) as Promise<ApiResult>,
        mapWaitlistAcknowledgement,
      );
    },

    async joinWaitlist(
      input: WaitlistJoinInput,
      signal?: AbortSignal,
    ): Promise<WaitlistJoinConfirmationViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/waitlist/draft/join", {
          ...waitlistMutationInit(input.idempotencyKey, signal),
          body: {
            revision: input.revision,
            email: input.email,
            consent_version: input.consentVersion,
          },
        }) as Promise<ApiResult>,
        (data) => {
          const confirmation = successEnvelope(waitlistJoinConfirmationSchema).parse(data).data;
          return {
            email: confirmation.email ?? null,
            operation: confirmation.operation,
            resultLifecycle: confirmation.result_lifecycle,
            resultRevision: confirmation.result_revision,
          };
        },
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

function mapWaitlistAcknowledgement(data: unknown): WaitlistAcknowledgementViewModel {
  const acknowledgement = successEnvelope(waitlistAcknowledgementSchema).parse(data).data;
  return {
    operation: acknowledgement.operation,
    resultLifecycle: acknowledgement.result_lifecycle,
    resultRevision: acknowledgement.result_revision,
  };
}

function parseOptionalWaitlistSection<T>(value: unknown, schema: z.ZodType<T>): T | null {
  if (value === null || value === undefined) return null;
  const parsed = schema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

function mapWaitlistSnapshot(data: unknown): WaitlistSnapshotViewModel {
  const snapshot = successEnvelope(waitlistSnapshotSchema).parse(data).data;
  const greeting = parseOptionalWaitlistSection(snapshot.greeting, waitlistGreetingSchema);
  const reply = parseOptionalWaitlistSection(snapshot.reply, waitlistReplySchema);
  const join = parseOptionalWaitlistSection(snapshot.join, waitlistJoinSnapshotSchema);
  return {
    id: snapshot.id,
    lifecycle: snapshot.lifecycle,
    revision: snapshot.revision,
    configuration: {
      name: snapshot.configuration.name ?? null,
      appearanceCatalogVersion: snapshot.configuration.appearance_catalog_version ?? null,
      appearanceKey: snapshot.configuration.appearance_key ?? null,
      job: snapshot.configuration.job ?? null,
      personality: snapshot.configuration.personality ?? null,
    },
    greeting: greeting
      ? {
          text: greeting.text,
          policyVersion: greeting.policy_version,
          generatedAt: greeting.generated_at,
        }
      : null,
    reply: reply
      ? {
          text: reply.text,
          status: reply.status,
          recordedAt: reply.recorded_at,
        }
      : null,
    join: join
      ? { email: join.email, joinedAt: join.joined_at }
      : null,
    timestamps: {
      createdAt: snapshot.timestamps.created_at ?? null,
      expiresAt: snapshot.timestamps.expires_at ?? null,
      generatedAt: snapshot.timestamps.generated_at ?? null,
      joinedAt: snapshot.timestamps.joined_at ?? null,
      repliedAt: snapshot.timestamps.replied_at ?? null,
      updatedAt: snapshot.timestamps.updated_at ?? null,
    },
  };
}

export type CloudClient = ReturnType<typeof createCloudClient>;
